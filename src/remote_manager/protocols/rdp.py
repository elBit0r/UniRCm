"""FreeRDP framebuffer rendered by Qt, independent of the window system."""
import ctypes as C
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import uuid

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QEvent, QTimer, QMimeData
from PyQt6.QtGui import QImage, QPainter, QCursor, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QMessageBox, QHBoxLayout, QPushButton, QApplication

from remote_manager.connection_commands import ConnectionCommands
from remote_manager.session import SessionStatus
from remote_manager.rdp_options import effective_options, native_flags, desktop_size
from remote_manager.ui.icons import action_icon

FRAME = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_int, C.c_int)
POINTER = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int)
CLIPBOARD = C.CFUNCTYPE(None, C.c_void_p, C.c_int)
CLIP_LIMIT = 1024 * 1024
CLIP_ORIGIN = "application/x-unircm-rdp-clipboard"

CERT = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_char_p, C.c_char_p, C.c_int)


def authentication_identity(username, domain=''):
    if '\\' in username:
        prefix, username = username.split('\\', 1)
        domain = domain or prefix
    return username, domain


def load_bridge():
    path = Path(__file__).with_name('native') / 'librdp.so'
    if not path.exists():
        raise ValueError('Native RDP requires FreeRDP 3 development libraries. Run python -m remote_manager.protocols.build_rdp first.')
    try:
        lib = C.CDLL(str(path))
        lib.urdp_abi_version.restype = C.c_uint
        if lib.urdp_abi_version() != 3:
            raise AttributeError('RDP bridge ABI mismatch')
    except (OSError, AttributeError) as error:
        raise ValueError('Rebuild the native RDP backend with python -m remote_manager.protocols.build_rdp.') from error
    signatures = {
        'new': ([C.c_char_p, C.c_uint, C.c_char_p, C.c_char_p, C.c_char_p, C.c_uint, C.c_uint, FRAME, CERT], C.c_void_p),
        'callbacks': ([C.c_void_p, POINTER, CLIPBOARD], None),
        'clipboard': ([C.c_void_p, C.c_char_p, C.c_uint], C.c_int),
        'clipboard_status': ([C.c_void_p], C.c_uint),
        'clipboard_request': ([C.c_void_p], C.c_int),
        'configure': ([C.c_void_p, C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_int], C.c_int),
        'resize': ([C.c_void_p, C.c_uint, C.c_uint], C.c_int),
        'display_control': ([C.c_void_p], C.c_int),
        'connect': ([C.c_void_p], C.c_int), 'step': ([C.c_void_p], C.c_int),
        'error': ([C.c_void_p], C.c_uint), 'free': ([C.c_void_p], None),
        'abort': ([C.c_void_p], None),
        'mouse': ([C.c_void_p, C.c_uint, C.c_uint, C.c_uint], C.c_int),
        'key': ([C.c_void_p, C.c_uint, C.c_uint, C.c_int], C.c_int),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, 'urdp_' + name)
        fn.argtypes, fn.restype = args, result
    return lib


