"""Small SFTP v3 client over an already authenticated OpenSSH control socket.

No shell commands, credentials or extra SSH authentication are used here.
"""
import os
import select
import stat
import struct
import subprocess
import threading
import time
from dataclasses import dataclass


def uint(value):
    return struct.pack('>I', value)


def string(value):
    if isinstance(value, str):
        value = value.encode('utf-8', 'surrogateescape')
    return uint(len(value)) + value


class Packet:
    def __init__(self, data):
        self.data = data

    def take(self, size):
        if len(self.data) < size:
            raise OSError('Invalid SFTP response.')
        result, self.data = self.data[:size], self.data[size:]
        return result

    def integer(self):
        return struct.unpack('>I', self.take(4))[0]

    def string(self):
        return self.take(self.integer())

    def text(self):
        return self.string().decode('utf-8', 'surrogateescape')

    def attrs(self):
        flags = self.integer()
        attrs = {}
        if flags & 1:
            attrs['size'] = struct.unpack('>Q', self.take(8))[0]
        if flags & 2:
            self.take(8)
        if flags & 4:
            attrs['mode'] = self.integer()
        if flags & 8:
            self.integer()  # access time
            attrs['mtime'] = self.integer()
        if flags & 0x80000000:
            for _ in range(self.integer()):
                self.string()
                self.string()
        return attrs


