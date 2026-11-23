"""Portable .uni containers: public description and SQLCipher-only contents."""
import fcntl
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

from .kdf import KeyFileError, archive_passphrase, keyed_archive_passphrase
from .vault import (BackupError, DEFAULT_KDF_ITERATIONS, LEGACY_KDF_ITERATIONS,
                    SCHEMA_VERSION, UnsupportedSchemaVersion, Vault, backup_path,
                    check_encrypted_header, publish_copy, validate_kdf_iterations)

MAX_DATABASE_SIZE = 256 * 1024 * 1024
KEEP_KEY_FILE = object()


class RecoveryConflict(ValueError):
    """The archive was replaced while a working copy was left behind."""


class ArchiveInUse(BlockingIOError):
    """Another open vault holds the archive lock."""


def metadata(path):
    with zipfile.ZipFile(path) as archive:
        return _read_metadata(archive)


def _read_metadata(archive):
    if sorted(archive.namelist()) != ['database.db', 'metadata.json']:
        raise ValueError('Invalid UniRCm archive contents.')
    if archive.getinfo('database.db').file_size > MAX_DATABASE_SIZE:
        raise ValueError('Database exceeds the 256 MiB limit.')
    if archive.getinfo('metadata.json').file_size > 16384:
        raise ValueError('Database description is too large.')
    data = json.loads(archive.read('metadata.json'))
    if (not isinstance(data, dict) or type(data.get('format_version')) is not int
            or data['format_version'] not in (1, 2, 3, 4) or not isinstance(data.get('description'), str)):
        raise ValueError('Unsupported UniRCm archive metadata.')
    version = data['format_version']
    if version == 4 and data.get('key_file_required') is not True:
        raise ValueError('Invalid key file requirement.')
    if version == 2 or (version == 4 and 'kdf_iterations' in data):
        validate_kdf_iterations(data.get('kdf_iterations'), minimum=DEFAULT_KDF_ITERATIONS)
    if version in (3, 4):
        salt = data.get('password_salt' if version == 4 else 'argon2_salt')
        if (not isinstance(salt, str) or len(salt) != 32
                or any(character not in '0123456789abcdef' for character in salt)):
            raise ValueError('Invalid password derivation salt.')
    return data


def _key_settings(data, password, key_file=None):
    version = data['format_version']
    if version == 4:
        iterations = data.get('kdf_iterations')
        key = keyed_archive_passphrase(password, bytes.fromhex(data['password_salt']), key_file,
                                       iterations=iterations)
        return key, iterations if iterations is not None else DEFAULT_KDF_ITERATIONS
    if version == 3:
        return archive_passphrase(password, bytes.fromhex(data['argon2_salt'])), DEFAULT_KDF_ITERATIONS
    return password, data['kdf_iterations'] if version == 2 else LEGACY_KDF_ITERATIONS


def _with_key_file_requirement(data, required):
    if required == (data['format_version'] == 4):
        return data
    description = data['description']
    iterations = data.get('kdf_iterations')
    if required:
        updated = dict(format_version=4, description=description, key_file_required=True,
                       password_salt=data.get('argon2_salt') or os.urandom(16).hex())
        if iterations is not None:
            updated['kdf_iterations'] = iterations
        return updated
    if iterations is not None:
        return dict(format_version=2, description=description, kdf_iterations=iterations)
    return dict(format_version=3, description=description, argon2_salt=data['password_salt'])


def _verify_archive(path, key_settings):
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(dir=path.parent) as directory:
        key, iterations = key_settings(_read_metadata(archive))
        database = Path(directory) / 'database.db'
        fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as output, archive.open('database.db') as encrypted:
            check_encrypted_header(encrypted)
            shutil.copyfileobj(encrypted, output)
        return Vault.verify_key(database, key, kdf_iterations=iterations)


def restore_backup(source, destination, password, *, is_archive, key_file=None):
    def verify(path):
        schema = (_verify_archive(path, lambda data: _key_settings(data, password, key_file))
                  if is_archive else Vault.verify_key(path, password))
        if schema not in range(SCHEMA_VERSION + 1):
            raise UnsupportedSchemaVersion('Unsupported database schema version.')

    publish_copy(source, destination, verify, raw_database=not is_archive)