class RdpWorker(QThread):
    connected = pyqtSignal()
    display_control = pyqtSignal(bool)
    certificate = pyqtSignal(str, str, str, bool)
    ended = pyqtSignal(int)
    frame_ready = pyqtSignal()
    pointer_ready = pyqtSignal()
    clipboard_ready = pyqtSignal()
    clipboard_status = pyqtSignal(int)

    def __init__(self, lib, profile, parent):
        super().__init__(parent)
        self.lib = lib
        self.credentials = (profile['host'], profile['port'], profile.get('username', ''), profile.get('password', ''), profile.get('rdp_domain', ''))
        self.options = effective_options(profile.get('rdp_options', {}))
        self.initial_size = desktop_size(self.options, 1280, 720)
        self.commands = Queue(maxsize=2048)
        self.cancel = threading.Event()
        self.cert_answer = threading.Event()
        self.accept_cert = False
        self.lock = threading.Lock()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.handle = None
        self.pointer_lock = threading.Lock()
        self.latest_pointer = None
        self.clipboard_lock = threading.Lock()
        self.latest_clipboard = None
        self.local_clipboard = None
        self.clipboard_requested = False
        self.clipboard_state = 0

    def receive_pointer(self, data, width, height, hot_x, hot_y):
        if width in (0, -1):
            value = (None, width, 0, 0)
        elif data and 0 < width <= 512 and 0 < height <= 512:
            image = QImage(C.string_at(data, width * height * 4), width, height,
                           width * 4, QImage.Format.Format_RGBA8888).copy()
            value = (image, 1, max(0, min(width-1, hot_x)), max(0, min(height-1, hot_y)))
        else:
            return
        with self.pointer_lock:
            notify = self.latest_pointer is None
            self.latest_pointer = value
        if notify:
            self.pointer_ready.emit()

    def receive_clipboard(self, data, length):
        if not self.options['clipboard'] or self.cancel.is_set():
            return
        if length == -1:
            value = (False, '')  # Remote text is available; GUI decides whether to request it.
        elif data and 2 <= length <= CLIP_LIMIT and length % 2 == 0:
            raw = C.string_at(data, length)
            if raw[-2:] != b'\x00\x00':
                return
            try:
                text = raw.decode('utf-16-le').split('\x00', 1)[0]
            except UnicodeDecodeError:
                return
            value = (True, text.replace('\r\n', '\n'))
        else:
            return
        with self.clipboard_lock:
            notify = self.latest_clipboard is None
            self.latest_clipboard = value
        if notify:
            self.clipboard_ready.emit()

    def offer_clipboard(self, text):
        if not self.options['clipboard'] or self.cancel.is_set() or len(text) > CLIP_LIMIT // 2:
            return
        text = text.replace('\r\n', '\n').replace('\r', '\n').split('\x00', 1)[0]
        try:
            data = (text.replace('\n', '\r\n') + '\x00').encode('utf-16-le')
        except UnicodeEncodeError:
            return
        if len(data) <= CLIP_LIMIT:
            with self.clipboard_lock:
                self.local_clipboard = data

    def request_clipboard(self):
        if self.options['clipboard'] and not self.cancel.is_set():
            with self.clipboard_lock:
                self.clipboard_requested = True

    def receive_frame(self, data, width, height, stride):
        # One pending image and one notification: slow painting cannot build a frame backlog.
        image = QImage(C.string_at(data, stride * height), width, height, stride, QImage.Format.Format_RGB32).copy()
        with self.frame_lock:
            notify = self.latest_frame is None
            self.latest_frame = image
        if notify:
            self.frame_ready.emit()

    def verify(self, host, subject, fingerprint, changed):
        self.cert_answer.clear()
        self.accept_cert = False
        self.certificate.emit(*(v.decode('utf-8', 'replace') if v else '' for v in (host, subject, fingerprint)), bool(changed))
        while not self.cert_answer.wait(.1):
            if self.cancel.is_set():
                return 0
        return int(self.accept_cert and not self.cancel.is_set())

    def stop(self):
        self.cancel.set()
        self.cert_answer.set()
        with self.clipboard_lock:
            self.latest_clipboard = self.local_clipboard = None
            self.clipboard_requested = False
        with self.lock:
            if self.handle:
                self.lib.urdp_abort(self.handle)

    def run(self):
        frame, cert = FRAME(self.receive_frame), CERT(self.verify)
        pointer, clipboard = POINTER(self.receive_pointer), CLIPBOARD(self.receive_clipboard)
        host, port, username, password, domain = self.credentials
        self.credentials = None
        username, domain = authentication_identity(username, domain)
        code = 1
        try:
            with self.lock:
                self.handle = self.lib.urdp_new(host.encode(), port, username.encode(), password.encode(), domain.encode(), *self.initial_size, frame, cert)
            password = None
            if not self.handle or self.cancel.is_set():
                return
            self.lib.urdp_callbacks(self.handle, pointer, clipboard)
            options = self.options
            if not self.lib.urdp_configure(self.handle, options['connection_speed'], options['color_depth'],
                                            options['timeout'], native_flags(options), options['resolution'] == 'automatic'):
                return
            if not self.lib.urdp_connect(self.handle):
                code = self.lib.urdp_error(self.handle) or 1
                return
            self.connected.emit()
            last_display_control = None
            while not self.cancel.is_set():
                with self.clipboard_lock:
                    local, requested = self.local_clipboard, self.clipboard_requested
                    self.local_clipboard = None
                    self.clipboard_requested = False
                if local is not None:
                    self.lib.urdp_clipboard(self.handle, local, len(local))
                if requested:
                    self.lib.urdp_clipboard_request(self.handle)
                local = None
                for _ in range(128):
                    try:
                        name, args = self.commands.get_nowait()
                    except Empty:
                        break
                    if not getattr(self.lib, 'urdp_' + name)(self.handle, *args):
                        self.cancel.set()
                        break
                if not self.lib.urdp_step(self.handle):
                    break
                state = self.lib.urdp_clipboard_status(self.handle)
                if state != self.clipboard_state:
                    self.clipboard_state = state
                    self.clipboard_status.emit(state)
                supported = bool(self.lib.urdp_display_control(self.handle))
                if supported != last_display_control:
                    last_display_control = supported
                    self.display_control.emit(supported)
            code = 0 if self.cancel.is_set() else self.lib.urdp_error(self.handle)
        finally:
            password = None
            with self.lock:
                if self.handle:
                    self.lib.urdp_free(self.handle)
                    self.handle = None
            with self.clipboard_lock:
                self.latest_clipboard = self.local_clipboard = None
                self.clipboard_requested = False
            self.ended.emit(code)