class SFTPError(OSError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class UploadCleanupError(OSError):
    def __init__(self, path, original, cleanup):
        self.path = path
        self.original = original
        super().__init__(f'{original} Temporary upload could not be removed: {path} ({cleanup})')


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    size: int | None
    mode: int | None
    mtime: int | None

    @property
    def directory(self):
        return stat.S_ISDIR(self.mode or 0)


class SFTPClient:
    def __init__(self, socket_path, host, cancelled=None, *, deadline=None):
        self.socket_path = socket_path
        self.host = host
        self.deadline = deadline
        self.cancelled = cancelled or threading.Event()
        self.sequence = 0
        self.process = subprocess.Popen(
            ['ssh', '-S', socket_path, '-o', 'ControlMaster=no',
             '-o', 'ProxyCommand=false', '-o', 'BatchMode=yes',
             '-o', 'ForwardAgent=no', '-T', '-s', '--', host, 'sftp'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        try:
            self.send(b'\x01' + uint(3))
            reply = self.receive()
            if reply.take(1) != b'\x02' or reply.integer() != 3:
                raise OSError('SFTP version 3 is required.')
            self.extensions = {}
            while reply.data:
                key, value = reply.string(), reply.string()
                self.extensions[key] = value
        except BaseException:
            self.close()
            raise

    def check(self):
        if self.cancelled.is_set():
            raise InterruptedError('Transfer cancelled.')

    def send(self, data):
        self.check()
        data = uint(len(data)) + data
        deadline = min(time.monotonic() + 30, self.deadline or float('inf'))
        while data:
            self.check()
            if time.monotonic() > deadline:
                raise TimeoutError('SFTP write timed out.')
            if not select.select([], [self.process.stdin], [], .1)[1]:
                continue
            try:
                written = os.write(self.process.stdin.fileno(), data)
            except BlockingIOError:
                continue
            data = data[written:]

    def read(self, size):
        result = bytearray()
        deadline = min(time.monotonic() + 30, self.deadline or float('inf'))
        while len(result) < size:
            self.check()
            if time.monotonic() > deadline:
                raise TimeoutError('SFTP server did not respond within 30 seconds.')
            if not select.select([self.process.stdout], [], [], .1)[0]:
                continue
            chunk = os.read(self.process.stdout.fileno(), size - len(result))
            if not chunk:
                raise OSError('SFTP channel closed. Check the SSH connection and SFTP server availability.')
            result.extend(chunk)
        return bytes(result)

    def receive(self):
        size = struct.unpack('>I', self.read(4))[0]
        if not 1 <= size <= 4 * 1024 * 1024:
            raise OSError('Invalid SFTP packet size.')
        return Packet(self.read(size))

    def request(self, kind, body=b'', expected=101):
        self.sequence += 1
        self.send(bytes([kind]) + uint(self.sequence) + body)
        reply = self.receive()
        received = reply.take(1)[0]
        if reply.integer() != self.sequence:
            raise OSError('Invalid SFTP request identifier.')
        if received == 101:
            code, message = reply.integer(), reply.text()
            if code:
                raise SFTPError(code, message)
        if received != expected:
            raise OSError('Unexpected SFTP response.')
        return reply

    def realpath(self, path):
        reply = self.request(16, string(path), 104)
        if reply.integer() != 1:
            raise OSError('Invalid SFTP path response.')
        return reply.text()

    def listing(self, path):
        handle = self.request(11, string(path), 102).string()
        entries = []
        try:
            while True:
                try:
                    reply = self.request(12, string(handle), 104)
                except SFTPError as error:
                    if error.code == 1:
                        break
                    raise
                for _ in range(reply.integer()):
                    name = reply.text()
                    reply.string()  # server's long listing is not a path
                    attrs = reply.attrs()
                    if name not in ('.', '..') and name and '/' not in name and '\x00' not in name:
                        entries.append(RemoteEntry(name, attrs.get('size'), attrs.get('mode'),
                                                   attrs.get('mtime')))
        finally:
            self.request(4, string(handle))
        return entries

    def size(self, path):
        return self.request(17, string(path), 105).attrs()['size']

    def mkdir(self, path):
        self.request(14, string(path) + uint(0))

    def rename(self, source, destination):
        self.request(18, string(source) + string(destination))

    def remove(self, path, *, directory=False):
        self.request(15 if directory else 13, string(path))

    def upload(self, local, remote, progress, overwrite=False):
        import uuid
        temporary = remote + '.unircm-' + uuid.uuid4().hex + '.part'
        self.check()
        handle = None
        opened = False
        try:
            handle = self.request(3, string(temporary) + uint(2 | 8 | 32) + uint(4) + uint(0o600), 102).string()
            opened = True
            with open(local, 'rb') as source:
                total = os.fstat(source.fileno()).st_size
                offset = 0
                progress(0, total)
                while chunk := source.read(32768):
                    self.request(6, string(handle) + struct.pack('>Q', offset) + string(chunk))
                    offset += len(chunk)
                    progress(offset, total)
            self.request(4, string(handle))
            handle = None
            if overwrite:
                if b'posix-rename@openssh.com' not in self.extensions:
                    raise OSError('This server cannot safely replace an existing file. Choose a different name.')
                self.request(200, string('posix-rename@openssh.com') + string(temporary) + string(remote))
            else:
                self.rename(temporary, remote)
        except BaseException as error:
            # An explicit rejected OPEN created nothing. Never delete a path
            # when the server rejected our exclusive creation (e.g. a collision).
            if not opened and isinstance(error, SFTPError):
                raise
            if isinstance(error, SFTPError):
                if handle is not None:
                    try:
                        self.request(4, string(handle))
                    except OSError:
                        pass
            else:
                # Cancellation may interrupt a packet or leave a response in
                # flight. That stream cannot safely carry a REMOVE request.
                self.close()
            try:
                self.remove_temporary_upload(temporary)
            except OSError as cleanup_error:
                raise UploadCleanupError(temporary, error, cleanup_error) from error
            raise

    def remove_temporary_upload(self, path):
        # A separate SFTP channel on the same authenticated master ignores the
        # cancelled operation's event. Bound handshake + removal to 3 seconds.
        cleanup = SFTPClient(self.socket_path, self.host, deadline=time.monotonic() + 3)
        try:
            try:
                cleanup.request(13, string(path))
            except SFTPError as error:
                if error.code != 2:  # already absent is also successful cleanup
                    raise
        finally:
            cleanup.close()

    def download(self, remote, local, progress, overwrite=False):
        import tempfile
        handle = self.request(3, string(remote) + uint(1) + uint(0), 102).string()
        temporary = None
        try:
            total = self.request(8, string(handle), 105).attrs().get('size', 0)
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(local), prefix='.unircm-', delete=False) as target:
                temporary = target.name
                offset = 0
                progress(0, total)
                while True:
                    try:
                        chunk = self.request(5, string(handle) + struct.pack('>Q', offset) + uint(32768), 103).string()
                    except SFTPError as error:
                        if error.code == 1:
                            break
                        raise
                    if not chunk:
                        raise OSError('SFTP server returned an empty data packet.')
                    target.write(chunk)
                    offset += len(chunk)
                    progress(offset, total)
            self.request(4, string(handle))
            handle = None
            self.check()
            if overwrite:
                os.replace(temporary, local)
            else:
                os.link(temporary, local)  # exclusive publication, including racing files/symlinks
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
            if handle is not None:
                self.request(4, string(handle))

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
