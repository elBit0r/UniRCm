"""Small RFB 3.8 viewer. Only password authentication and raw pixels are supported.

No security negotiation fallback: TLS-only servers are rejected, not downgraded.
LibVNCClient supplies the standard VNC DES challenge response.
"""
import ctypes as C
from ctypes.util import find_library
import select
import socket
import struct as S
import threading
from queue import Queue, Empty, Full

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from remote_manager.protocols.validation import validate_profile
from remote_manager.session import SessionStatus
from remote_manager.ui.icons import action_icon


_AUTH_LOCK = threading.Lock()

def challenge_response(challenge, password):
    if len(challenge) != 16:
        raise ValueError('Invalid VNC challenge.')
    name = find_library('vncclient')
    if not name:
        raise ValueError('VNC authentication requires LibVNCClient (libvncclient).')
    lib = C.CDLL(name)
    lib.rfbClientEncryptBytes.argtypes = [C.c_void_p, C.c_char_p]
    lib.rfbClientEncryptBytes.restype = None
    data = C.create_string_buffer(challenge, 16)
    with _AUTH_LOCK:
        lib.rfbClientEncryptBytes(data, password.encode('latin-1', errors='strict'))
    return data.raw


class VncWorker(QThread):
    frame = pyqtSignal(QImage)
    ended = pyqtSignal(int, str)
    ready = pyqtSignal(int, int)

    def __init__(self, profile, parent):
        super().__init__(parent)
        self.host, self.port = profile['host'].strip('[]'), profile['port']
        self.password = profile.get('password', '')
        self.cancel = threading.Event()
        self.commands = Queue(maxsize=512)
        self.sock = None
        self.latest = None
        self.frame_pending = False
        self.frame_lock = threading.Lock()

    def read(self, count):
        data = bytearray()
        while len(data) < count:
            if self.cancel.is_set():
                raise OSError('Stopped')
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise OSError('VNC server disconnected.')
            data.extend(chunk)
        return bytes(data)

    def send_input(self, packet):
        try:
            self.commands.put_nowait(packet)
        except Full:
            # Never lose a key/button release and leave remote input stuck.
            self.cancel.set()

    def stop(self):
        self.cancel.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self):
        code, message = 1, 'VNC connection failed.'
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=5)
            self.sock.settimeout(10)
            if self.read(12) != b'RFB 003.008\n':
                raise ValueError('This viewer currently requires RFB 3.8.')
            self.sock.sendall(b'RFB 003.008\n')
            types = self.read(self.read(1)[0])
            if 2 not in types:
                raise ValueError('VNC password authentication is required; TLS and unauthenticated servers are not supported.')
            if not self.password:
                raise ValueError('Set a password using the shared credential editor before connecting.')
            self.sock.sendall(b'\x02')
            self.sock.sendall(challenge_response(self.read(16), self.password))
            self.password = ''
            if self.read(4) != b'\0\0\0\0':
                raise ValueError('VNC authentication failed.')
            self.sock.sendall(b'\x01')  # shared desktop
            header = self.read(24)
            width, height = S.unpack('!HH', header[:4])
            if not width or not height or width * height > 16_777_216:
                raise ValueError('VNC desktop exceeds the supported size.')
            name_length = S.unpack('!I', header[20:24])[0]
            if name_length > 1024 * 1024:
                raise ValueError('Invalid VNC desktop name length.')
            self.read(name_length)
            # Fixed RGBX bytes, independent of server native pixel layout.
            fmt = S.pack('!BBBBHHHBBB3x', 32, 24, 0, 1, 255, 255, 255, 0, 8, 16)
            self.sock.sendall(b'\0\0\0\0' + fmt)
            self.sock.sendall(S.pack('!BBHi', 2, 0, 1, 0))  # raw only
            request = lambda incremental: S.pack('!BBHHHH', 3, incremental, 0, 0, width, height)
            self.sock.sendall(request(0))
            image = QImage(width, height, QImage.Format.Format_RGBX8888)
            image.fill(Qt.GlobalColor.black)
            self.ready.emit(width, height)
            while not self.cancel.is_set():
                for _ in range(128):
                    try:
                        self.sock.sendall(self.commands.get_nowait())
                    except Empty:
                        break
                if not select.select([self.sock], [], [], .03)[0]:
                    continue
                kind = self.read(1)[0]
                if kind == 0:
                    count = S.unpack('!xH', self.read(3))[0]
                    for _ in range(count):
                        x, y, w, h, encoding = S.unpack('!HHHHi', self.read(12))
                        if encoding != 0 or not w or not h or x+w > width or y+h > height:
                            raise ValueError('Unsupported VNC framebuffer rectangle.')
                        pixels = self.read(w*h*4)
                        rectangle = QImage(pixels, w, h, w*4, QImage.Format.Format_RGBX8888)
                        painter = QPainter(image)
                        painter.drawImage(x, y, rectangle)
                        painter.end()
                    with self.frame_lock:
                        self.latest = image.copy()
                        if not self.frame_pending:
                            self.frame_pending = True
                            self.frame.emit(QImage())
                    self.sock.sendall(request(1))
                elif kind == 2:  # bell
                    pass
                elif kind == 3:
                    length = S.unpack('!3xI', self.read(7))[0]
                    if length > 1024*1024:
                        raise ValueError('VNC clipboard exceeds the supported size.')
                    self.read(length)  # clipboard intentionally not synchronized yet
                else:
                    raise ValueError('Unsupported VNC server message.')
            code, message = 0, 'Disconnected.'
        except (OSError, ValueError, UnicodeError):
            # Do not expose server-controlled strings or credential-bearing exceptions.
            if self.cancel.is_set():
                code, message = 0, 'Disconnected.'
            else:
                message = 'VNC connection failed: check server, RFB 3.8 password authentication and LibVNCClient availability.'
        finally:
            self.password = ''
            if self.sock:
                self.sock.close()
            self.ended.emit(code, message)