# RDP set-1 scancodes for control keys; printable text uses Unicode events.
KEYS = {Qt.Key.Key_Escape: 1, Qt.Key.Key_Backspace: 14, Qt.Key.Key_Tab: 15,
        Qt.Key.Key_Return: 28, Qt.Key.Key_Enter: 28, Qt.Key.Key_Control: 29,
        Qt.Key.Key_Shift: 42, Qt.Key.Key_Alt: 56, Qt.Key.Key_Meta: 0x15b,
        Qt.Key.Key_Home: 0x147, Qt.Key.Key_Up: 0x148, Qt.Key.Key_PageUp: 0x149,
        Qt.Key.Key_Left: 0x14b, Qt.Key.Key_Right: 0x14d, Qt.Key.Key_End: 0x14f,
        Qt.Key.Key_Down: 0x150, Qt.Key.Key_PageDown: 0x151, Qt.Key.Key_Insert: 0x152,
        Qt.Key.Key_Delete: 0x153, Qt.Key.Key_CapsLock: 58}
KEYS.update({getattr(Qt.Key, f'Key_F{i}'): 58 + i for i in range(1, 11)})
KEYS.update({Qt.Key.Key_F11: 87, Qt.Key.Key_F12: 88})
LETTERS = dict(zip('QWERTYUIOPASDFGHJKLZXCVBNM', [*range(16, 26), *range(30, 39), *range(44, 51)]))


