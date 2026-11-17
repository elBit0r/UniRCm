"""Protocol-independent, secret-free session information for the UI."""
from time import monotonic
from PyQt6.QtCore import QObject, pyqtSignal


class SessionStatus(QObject):
    changed = pyqtSignal()
    activity = pyqtSignal(str)
    bell = pyqtSignal()

    def __init__(self, protocol, host, port, username='', parent=None):
        super().__init__(parent)
        self.protocol, self.host, self.port, self.username = protocol.upper(), host, port, username
        self.state = 'connecting'
        self.connected_at = None
        self.ended_at = None
        self.exit_code = None
        self.terminal_size = None
        self.desktop_size = None

    def set_state(self, state):
        if self.ended_at is not None or state == self.state:
            return
        self.state = state
        if state == 'connected' and self.connected_at is None:
            self.connected_at = monotonic()
        self.changed.emit()

    def set_terminal_size(self, columns, rows):
        if self.terminal_size != (columns, rows):
            self.terminal_size = (columns, rows)
            self.changed.emit()

    def set_desktop_size(self, width, height):
        if self.desktop_size != (width, height):
            self.desktop_size = (width, height)
            self.changed.emit()

    def finish(self, code=None, intentional=False):
        if self.ended_at is not None:
            return
        self.ended_at = monotonic()
        self.exit_code = code
        self.state = 'disconnected' if intentional or code in (None, 0) else 'error'
        self.changed.emit()

    def duration(self):
        if self.connected_at is None:
            return None
        elapsed = int((self.ended_at if self.ended_at is not None else monotonic()) - self.connected_at)
        hours, remainder = divmod(max(0, elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours:02}:{minutes:02}:{seconds:02}'