class ArchiveVault(Vault):
    def __init__(self, path, password, description=None, *, kdf_iterations=None, key_file=None):
        self.archive_path = Path(path).resolve()
        self._working = self.archive_path.with_name('.' + self.archive_path.name + '.working')
        self._database = self._working / 'database.db'
        self._archive_digest = None
        self._closed = False
        creating = False
        lock_fd = os.open(str(self.archive_path) + '.lock',
                          os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        self._lock = os.fdopen(lock_fd, 'r+b')
        try:
            lock = os.fstat(lock_fd)
            if not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.getuid() or lock.st_nlink != 1:
                raise PermissionError('Unsafe database lock file.')
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ArchiveInUse('Database is already open.') from error
            os.fchmod(lock_fd, 0o600)
            if description is None:
                with self.archive_path.open('rb') as source, zipfile.ZipFile(source) as archive:
                    self.metadata = _read_metadata(archive)
                    if self.key_file_required:
                        self._check_key_file_path(key_file)
                    key, kdf_iterations = _key_settings(self.metadata, password, key_file)
                    source.seek(0)
                    self._archive_digest = hashlib.file_digest(source, 'sha256').hexdigest()
                    self._prepare_working_directory()
                    if self._database.exists():
                        self._recover(key, kdf_iterations)
                    else:
                        self._write_recovery_digests(self._archive_digest)
                        with archive.open('database.db') as database:
                            check_encrypted_header(database)
                            self._replace_working_file(self._database, database)
            else:
                if self.archive_path.exists():
                    raise FileExistsError('Database already exists.')
                if len(description.encode('utf-8')) > 12000:
                    raise ValueError('Database description is too large.')
                if kdf_iterations is None:
                    self.metadata = dict(format_version=3, description=description, argon2_salt=os.urandom(16).hex())
                else:
                    validate_kdf_iterations(kdf_iterations, minimum=DEFAULT_KDF_ITERATIONS)
                    self.metadata = dict(format_version=2, description=description, kdf_iterations=kdf_iterations)
                self._check_key_file_path(key_file)
                self.metadata = _with_key_file_requirement(self.metadata, key_file is not None)
                key, kdf_iterations = _key_settings(self.metadata, password, key_file)
                self._prepare_working_directory()
                if self._database.exists():
                    raise FileExistsError('An encrypted working copy already exists.')
                creating = True
            super().__init__(self._database, key, kdf_iterations=kdf_iterations)
            if description is not None:
                self.verify_key(self._database, key, kdf_iterations=kdf_iterations)
            if self.metadata['format_version'] == 1:
                self._upgrade_legacy(key)
            else:
                self._persist()
                self.connection = PersistingConnection(self.connection, self._persist)
            for pattern in ('stage-*', 'publish-*', '.unircm-rekey-*'):
                for leftover in self._working.glob(pattern):
                    leftover.unlink()
        except Exception:
            try:
                if hasattr(self, 'connection'):
                    self.connection.close()
                if creating and not self.archive_path.exists():
                    shutil.rmtree(self._working)
            finally:
                self._lock.close()
            raise

    def _check_key_file_path(self, key_file):
        if key_file is None:
            return
        try:
            path = Path(key_file).resolve()
        except (OSError, RuntimeError):
            raise KeyFileError('Unable to read the key file.') from None
        if path == self.archive_path or path.is_relative_to(self._working):
            raise KeyFileError('Choose a key file outside the database and its working directory.')

    def _prepare_working_directory(self):
        self._working.mkdir(mode=0o700, exist_ok=True)
        directory = self._working.lstat()
        if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid()
                or stat.S_IMODE(directory.st_mode) != 0o700):
            raise PermissionError('Unsafe encrypted working directory.')
        for path in self._working.iterdir():
            entry = path.lstat()
            if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.getuid()
                    or entry.st_mode & 0o077):
                raise PermissionError('Unsafe encrypted working file.')

    def _replace_working_file(self, path, source):
        with tempfile.NamedTemporaryFile(prefix='stage-', dir=self._working, delete=False) as target:
            staging = Path(target.name)
            try:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
                os.replace(staging, path)
            finally:
                staging.unlink(missing_ok=True)

    def _write_recovery_digests(self, *digests):
        # Accept the archive on either side of the atomic publication.
        self._replace_working_file(self._working / 'archives.json',
                                   BytesIO(json.dumps(digests).encode('ascii')))

    def _recover(self, password, kdf_iterations):
        marker = self._working / 'archives.json'
        if not marker.exists() or self._archive_digest not in json.loads(marker.read_bytes()):
            raise RecoveryConflict('The encrypted working copy belongs to a different version of this archive.')
        if not 0 < self._database.stat().st_size <= MAX_DATABASE_SIZE:
            raise ValueError('Invalid encrypted working database size.')
        original = self._password_recovery_path(None)
        if original.exists():
            self.verify_key(original, password, kdf_iterations=kdf_iterations)
            os.replace(original, self._database)
            # Renaming over a hard link to the same inode is a no-op.
            original.unlink(missing_ok=True)
        else:
            self.verify_key(self._database, password, kdf_iterations=kdf_iterations)

    def _password_recovery_path(self, candidate):
        # Only an archive with the old digest can recover the old key.
        return self._working / f'.unircm-rekey-{self._archive_digest}.original'

    def _write_archive(self, output, database):
        if not 0 < database.stat().st_size <= MAX_DATABASE_SIZE:
            raise ValueError('Invalid encrypted database size.')
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('metadata.json', json.dumps(self.metadata, ensure_ascii=False))
            archive.write(database, 'database.db')

    def _backup(self, password, reason, schema):
        try:
            with tempfile.NamedTemporaryFile(dir=self._working) as package:
                self._write_archive(package, self._database)
                package.flush()
                publish_copy(package.name, backup_path(self.archive_path, reason, schema),
                             lambda path: _verify_archive(path, lambda _: (password, self.kdf_iterations)))
        except Exception as error:
            raise BackupError('Unable to create a verified encrypted backup.') from error

    def _upgrade_legacy(self, key):
        schema = self.connection.execute('PRAGMA user_version').fetchone()[0]
        self._backup(key, 'kdf', schema)
        previous = self.metadata
        self.metadata = dict(format_version=2, description=previous['description'],
                             kdf_iterations=DEFAULT_KDF_ITERATIONS)
        try:
            self._replace_encryption(key, key, DEFAULT_KDF_ITERATIONS)
        except Exception:
            self.metadata = previous
            raise

    @property
    def key_file_required(self):
        return self.metadata['format_version'] == 4

    def change_password(self, current, replacement, *, key_file=None, new_key_file=KEEP_KEY_FILE):
        if new_key_file is KEEP_KEY_FILE:
            new_key_file = key_file if self.key_file_required else None
        self._check_key_file_path(key_file)
        self._check_key_file_path(new_key_file)
        previous = self.metadata
        updated = _with_key_file_requirement(previous, new_key_file is not None)
        current_key, _ = _key_settings(previous, current, key_file)
        replacement_key, iterations = _key_settings(updated, replacement, new_key_file)
        schema = self._verify_rekey(current_key, replacement_key)
        reason = 'key-file' if new_key_file != key_file else 'password'
        self._backup(current_key, reason, schema)
        self.metadata = updated
        try:
            self._replace_encryption(current_key, replacement_key, iterations)
        except Exception:
            self.metadata = previous
            raise

    def _persist(self):
        fd, name = tempfile.mkstemp(prefix='publish-', dir=self._working)
        try:
            with os.fdopen(fd, 'w+b') as output:
                self._write_archive(output, self._database)
                output.flush()
                os.fsync(output.fileno())
                output.seek(0)
                digest = hashlib.file_digest(output, 'sha256').hexdigest()
            self._write_recovery_digests(self._archive_digest, digest)
            os.replace(name, self.archive_path)
            self._archive_digest = digest
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def set_description(self, description):
        if not isinstance(description, str) or len(description.encode('utf-8')) > 12000:
            raise ValueError('Database description is too large.')
        previous = self.metadata
        self.metadata = dict(previous, description=description)
        try:
            self._persist()
        except Exception:
            self.metadata = previous
            raise

    def _reopen(self, password):
        super()._reopen(password)
        self.connection = PersistingConnection(self.connection, self._persist)

    def _publish_password_change(self):
        self._persist()

    def close(self):
        if self._closed:
            return
        # Retry a failed archive write before releasing the working copy.
        if self.connection.in_transaction:
            self.connection.rollback()
        self._persist()
        super().close()
        self._closed = True
        try:
            self._database.unlink()
            shutil.rmtree(self._working)
        finally:
            self._lock.close()


class PersistingConnection:
    """Publish each committed mutation before the UI reports success."""
    def __init__(self, connection, persist):
        object.__setattr__(self, '_connection', connection)
        object.__setattr__(self, '_persist', persist)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value):
        setattr(self._connection, name, value)

    def __enter__(self):
        return self._connection.__enter__()

    def __exit__(self, *exc):
        result = self._connection.__exit__(*exc)
        if exc[0] is None:
            self._persist()
        return result