class RdpView(QWidget):
    resized = pyqtSignal()
    def __init__(self, worker, parent):
        super().__init__(parent)
        self.worker = worker
        self.session = parent
        self.image = QImage()
        self.pressed = {}
        self.mouse_buttons = set()
        self.mouse_position = (0, 0)
        self.wheel_remainder = [0, 0]
        self.remote_pointer = None
        self.fullscreen_key = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 100)
        worker.frame_ready.connect(self.receive_frame)
        worker.pointer_ready.connect(self.receive_pointer)

    def receive_frame(self):
        with self.worker.frame_lock:
            self.image = self.worker.latest_frame
            self.worker.latest_frame = None
        if self.image is None:
            self.image = QImage()
            return
        self.session.session_status.set_desktop_size(self.image.width(), self.image.height())
        self.update_pointer()
        self.update()

    def receive_pointer(self):
        with self.worker.pointer_lock:
            self.remote_pointer = self.worker.latest_pointer
            self.worker.latest_pointer = None
        self.update_pointer()

    def update_pointer(self):
        if self.remote_pointer is None:
            self.unsetCursor()
            return
        image, kind, x, y = self.remote_pointer
        if kind == -1:
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif kind == 0:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            scale = self.target().width() / max(1, self.image.width()) if not self.image.isNull() else 1
            width, height = max(1, round(image.width()*scale)), max(1, round(image.height()*scale))
            # Native cursor sizes are limited on some platforms.
            width, height = min(width, 512), min(height, 512)
            pixmap = QPixmap.fromImage(image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
            self.setCursor(QCursor(pixmap, min(width-1, round(x*width/image.width())),
                                   min(height-1, round(y*height/image.height()))))

    def target(self):
        if self.image.isNull():
            return self.rect()
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width()-size.width())//2, (self.height()-size.height())//2, size.width(), size.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.session.rdp_options['smooth_scaling'])
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self.image.isNull():
            painter.drawImage(self.target(), self.image)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_pointer()
        self.resized.emit()

    def send(self, name, *args):
        if self.worker.isRunning() and not self.worker.cancel.is_set():
            # Keep release events: a saturated queue terminates rather than leaving keys stuck.
            try:
                self.worker.commands.put_nowait((name, args))
            except Full:
                self.worker.stop()

    def mouse(self, event, flags):
        if self.image.isNull():
            return
        rect = self.target()
        if not rect.contains(event.position().toPoint()) and not self.mouse_buttons:
            return False
        x = max(0, min(self.image.width()-1, int((event.position().x()-rect.x()) * self.image.width()/max(1, rect.width()))))
        y = max(0, min(self.image.height()-1, int((event.position().y()-rect.y()) * self.image.height()/max(1, rect.height()))))
        self.mouse_position = (x, y)
        self.send('mouse', flags, x, y)
        return True

    def mouseMoveEvent(self, event):
        self.mouse(event, 0x0800)

    def mousePressEvent(self, event):
        self.setFocus()
        button = {Qt.MouseButton.LeftButton: 0x1000, Qt.MouseButton.RightButton: 0x2000, Qt.MouseButton.MiddleButton: 0x4000}.get(event.button())
        if button and self.mouse(event, button | 0x8000):
            self.mouse_buttons.add(button)

    def mouseReleaseEvent(self, event):
        button = {Qt.MouseButton.LeftButton: 0x1000, Qt.MouseButton.RightButton: 0x2000, Qt.MouseButton.MiddleButton: 0x4000}.get(event.button())
        if button in self.mouse_buttons:
            self.mouse(event, button)
            self.mouse_buttons.discard(button)

    def wheelEvent(self, event):
        for axis, delta in enumerate((event.angleDelta().x(), event.angleDelta().y())):
            self.wheel_remainder[axis] += delta
            while abs(self.wheel_remainder[axis]) >= 120:
                positive = self.wheel_remainder[axis] > 0
                self.mouse(event, (0x0400 if axis == 0 else 0x0200) | (120 if positive else (-120 & 0x1ff)))
                self.wheel_remainder[axis] -= 120 if positive else -120
        event.accept()

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        # Tab belongs to the remote desktop, rather than Qt focus traversal.
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(event) if event.type() == QEvent.Type.KeyPress else self.keyReleaseEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier) == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            if not event.isAutoRepeat():
                self.release_inputs()
                self.fullscreen_key = True
                self.session.set_fullscreen(not self.session.fullscreen)
            event.accept()
            return
        if key == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Re-offer on explicit paste: a remote logon can reset clipboard ownership.
            self.session.sync_local_clipboard()
        scan = KEYS.get(key)
        if scan is None and event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            scan = LETTERS.get(chr(key)) if 0 <= key < 128 else None
        if scan is not None:
            values = [(scan & 255, 0, 0x0100 if scan > 255 else 0)]
        else:
            raw = event.text().encode('utf-16-le')
            values = [(int.from_bytes(raw[i:i+2], 'little'), 1, 0) for i in range(0, len(raw), 2)]
        self.pressed[key] = values
        for code, unicode, flags in values:
            self.send('key', flags, code, unicode)
        event.accept()

    def keyReleaseEvent(self, event):
        if self.fullscreen_key and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.fullscreen_key = False
            event.accept()
            return
        if not event.isAutoRepeat():
            for code, unicode, flags in self.pressed.pop(event.key(), []):
                self.send('key', flags | 0x8000, code, unicode)
        event.accept()

    def release_inputs(self):
        for button in self.mouse_buttons:
            self.send("mouse", button, *self.mouse_position)
        self.mouse_buttons.clear()
        self.wheel_remainder = [0, 0]
        for values in self.pressed.values():
            for code, unicode, flags in values:
                self.send('key', flags | 0x8000, code, unicode)
        self.pressed.clear()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.session.sync_local_clipboard()
        self.worker.request_clipboard()

    def focusOutEvent(self, event):
        self.release_inputs()
        super().focusOutEvent(event)


