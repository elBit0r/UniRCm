"""Password derivation and optional key file for portable archives."""
from ctypes import CDLL, c_int, c_size_t, c_uint32, c_void_p, create_string_buffer
from ctypes.util import find_library
from functools import lru_cache
import hashlib
import hmac
import os
import stat


@lru_cache(maxsize=1)
def _argon2():
    library = find_library('argon2')
    if not library:
        raise RuntimeError('libargon2 is required to unlock this archive.')
    derive = CDLL(library).argon2id_hash_raw
    derive.argtypes = (c_uint32, c_uint32, c_uint32, c_void_p, c_size_t,
                       c_void_p, c_size_t, c_void_p, c_size_t)
    derive.restype = c_int
    return derive


def _password_bytes(password):
    if not password or '\x00' in password:
        raise ValueError('Enter a nonempty master password without NUL characters.')
    return password.encode('utf-8')


def _argon2_key(encoded, salt):
    key = create_string_buffer(32)
    # RFC 9106's profile for memory-constrained environments.
    if _argon2()(3, 64 * 1024, 4, encoded, len(encoded), salt, len(salt), key, len(key)):
        raise RuntimeError('Argon2id key derivation failed.')
    return key.raw

def archive_passphrase(password, salt):
    return _argon2_key(_password_bytes(password), salt).hex()


class KeyFileError(ValueError):
    """The key file is missing or unreadable."""


def generate_key_file(path):
    secret = os.urandom(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(secret)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        os.unlink(path)
        raise


def _key_file_digest(path):
    if path is None:
        raise KeyFileError('Select the required key file.')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            entry = os.fstat(fd)
            if not stat.S_ISREG(entry.st_mode) or not entry.st_size:
                raise KeyFileError('Choose a nonempty regular key file.')
            with os.fdopen(fd, 'rb', closefd=False) as source:
                return hashlib.file_digest(source, 'sha256').digest()
        finally:
            os.close(fd)
    except OSError:
        raise KeyFileError('Unable to read the key file.') from None


def keyed_archive_passphrase(password, salt, key_file, *, iterations=None):
    file_digest = _key_file_digest(key_file)
    encoded = _password_bytes(password)
    if iterations is None:
        password_key = _argon2_key(encoded, salt)
    else:
        password_key = hashlib.pbkdf2_hmac('sha512', encoded, salt, iterations, dklen=32)
    # HKDF-SHA-256 extract uses the file digest as salt. Expand emits one block.
    prk = hmac.digest(file_digest, password_key, 'sha256')
    return hmac.digest(prk, b'UniRCm archive v4 SQLCipher passphrase\x01', 'sha256').hex()