class VncCanvas(QWidget):
    SPECIAL = {Qt.Key.Key_Backspace: 0xff08, Qt.Key.Key_Tab: 0xff09,
               Qt.Key.Key_Return: 0xff0d, Qt.Key.Key_Enter: 0xff0d,
               Qt.Key.Key_Escape: 0xff1b, Qt.Key.Key_Delete: 0xffff,
               Qt.Key.Key_Home: 0xff50, Qt.Key.Key_End: 0xff57,
               Qt.Key.Key_Left: 0xff51, Qt.Key.Key_Up: 0xff52,
               Qt.Key.Key_Right: 0xff53, Qt.Key.Key_Down: 0xff54,
               Qt.Key.Key_PageUp: 0xff55, Qt.Key.Key_PageDown: 0xff56,
               Qt.Key.Key_Shift: 0xffe1, Qt.Key.Key_Control: 0xffe3,
               Qt.Key.Key_Alt: 0xffe9, Qt.Key.Key_Meta: 0xffeb}

    def __init__(self, worker, parent):
        super().__init__(parent)
        self.worker, self.image, self.view_only = worker, QImage(), False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.pressed = set()
        self.setMinimumSize(160, 100)

    def receive(self, _):
        with self.worker.frame_lock:
            self.image = self.worker.latest
            self.worker.frame_pending = False
        self.update()

    def target(self):
        from PyQt6.QtCore import QRect
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width()-size.width())//2, (self.height()-size.height())//2, size.width(), size.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self.image.isNull():
            painter.drawImage(self.target(), self.image)

    def keyPressEvent(self, event):
        if self.view_only or event.isAutoRepeat():
            return
        key = self.SPECIAL.get(event.key())
        if Qt.Key.Key_F1 <= event.key() <= Qt.Key.Key_F12:
            key = 0xffbe + event.key() - Qt.Key.Key_F1
        if key is None and event.text():
            point = ord(event.text()[0])
            key = point if point <= 255 else 0x1000000 | point
        if key:
            self.pressed.add(key)
            self.worker.send_input(S.pack('!BBHI', 4, 1, 0, key))
            self.setProperty(str(event.key()), key)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            return
        key = self.property(str(event.key()))
        if key in self.pressed:
            self.worker.send_input(S.pack('!BBHI', 4, 0, 0, key))
            self.pressed.discard(key)

    def release_input(self):
        for key in self.pressed:
            self.worker.send_input(S.pack('!BBHI', 4, 0, 0, key))
        self.pressed.clear()
        self.worker.send_input(S.pack('!BBHH', 5, 0, 0, 0))

    def focusOutEvent(self, event):
        self.release_input()
        super().focusOutEvent(event)

    def mouseMoveEvent(self, event):
        if self.view_only or self.image.isNull():
            return
        target = self.target()
        if not target.width() or not target.height():
            return
        x = max(0, min(self.image.width()-1, int((event.position().x()-target.x()) * self.image.width()/target.width())))
        y = max(0, min(self.image.height()-1, int((event.position().y()-target.y()) * self.image.height()/target.height())))
        buttons = event.buttons()
        mask = sum(bit for button, bit in ((Qt.MouseButton.LeftButton, 1), (Qt.MouseButton.MiddleButton, 2), (Qt.MouseButton.RightButton, 4)) if buttons & button)
        self.worker.send_input(S.pack('!BBHH', 5, mask, x, y))

    def mousePressEvent(self, event):
        self.setFocus()
        self.mouseMoveEvent(event)

    mouseReleaseEvent = mouseMoveEvent