class DetachedDesktop(QWidget):
    def __init__(self, session):
        super().__init__(session, Qt.WindowType.Window)
        self.session = session
        self.setWindowTitle(session.windowTitle())
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.exit_fullscreen = QPushButton(self.tr('Exit fullscreen'))
        self.exit_fullscreen.setIcon(action_icon(self, 'Maximize'))
        self.exit_fullscreen.setToolTip(self.tr('Return to the previous view (Ctrl+Alt+Enter).'))
        self.exit_fullscreen.clicked.connect(lambda: session.set_fullscreen(False))
        self.box.addWidget(self.exit_fullscreen)
        self.exit_fullscreen.hide()

    def closeEvent(self, event):
        self.session.stop()
        event.accept()


class RdpSession(QWidget):
    exited = pyqtSignal(int)

    def __init__(self, profile, parent=None):
        lib = load_bridge()
        super().__init__(parent)
        self.rdp_options = effective_options(profile.get('rdp_options', {}))
        self.clipboard_origin = uuid.uuid4().hex.encode()
        self.detached = False
        self.fullscreen = False
        self.fullscreen_return_workspace = False
        self.desktop_window = None
        self.setWindowTitle(profile.get('name', self.tr('RDP desktop')))
        self.embedded = True
        self.profile_id = profile.get('id')
        self.options = profile.get('terminal_options', {})
        self.session_status = SessionStatus('rdp', profile['host'], profile['port'], profile.get('username', ''), self)
        self.worker = RdpWorker(lib, profile, self)
        layout = QVBoxLayout(self)
        self.box = layout
        header = QHBoxLayout()
        self.result = QLabel(self.tr('Connecting to RDP…'))
        self.result.setWordWrap(True)
        header.addWidget(self.result, 1)
        self.display_button = QPushButton(self.tr('Detach desktop'))
        self.display_button.setIcon(action_icon(self, 'Detach'))
        self.display_button.setToolTip(self.tr('Move the live desktop between the workspace and a separate window without reconnecting.'))
        self.display_button.clicked.connect(self.toggle_display)
        header.addWidget(self.display_button)
        self.fullscreen_button = QPushButton(self.tr('Fullscreen'))
        self.fullscreen_button.setIcon(action_icon(self, 'Maximize'))
        self.fullscreen_button.setToolTip(self.tr('Toggle fullscreen without reconnecting (Ctrl+Alt+Enter).'))
        self.fullscreen_button.clicked.connect(lambda: self.set_fullscreen(not self.fullscreen))
        header.addWidget(self.fullscreen_button)
        self.show_button = QPushButton(self.tr('Show desktop'))
        self.show_button.setIcon(action_icon(self, 'Connect'))
        self.show_button.setToolTip(self.tr('Bring the detached desktop window to the front.'))
        self.show_button.clicked.connect(self.show_desktop)
        self.show_button.hide()
        header.addWidget(self.show_button)
        layout.addLayout(header)
        self.view = RdpView(self.worker, self)
        self.setFocusProxy(self.view)
        layout.addWidget(self.view, 1)
        self.worker.connected.connect(self.on_connected)
        self.worker.certificate.connect(self.verify_certificate)
        self.worker.ended.connect(self.on_ended)
        self.worker.display_control.connect(self.on_display_control)
        self.worker.clipboard_ready.connect(self.receive_clipboard)
        self.worker.clipboard_status.connect(self.on_clipboard_status)
        QApplication.clipboard().dataChanged.connect(self.sync_local_clipboard)
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(350)
        self.resize_timer.timeout.connect(self.request_resize)
        self.view.resized.connect(self.resize_timer.start)
        self.connection_commands = ConnectionCommands(self, profile, self.result.setText)
        QTimer.singleShot(0, self.start_with_commands)

    def start_with_commands(self):
        if not self.worker.cancel.is_set():
            self.connection_commands.start(self.start_connection)

    def start_connection(self):
        if self.worker.cancel.is_set():
            return
        if self.rdp_options['display'] == 'detached':
            self.detach_desktop()
        self.layout().activate()
        if self.detached:
            self.desktop_window.layout().activate()
        self.worker.initial_size = desktop_size(self.rdp_options, self.view.width(), self.view.height())
        self.worker.start()

    def on_clipboard_status(self, state):
        if self.rdp_options['clipboard']:
            self.result.setToolTip(self.tr('Text clipboard ready.') if state & 2 else
                                   self.tr('Text clipboard enabled; waiting for the server.'))

    def sync_local_clipboard(self):
        if not self.rdp_options['clipboard'] or not self.view.hasFocus() or self.worker.cancel.is_set():
            return
        mime = QApplication.clipboard().mimeData()
        if mime and mime.hasText() and bytes(mime.data(CLIP_ORIGIN)) != self.clipboard_origin:
            self.worker.offer_clipboard(mime.text())

    def receive_clipboard(self):
        with self.worker.clipboard_lock:
            value = self.worker.latest_clipboard
            self.worker.latest_clipboard = None
        if value is None or not self.view.hasFocus() or self.worker.cancel.is_set():
            return
        received, text = value
        if not received:
            self.worker.request_clipboard()
            return
        mime = QMimeData()
        mime.setText(text)
        mime.setData(CLIP_ORIGIN, self.clipboard_origin)
        QApplication.clipboard().setMimeData(mime)

    def set_fullscreen(self, enabled):
        if enabled == self.fullscreen:
            return
        if enabled:
            self.fullscreen_return_workspace = not self.detached
            self.detach_desktop()
            self.fullscreen_previous_state = self.desktop_window.windowState()
            self.fullscreen = True
            self.desktop_window.exit_fullscreen.show()
            self.desktop_window.showFullScreen()
        else:
            self.fullscreen = False
            self.desktop_window.exit_fullscreen.hide()
            self.desktop_window.setWindowState(self.fullscreen_previous_state)
            self.desktop_window.show()
            if self.fullscreen_return_workspace:
                self.attach_desktop()
        self.view.setFocus()

    def toggle_display(self):
        self.attach_desktop() if self.detached else self.detach_desktop()

    def detach_desktop(self):
        self.rdp_options['display'] = 'detached'
        if self.detached:
            self.show_desktop()
            return
        if self.desktop_window is None:
            self.desktop_window = DetachedDesktop(self)
            area = self.screen().availableGeometry()
            self.desktop_window.resize(min(1280, area.width()*4//5), min(900, area.height()*4//5))
        self.box.removeWidget(self.view)
        self.desktop_window.box.addWidget(self.view)
        self.detached = True
        self.display_button.setText(self.tr('Attach desktop'))
        self.show_button.show()
        self.show_desktop()

    def attach_desktop(self):
        if self.fullscreen:
            self.fullscreen_return_workspace = False
            self.set_fullscreen(False)
        self.rdp_options['display'] = 'workspace'
        if not self.detached:
            return
        self.desktop_window.box.removeWidget(self.view)
        self.box.addWidget(self.view, 1)
        self.desktop_window.hide()
        self.detached = False
        self.display_button.setText(self.tr('Detach desktop'))
        self.show_button.hide()
        self.view.show()
        self.view.setFocus()

    def show_desktop(self):
        if self.desktop_window is not None:
            if self.fullscreen:
                self.desktop_window.showFullScreen()
            elif self.desktop_window.isMinimized():
                self.desktop_window.showNormal()
            else:
                self.desktop_window.show()
            self.desktop_window.raise_()
            self.desktop_window.activateWindow()
            self.view.setFocus()

    def request_resize(self):
        if self.rdp_options['resolution'] == 'automatic':
            self.view.send('resize', *desktop_size(self.rdp_options, self.view.width(), self.view.height()))

    def on_display_control(self, supported):
        if self.rdp_options['resolution'] == 'automatic':
            self.result.setText(self.tr('RDP connected — automatic resolution.') if supported else
                                self.tr('RDP connected — server resolution scaled to fit.'))

    def on_connected(self):
        self.session_status.set_state('connected')
        self.request_resize()
        self.result.setText(self.tr('RDP connected — desktop scaled to fit.'))
        self.view.setFocus()
        self.sync_local_clipboard()

    def verify_certificate(self, host, subject, fingerprint, changed):
        if self.worker.cancel.is_set():
            return
        box = QMessageBox(self)
        box.setWindowTitle(self.tr('RDP certificate verification'))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(self.tr('The server certificate changed.') if changed else self.tr('The server certificate could not be verified.'))
        box.setInformativeText(self.tr('Host: %1\nSubject: %2\nCertificate: %3\nAccept only if you have verified this certificate independently.').replace('%1', host).replace('%2', subject).replace('%3', fingerprint))
        accept = box.addButton(self.tr('Accept for this session'), QMessageBox.ButtonRole.AcceptRole)
        accept.setIcon(action_icon(self, 'Connect'))
        reject = box.addButton(self.tr('Reject'), QMessageBox.ButtonRole.RejectRole)
        reject.setIcon(action_icon(self, 'Disconnect'))
        box.setDefaultButton(reject)
        self.cert_box = box
        box.exec()
        self.cert_box = None
        self.worker.accept_cert = box.clickedButton() == accept
        self.worker.cert_answer.set()

    def on_ended(self, code):
        self.view.remote_pointer = None
        self.view.update_pointer()
        self.session_status.finish(code, intentional=self.worker.cancel.is_set())
        self.result.setText(self.tr('RDP disconnected.') if not code else self.tr('RDP connection failed (FreeRDP error %1).').replace('%1', f'0x{code:08X}'))
        if code == 0x00020006 and not self.worker.cancel.is_set():
            self.result.setText(self.tr('Unable to reach the RDP server. Check the address, port and network/VPN.'))
        self.exited.emit(code)

    def apply_options(self, options):
        self.options = options

    def is_running(self):
        return self.connection_commands.starting or self.worker.isRunning()

    def stop(self):
        self.connection_commands.stop()
        self.resize_timer.stop()
        self.view.release_inputs()
        self.worker.stop()
        try:
            QApplication.clipboard().dataChanged.disconnect(self.sync_local_clipboard)
        except (TypeError, RuntimeError):
            pass
        if self.desktop_window is not None:
            self.desktop_window.hide()
        if getattr(self, 'cert_box', None):
            self.cert_box.reject()
        # Native connect is cancellable; join before the tab/vault can be destroyed.
        self.worker.wait()
        self.worker.credentials = None
        self.session_status.finish(intentional=True)
