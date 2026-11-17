"""Compact, protocol-independent status for the selected session tab."""
from PyQt6.QtCore import Qt, QEvent, QRectF, QSize, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QSizePolicy

from .icons import connection_icon


class ConnectionLed(QWidget):
    COLORS = {'connected': '#239b56', 'connecting': '#d69b13',
              'authenticating': '#d69b13', 'error': '#d64545',
              'rx': '#24a148', 'tx': '#da1e28'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.setFixedSize(16, 16)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.COLORS.get(self.state, '#888888'))
        # Carbon activity colors: brighter variants for dark backgrounds.
        if self.state in ('rx', 'tx') and self.palette().window().color().lightness() < 128:
            color = QColor({'rx': '#42be65', 'tx': '#fa4d56'}[self.state])
        painter.setPen(QPen(color.darker(135), 1))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(3, 3, 10, 10))


class SessionStatusLabel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ''
        self._session = None
        self._icon_key = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(7)
        self.led = ConnectionLed(self)
        self.state_label = self.label()
        layout.addWidget(self.led)
        layout.addWidget(self.state_label)
        self.protocol = self.section()
        layout.addWidget(self.protocol)
        self.destination = self.section()
        self.destination.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.destination.value.setMinimumWidth(80)
        layout.addWidget(self.destination, 1)
        self.elapsed = self.section(icon=True)
        self.dimensions = self.section(icon=True)
        self.exit_status = self.section()
        for section in (self.elapsed, self.dimensions, self.exit_status):
            layout.addWidget(section)
        self.activity_leds = {}
        self.activity_timers = {}
        self.activity_section = QWidget(self)
        activity_layout = QHBoxLayout(self.activity_section)
        activity_layout.setContentsMargins(0, 0, 0, 0)
        activity_layout.setSpacing(4)
        for direction, text, tooltip in (
                ('rx', 'RX', self.tr('Receiving terminal data')),
                ('tx', 'TX', self.tr('Sending terminal data'))):
            led = ConnectionLed(self.activity_section)
            led.activity_direction = direction
            label = self.label()
            label.setText(text)
            led.setToolTip(tooltip)
            label.setToolTip(tooltip)
            led.setAccessibleName(text)
            activity_layout.addWidget(led)
            activity_layout.addWidget(label)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(lambda led=led: self.set_activity_led(led, False))
            self.activity_leds[direction] = led
            self.activity_timers[direction] = timer
        layout.addWidget(self.activity_section)
        self.show_session(None)

    def label(self):
        label = QLabel(self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def section(self, icon=False):
        section = QWidget(self)
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        separator = self.label()
        separator.setText('|')
        separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row.addWidget(separator)
        if icon:
            section.icon = self.label()
            section.icon.setFixedSize(16, 16)
            row.addWidget(section.icon)
        section.value = self.label()
        row.addWidget(section.value)
        return section

    def _refresh_icons(self):
        ratio = self.devicePixelRatioF()
        desktop = self._session is not None and self._session.terminal_size is None
        key = (ratio, self.palette().cacheKey(), desktop)
        if key == self._icon_key:
            return
        self._icon_key = key
        pixmap = QPixmap(round(16 * ratio), round(16 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().windowText().color(), 1.5))
        painter.drawEllipse(QRectF(2, 2, 12, 12))
        painter.drawLine(8, 4, 8, 8)
        painter.drawLine(8, 8, 11, 10)
        painter.end()
        self.elapsed.icon.setPixmap(pixmap)
        icon = connection_icon('monitor' if desktop else 'terminal', self.palette())
        self.dimensions.icon.setPixmap(icon.pixmap(QSize(16, 16), ratio))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and hasattr(self, 'dimensions'):
            self._refresh_icons()

    def text(self):
        """Plain-text equivalent for accessibility and status inspection."""
        return self._text

    @staticmethod
    def set_activity_led(led, active):
        led.state = led.activity_direction if active else None
        led.update()

    def show_activity(self, direction):
        if direction in self.activity_leds:
            self.set_activity_led(self.activity_leds[direction], True)
            self.activity_timers[direction].start()

    def show_session(self, session):
        if session is not self._session:
            if self._session is not None:
                self._session.activity.disconnect(self.show_activity)
            for direction, led in self.activity_leds.items():
                self.activity_timers[direction].stop()
                self.set_activity_led(led, False)
            if session is not None:
                session.activity.connect(self.show_activity)
        self._session = session
        self.activity_section.setVisible(session is not None and session.protocol in ('SSH', 'TELNET'))
        states = {'embedded': self.tr('Desktop in workspace'), 'external': self.tr('External client running'), 'connecting': self.tr('Connecting'), 'authenticating': self.tr('Authenticating'),
                  'connected': self.tr('Connected'), 'disconnected': self.tr('Disconnected'),
                  'error': self.tr('Error')}
        state = states.get(session.state, self.tr('Unknown')) if session else self.tr('No active tab')
        self.state_label.setText(state)
        self.state_label.setToolTip(state)
        self.led.state = session.state if session else None
        self.led.setToolTip(state)
        self.led.setAccessibleName(state)
        self.led.update()
        for section in (self.protocol, self.destination, self.elapsed, self.dimensions, self.exit_status):
            section.setVisible(session is not None)
        parts = [state]
        if session is not None:
            self.protocol.value.setText(session.protocol)
            self.protocol.setToolTip(self.tr('Telnet — unencrypted TCP connection; authentication is handled by the remote device.') if session.protocol == 'TELNET' else self.tr('Connection protocol'))
            user = f'{session.username}@' if session.username else ''
            host = f'[{session.host}]' if ':' in session.host and not session.host.startswith('[') else session.host
            destination = f'{user}{host}:{session.port}'
            self.destination.value.setText(destination)
            self.destination.setToolTip(destination)
            parts.extend([session.protocol, destination])
            duration = session.duration()
            self.elapsed.setVisible(duration is not None)
            if duration is not None:
                self.elapsed.value.setText(duration)
                self.elapsed.setToolTip(self.tr('Duration since Telnet connection was established; login status is unknown.') if session.protocol == 'TELNET' else self.tr('Connection duration since successful authentication'))
                parts.append(duration)
            terminal = session.terminal_size
            size = terminal or session.desktop_size
            self.dimensions.setVisible(size is not None)
            if size is not None:
                width, height = size
                self.dimensions.value.setText(f'{width} × {height}')
                tooltip = (self.tr('Terminal: %1 columns × %2 rows') if terminal else
                           self.tr('Desktop: %1 × %2 pixels')).replace('%1', str(width)).replace('%2', str(height))
                self.dimensions.setToolTip(tooltip)
                parts.append(f'{width} × {height}')
            self.exit_status.setVisible(session.exit_code is not None)
            if session.exit_code is not None:
                code = self.tr('Exit code: %1').replace('%1', str(session.exit_code))
                self.exit_status.value.setText(code)
                self.exit_status.setToolTip(self.tr('Local connection result: 0 means closed, 1 means transport error. Telnet does not provide remote command exit codes.') if session.protocol == 'TELNET' else self.tr('Session process exit code'))
                parts.append(code)
        self._text = ' | '.join(parts)
        self.setAccessibleName(self._text)
        self._refresh_icons()
