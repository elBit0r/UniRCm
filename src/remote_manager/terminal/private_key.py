"""Pass private keys to OpenSSH through an anonymous Linux file descriptor."""
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import uuid


def open_memory_key(data):
    if not hasattr(os, 'memfd_create') or not os.path.isdir('/proc/self/fd'):
        raise ValueError('Imported SSH keys require Linux with /proc available.')
    # A unique name keeps the askpass prompt bound to this specific key.
    fd = os.memfd_create('unircm-key-' + uuid.uuid4().hex, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(os.dup(fd), 'wb') as output:
            output.write(data)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        path = f'/proc/{os.getpid()}/fd/{fd}'
        return fd, path
    except BaseException:
        os.close(fd)
        raise


def read_imported_key(filename):
    source = Path(filename)
    limit = 128 * 1024
    try:
        # Avoid blocking on a FIFO or reading from a device selected as a key.
        fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Select an OpenSSH private key file up to 128 KiB.')
            data = stream.read(limit + 1)
    except OSError:
        raise ValueError('Unable to read the selected SSH private key.') from None
    if (len(data) > limit or not data.startswith(b'-----BEGIN OPENSSH PRIVATE KEY-----')
            or not data.rstrip().endswith(b'-----END OPENSSH PRIVATE KEY-----')):
        raise ValueError('Select an OpenSSH private key file up to 128 KiB.')
    fd, path = open_memory_key(data)
    try:
        result = subprocess.run(['ssh-keygen', '-l', '-f', path], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('Unable to validate the selected SSH key with ssh-keygen.') from None
    finally:
        os.close(fd)
    if result.returncode:
        raise ValueError('The selected OpenSSH private key could not be read by ssh-keygen.')
    return source.name, data