class VncSession(QWidget):
    exited = pyqtSignal(int)

    def __init__(self, profile, parent=None):
        validate_profile(profile)
        super().__init__(parent)
        self.embedded = True
        self.profile_id = profile.get('id')
        self.options = profile.get('terminal_options', {})
        self.session_status = SessionStatus('vnc', profile['host'], profile['port'], profile.get('username', ''), self)
        self.worker = VncWorker(profile, self)
        self.canvas = VncCanvas(self.worker, self)
        layout = QVBoxLayout(self)
        warning = QLabel(self.tr('Unencrypted VNC — use a trusted network or an SSH tunnel. Classic VNC uses only the first eight password bytes; the username is not sent.'))
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.result = QLabel(self.tr('Connecting…'))
        layout.addWidget(self.result)
        controls = QHBoxLayout()
        self.view_button = QPushButton(self.tr('View only'))
        self.view_button.setIcon(action_icon(self, 'View only'))
        self.view_button.setToolTip(self.tr('Disable keyboard and mouse input to the remote desktop.'))
        self.view_button.setCheckable(True)
        self.view_button.toggled.connect(self.set_view_only)
        controls.addWidget(self.view_button)
        self.disconnect_button = QPushButton(self.tr('Disconnect'))
        self.disconnect_button.setIcon(action_icon(self, 'Disconnect'))
        self.disconnect_button.setToolTip(self.tr('Close the VNC connection.'))
        self.disconnect_button.clicked.connect(self.stop)
        controls.addWidget(self.disconnect_button)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        self.worker.frame.connect(self.canvas.receive)
        self.worker.ready.connect(self.connected)
        self.worker.ended.connect(self.finished)
        self.worker.start()

    def connected(self, width, height):
        self.session_status.set_desktop_size(width, height)
        self.session_status.set_state('connected')
        self.result.setText(self.tr('Connected — VNC desktop'))
        self.canvas.setFocus()

    def set_view_only(self, value):
        self.canvas.release_input()
        self.canvas.view_only = value

    def finished(self, code, message):
        self.result.setText(self.tr(message))
        self.disconnect_button.setEnabled(False)
        self.canvas.setEnabled(False)
        self.session_status.finish(code)
        self.exited.emit(code)

    def apply_options(self, options):
        self.options = options

    def is_running(self):
        return self.worker.isRunning()

    def stop(self):
        self.worker.stop()
        # create_connection and reads have bounded timeouts; never destroy a live QThread.
        self.worker.wait()
