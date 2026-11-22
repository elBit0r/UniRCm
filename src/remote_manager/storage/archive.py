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

from .vault import DEFAULT_KDF_ITERATIONS, LEGACY_KDF_ITERATIONS, Vault, validate_kdf_iterations

MAX_DATABASE_SIZE = 256 * 1024 * 1024


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
            or data['format_version'] not in (1, 2) or not isinstance(data.get('description'), str)):
        raise ValueError('Unsupported UniRCm archive metadata.')
    if data['format_version'] == 2:
        validate_kdf_iterations(data.get('kdf_iterations'), minimum=DEFAULT_KDF_ITERATIONS)
    return data


class ArchiveVault(Vault):
    def __init__(self, path, password, description=None, *, kdf_iterations=DEFAULT_KDF_ITERATIONS):
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
                    kdf_iterations = (self.metadata['kdf_iterations'] if self.metadata['format_version'] == 2
                                      else LEGACY_KDF_ITERATIONS)
                    source.seek(0)
                    self._archive_digest = hashlib.file_digest(source, 'sha256').hexdigest()
                    self._prepare_working_directory()
                    if self._database.exists():
                        self._recover(password, kdf_iterations)
                    else:
                        self._write_recovery_digests(self._archive_digest)
                        with archive.open('database.db') as database:
                            self._replace_working_file(self._database, database)
            else:
                if self.archive_path.exists():
                    raise FileExistsError('Database already exists.')
                if len(description.encode('utf-8')) > 12000:
                    raise ValueError('Database description is too large.')
                validate_kdf_iterations(kdf_iterations, minimum=DEFAULT_KDF_ITERATIONS)
                self.metadata = dict(format_version=2, description=description, kdf_iterations=kdf_iterations)
                self._prepare_working_directory()
                if self._database.exists():
                    raise FileExistsError('An encrypted working copy already exists.')
                creating = True
            super().__init__(self._database, password, kdf_iterations=kdf_iterations)
            if description is not None:
                self.verify_key(self._database, password, kdf_iterations=kdf_iterations)
            self._persist()
            for pattern in ('stage-*', 'publish-*', '.unircm-rekey-*'):
                for leftover in self._working.glob(pattern):
                    leftover.unlink()
            self.connection = PersistingConnection(self.connection, self._persist)
        except Exception:
            try:
                if hasattr(self, 'connection'):
                    self.connection.close()
                if creating and not self.archive_path.exists():
                    shutil.rmtree(self._working)
            finally:
                self._lock.close()
            raise

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
        self.verify_key(self._database, password, kdf_iterations=kdf_iterations)

    def _persist(self):
        fd, name = tempfile.mkstemp(prefix='publish-', dir=self._working)
        try:
            with os.fdopen(fd, 'w+b') as output:
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                    archive.writestr('metadata.json', json.dumps(self.metadata, ensure_ascii=False))
                    archive.write(self._database, 'database.db')
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
