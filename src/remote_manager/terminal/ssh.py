"""Embedded VT terminal for OpenSSH, local shells and Telnet, rendered by Qt."""
import errno
import fcntl
import os
import re
import signal
import struct
import subprocess
import termios
import tempfile

import pyte
from PyQt6.QtCore import Qt, QProcess, QSocketNotifier, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from remote_manager.session import SessionStatus
from remote_manager.ssh_options import advanced_arguments
from .askpass import AskpassBridge
from .private_key import open_memory_key
from .public_key import install_arguments
from .screen import TerminalScreen
from .appearance import DEFAULT_OPTIONS, default_font
from remote_manager.storage.vault import validate_connect_timeout
from remote_manager.ui.icons import action_icon


def ssh_command(profile):
    host = profile['host'].strip()
    user = profile['username'].strip()
    if not re.fullmatch(r'[A-Za-z0-9_.:\[\]-]+', host) or host.startswith('-'):
        raise ValueError('Enter a hostname, SSH alias or IP address without spaces.')
    if user and (user.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@-]+', user)):
        raise ValueError('Invalid username.')
    timeout = profile.get('connect_timeout', 15)
    validate_connect_timeout(timeout)
    args = ['ssh', '-tt', '-o', 'LogLevel=DEBUG1', '-o', 'ForwardAgent=no', '-o', 'StrictHostKeyChecking=ask',
            '-o', f'ConnectTimeout={timeout}', '-p', str(profile['port'])]
    args += advanced_arguments({'alive_interval': 30, **profile.get('ssh_advanced', {})})
    if profile.get('key_passphrase') and profile.get('identity_file'):
        # Remote keyboard-interactive challenges can imitate local key prompts.
        args += ['-o', 'KbdInteractiveAuthentication=no']
    if user:
        args += ['-l', user]
    if profile['identity_file']:
        args += ['-i', os.path.expanduser(profile['identity_file'])]
    return args + ['--', host]


class Terminal(QWidget):
    exited = pyqtSignal(int)
    appearance_requested = pyqtSignal()
    public_key_install_finished = pyqtSignal(str)

    def __init__(self, profile, parent=None, *, private_key=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setFont(default_font())
        protocol = profile.get('protocol', 'ssh')
        local = protocol == 'local'
        self.session_status = SessionStatus(protocol, profile.get('host', ''), profile.get('port'), profile.get('username', ''), self)
        self._diagnostic_buffer = bytearray()
        self._diagnostic_shown = 0
        self.profile_id = profile.get('id')
        self.options = profile.get('terminal_options', {})
        font = self.font()
        font.setFamily(self.options.get('font_family', font.family()))
        font.setPointSize(self.options.get('font_size', max(6, font.pointSize())))
        self.setFont(font)
        self.cursor_visible = True
        self.cursor_timer = QTimer(self)
        self.cursor_timer.setInterval(500)
        self.cursor_timer.timeout.connect(self.blink_cursor)
        if self.options.get('cursor_blink', DEFAULT_OPTIONS['cursor_blink']):
            self.cursor_timer.start()
        self.screen = TerminalScreen(80, 24, lambda data: self.send(data.encode()),
                                     bell=self.session_status.bell.emit)
        self.stream = pyte.ByteStream(self.screen)
        self.fd = None
        self.process = None
        self.pending = bytearray()
        # Bound parsing work and yield to keyboard events during continuous output.
        self.read_resume = QTimer(self)
        self.read_resume.setSingleShot(True)
        self.read_resume.setInterval(5)
        self.read_resume.timeout.connect(self.resume_output)
        self.output_frame = QTimer(self)
        self.output_frame.setSingleShot(True)
        self.output_frame.setInterval(33)
        self.output_frame.timeout.connect(self.update)
        self.selection_anchor = None
        self.selection_end = None
        self.selecting = False
        self.selection_pointer = None
        self.word_selection = None
        self.selection_timer = QTimer(self)
        self.selection_timer.setInterval(60)
        self.selection_timer.timeout.connect(self.scroll_selection)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.check_exit)
        self.transfer_dialogs = []
        self.control_directory = None
        self.control_path = None
        self.key_fd = None
        self.key_install_process = None
        self.sftp_host = profile.get('host', '').strip()
        self.setAcceptDrops(protocol == 'ssh')
        self.transport = None
        self.diagnostics = None
        if protocol == 'telnet':
            from .telnet import TelnetTransport
            self.askpass = None
            self.transport = TelnetTransport(profile)
            self.transport.output.connect(self.telnet_output)
            self.transport.activity.connect(self.session_status.activity.emit)
            self.transport.connected.connect(lambda: self.session_status.set_state('connected'))
            self.transport.failed.connect(self.telnet_error)
            self.transport.ended.connect(self.telnet_ended)
            self.resize_terminal()
            self.transport.start()
            return
        self.askpass = None
        master = slave = None
        try:
            master, slave = os.openpty()
            env = os.environ.copy()
            env['TERM'] = 'xterm-256color'
            if local:
                shell = env.get('SHELL', '')
                if not os.path.isabs(shell) or not os.path.isfile(shell) or not os.access(shell, os.X_OK):
                    shell = '/bin/sh'
                args = [shell, '-i']
            else:
                args = self.ssh_arguments(profile, private_key)
                env['LC_ALL'] = 'C'
                if self.askpass is not None:
                    env.update(self.askpass.environment())
            self.process = subprocess.Popen(
                args, stdin=slave, stdout=slave, stderr=slave if local else subprocess.PIPE,
                cwd=os.path.expanduser(profile.get('directory') or '~') if local else None,
                start_new_session=True,
                preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0), env=env)
        except Exception:
            self.release_private_key()
            if self.control_directory is not None:
                self.control_directory.cleanup()
            if self.askpass is not None:
                self.askpass.close()
            if master is not None:
                os.close(master)
            raise
        finally:
            if slave is not None:
                os.close(slave)
        self.fd = master
        os.set_blocking(master, False)
        self.reader = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self.reader.activated.connect(self.read_output)
        self.writer = QSocketNotifier(master, QSocketNotifier.Type.Write, self)
        self.writer.setEnabled(False)
        self.writer.activated.connect(self.flush_input)
        if self.process.stderr is not None:
            os.set_blocking(self.process.stderr.fileno(), False)
            self.diagnostics = QSocketNotifier(self.process.stderr.fileno(), QSocketNotifier.Type.Read, self)
            self.diagnostics.activated.connect(self.read_diagnostics)
        if local:
            self.session_status.set_state('connected')
        self.poll.start(100)
        self.resize_terminal()
        if local and profile.get('commands'):
            commands = profile['commands'].replace('\r\n', '\n').replace('\r', '\n')
            self.send((commands.rstrip('\n') + '\n').encode())

    def ssh_arguments(self, profile, private_key):
        if private_key is not None:
            self.key_fd, path = open_memory_key(private_key)
            profile = dict(profile, identity_file=path)
        if profile.get('password') or profile.get('key_passphrase'):
            self.askpass = AskpassBridge(profile.get('password', ''), self,
                                         profile.get('key_passphrase', ''), profile.get('identity_file', ''))
        self.control_directory = tempfile.TemporaryDirectory(prefix='unircm-ssh-')
        self.control_path = os.path.join(self.control_directory.name, 'socket')
        args = ssh_command(profile)
        args[1:1] = ['-o', 'ControlMaster=yes', '-o', 'ControlPersist=no',
                     '-o', f'ControlPath={self.control_path}']
        return args

    def is_running(self):
        return self.session_status.ended_at is None if self.transport is not None else self.process.poll() is None

    def telnet_output(self, data):
        if self.session_status.ended_at is None:
            self.clear_selection()
            self.stream.feed(data)
            self.update()
        self.transport.acknowledge()

    def telnet_error(self, message):
        if self.session_status.ended_at is None:
            self.stream.feed(('\r\n' + self.tr(message) + '\r\n').encode())
            self.update()

    def telnet_ended(self, code):
        if self.session_status.ended_at is None:
            self.session_status.finish(code)
            self.exited.emit(code)

    def read_diagnostics(self, *_):
        if self.process.stderr is None or self.process.stderr.closed:
            return
        try:
            data = os.read(self.process.stderr.fileno(), 65536)
        except BlockingIOError:
            return
        if not data:
            self.diagnostics.setEnabled(False)
            return
        self._diagnostic_buffer.extend(data)
        while b'\n' in self._diagnostic_buffer:
            line, _, rest = self._diagnostic_buffer.partition(b'\n')
            self._diagnostic_buffer = bytearray(rest)
            if line.startswith(b'Authenticated to ') or line.startswith(b'debug1: Authentication succeeded ('):
                self.release_private_key()
                self.session_status.set_state('connected')
                if self.askpass is not None:
                    self.askpass.clear_password()
            elif line.startswith(b'debug1: Next authentication method:'):
                self.session_status.set_state('authenticating')
            elif not line.startswith((b'debug1:', b'debug2:', b'debug3:')):
                self.stream.feed(line[self._diagnostic_shown:].rstrip(b'\r') + b'\r\n')
                self.update()
            self._diagnostic_shown = 0
        # Preserve partial lines for state detection while displaying prompts.
        prefix = bytes(self._diagnostic_buffer)
        if prefix and not (prefix.startswith(b'debug') or b'debug'.startswith(prefix)):
            self.stream.feed(prefix[self._diagnostic_shown:])
            self._diagnostic_shown = len(prefix)
            self.update()
        if len(self._diagnostic_buffer) > 65536:
            self._diagnostic_buffer.clear()
            self._diagnostic_shown = 0

    def blink_cursor(self):
        self.cursor_visible = not self.cursor_visible
        self.update()

    def apply_options(self, options):
        self.options = dict(options)
        font = default_font()
        font.setFamily(options.get('font_family', font.family()))
        font.setPointSize(options.get('font_size', max(6, font.pointSize())))
        self.setFont(font)
        self.cursor_visible = True
        self.cursor_timer.stop()
        if options.get('cursor_blink', DEFAULT_OPTIONS['cursor_blink']):
            self.cursor_timer.start()
        self.resize_terminal()

    def resume_output(self):
        if self.fd is not None:
            self.reader.setEnabled(True)

    def read_output(self, *_):
        if self.fd is None:
            return
        try:
            data = os.read(self.fd, 4096)
            if data:
                self.session_status.activity.emit('rx')
                self.clear_selection()
                self.stream.feed(data)
                if not self.output_frame.isActive():
                    self.output_frame.start()
                self.reader.setEnabled(False)
                self.read_resume.start()
            else:
                self.reader.setEnabled(False)
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                self.reader.setEnabled(False)

    def send(self, data):
        if self.transport is not None:
            if self.is_running():
                self.transport.send(data)
            return
        if self.fd is not None and self.process.poll() is None:
            self.pending.extend(data)
            self.flush_input()

    def flush_input(self, *_):
        if self.fd is None:
            return
        try:
            if self.pending:
                count = os.write(self.fd, self.pending)
                if count:
                    self.session_status.activity.emit('tx')
                del self.pending[:count]
            self.writer.setEnabled(bool(self.pending))
        except BlockingIOError:
            self.writer.setEnabled(True)
        except OSError:
            self.pending.clear()
            self.writer.setEnabled(False)

    def check_exit(self):
        code = self.process.poll()
        if code is not None:
            self.read_diagnostics()
            for dialog in self.transfer_dialogs:
                dialog.shutdown()
            self.session_status.finish(code)
            self.read_output()
            self.release_fd()
            if self.control_directory is not None:
                self.control_directory.cleanup()
            self.poll.stop()
            self.exited.emit(code)

    def release_fd(self):
        self.release_private_key()
        if self.key_install_process is not None:
            self.key_install_process.kill()
        self.read_resume.stop()
        self.output_frame.stop()
        if self.diagnostics is not None:
            self.diagnostics.setEnabled(False)
            self.process.stderr.close()
        self._diagnostic_buffer.clear()
        if self.askpass is not None:
            self.askpass.close()
        if self.fd is not None:
            self.reader.setEnabled(False)
            self.writer.setEnabled(False)
            os.close(self.fd)
            self.fd = None
        self.pending.clear()

    def release_private_key(self):
        if self.key_fd is not None:
            os.close(self.key_fd)
            self.key_fd = None

    def file_transfer_available(self):
        return (self.transport is None and self.process is not None
                and self.process.poll() is None and self.control_path is not None
                and os.path.exists(self.control_path))

    def can_install_public_key(self):
        return (self.session_status.state == 'connected' and self.file_transfer_available()
                and self.key_install_process is None)

    def install_public_key(self, public_key):
        if not self.can_install_public_key():
            return False
        process = QProcess(self)
        self.key_install_process = process
        process.setStandardErrorFile(QProcess.nullDevice())
        timeout = QTimer(process)
        timeout.setSingleShot(True)
        timeout.timeout.connect(process.kill)

        def send_key():
            process.write(public_key)
            process.closeWriteChannel()

        def finish(exit_code):
            timeout.stop()
            output = bytes(process.readAllStandardOutput()).splitlines()
            status = 'failed'
            if exit_code == 0 and output:
                status = {b'UNIRCM_KEY_INSTALLED': 'installed',
                          b'UNIRCM_KEY_ALREADY_PRESENT': 'exists'}.get(output[-1], 'failed')
            self.key_install_process = None
            process.deleteLater()
            self.public_key_install_finished.emit(status)

        process.started.connect(send_key)
        process.finished.connect(finish)
        process.errorOccurred.connect(lambda error: finish(-1) if error == QProcess.ProcessError.FailedToStart else None)
        timeout.start(10000)
        process.start('ssh', install_arguments(self.control_path, self.sftp_host))
        return True

    def open_file_transfer(self, upload=False, files=None):
        if not self.file_transfer_available():
            return
        from remote_manager.ui.file_transfer import FileTransferDialog
        if upload and files is None:
            from PyQt6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(self, self.tr('Upload file'))
            if not files:
                return
        dialog = next(iter(self.transfer_dialogs), None)
        if dialog is None:
            dialog = FileTransferDialog(self, files)
            self.transfer_dialogs.append(dialog)
        elif files:
            if dialog.job is None:
                dialog.upload(files)
            else:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, self.tr('SSH file transfer'),
                                        self.tr('Wait for the current operation before uploading more files.'))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if self.file_transfer_available() and urls and all(url.isLocalFile() and os.path.isfile(url.toLocalFile()) for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if self.file_transfer_available() and urls and all(url.isLocalFile() and os.path.isfile(url.toLocalFile()) for url in urls):
            event.acceptProposedAction()
            self.open_file_transfer(files=[url.toLocalFile() for url in urls])

    def stop(self):
        self.clear_selection()
        for dialog in self.transfer_dialogs:
            dialog.shutdown()
        if self.transport is not None:
            self.session_status.finish(intentional=True)
            self.transport.stop()
            return
        self.session_status.finish(self.process.poll(), intentional=self.process.poll() is None)
        if self.process is not None and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait()
        self.poll.stop()
        self.release_fd()
        if self.control_directory is not None:
            self.control_directory.cleanup()

    def resize_terminal(self):
        metrics = QFontMetrics(self.font())
        self.cell_w = max(1, metrics.horizontalAdvance('M'))
        self.cell_h = metrics.height()
        cols = max(2, self.width() // self.cell_w)
        rows = max(2, self.height() // self.cell_h)
        if getattr(self, '_terminal_size', None) == (rows, cols):
            self.update()
            return
        self._terminal_size = (rows, cols)
        self.clear_selection()
        self.screen.resize(rows, cols)
        self.session_status.set_terminal_size(cols, rows)
        if self.transport is not None:
            self.transport.resize(cols, rows)
        if self.fd is not None:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        self.update()

    def resizeEvent(self, event):
        self.resize_terminal()
        super().resizeEvent(event)

    @staticmethod
    def color(value, default):
        names = dict(zip(
            ('black', 'red', 'green', 'brown', 'blue', 'magenta', 'cyan', 'white',
             'brightblack', 'brightred', 'brightgreen', 'brightbrown', 'brightblue', 'brightmagenta', 'brightcyan', 'brightwhite'),
            ('#161616', '#cd0000', '#00cd00', '#cdcd00', '#5c5cff', '#cd00cd', '#00cdcd', '#dddddd',
             '#777777', '#ff5555', '#55ff55', '#ffff55', '#7777ff', '#ff55ff', '#55ffff', '#ffffff')))
        if value == 'default':
            return QColor(default)
        return QColor(names.get(value, '#' + value if len(value) == 6 else value))

    def paintEvent(self, event):
        painter = QPainter(self)
        background = self.options.get('background', DEFAULT_OPTIONS['background'])
        foreground = self.options.get('foreground', DEFAULT_OPTIONS['foreground'])
        painter.fillRect(self.rect(), QColor(background))
        baseline = QFontMetrics(self.font()).ascent()
        colors = {}
        fonts = {}

        def color(value, default):
            key = (value, default)
            if key not in colors:
                colors[key] = self.color(value, default)
            return colors[key]

        for y in range(self.screen.lines):
            line = self.screen.buffer.get(y, {})
            for x, char in line.items():
                fg = color(char.fg, foreground)
                bg = color(char.bg, background)
                if char.reverse:
                    fg, bg = bg, fg
                painter.fillRect(x*self.cell_w, y*self.cell_h, self.cell_w, self.cell_h, bg)
            span = self.selection_span(y)
            if span:
                painter.fillRect(span[0]*self.cell_w, y*self.cell_h,
                                 (span[1]-span[0])*self.cell_w, self.cell_h,
                                 self.palette().highlight())
            for x, char in line.items():
                fg = color(char.bg if char.reverse else char.fg, background if char.reverse else foreground)
                style = (char.bold, char.italics, char.underscore)
                if style not in fonts:
                    font = QFont(self.font())
                    font.setBold(char.bold)
                    font.setItalic(char.italics)
                    font.setUnderline(char.underscore)
                    fonts[style] = font
                font = fonts[style]
                painter.setFont(font)
                painter.setPen(self.palette().highlightedText().color() if span and span[0] <= x < span[1] else fg)
                painter.drawText(x*self.cell_w, y*self.cell_h + baseline, char.data)
        if self.hasFocus() and self.cursor_visible and not self.screen.cursor.hidden and self.screen.cursor.x < self.screen.columns:
            color = QColor(self.options.get('cursor_color', DEFAULT_OPTIONS['cursor_color']))
            painter.setPen(color)
            x, y = self.screen.cursor.x*self.cell_w, self.screen.cursor.y*self.cell_h
            shape = self.options.get('cursor_shape', DEFAULT_OPTIONS['cursor_shape'])
            if shape == 'bar':
                painter.fillRect(x, y, 2, self.cell_h, color)
            elif shape == 'underline':
                painter.fillRect(x, y+self.cell_h-2, self.cell_w, 2, color)
            elif shape == 'block':
                painter.fillRect(x, y, self.cell_w, self.cell_h, color)
                painter.setFont(self.font())
                painter.setPen(QColor(background))
                painter.drawText(x, y+baseline, self.screen.buffer[self.screen.cursor.y][self.screen.cursor.x].data)
            else:
                painter.drawRect(x, y, self.cell_w-1, self.cell_h-1)

    def focusNextPrevChild(self, next):
        return False  # Tab belongs to the remote shell.

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            event.accept()
            return
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy_selection()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste()
            return
        if mods == Qt.KeyboardModifier.ShiftModifier and key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self.clear_selection()
            (self.screen.prev_page if key == Qt.Key.Key_PageUp else self.screen.next_page)()
            self.update()
            return
        self.clear_selection()
        # Return from scrollback before sending input.
        while self.screen.history.bottom:
            self.screen.next_page()
        keys = {Qt.Key.Key_Return: b'\r', Qt.Key.Key_Enter: b'\r', Qt.Key.Key_Backspace: b'\x7f',
                Qt.Key.Key_Tab: b'\t', Qt.Key.Key_Backtab: b'\x1b[Z', Qt.Key.Key_Escape: b'\x1b',
                Qt.Key.Key_Insert: b'\x1b[2~', Qt.Key.Key_Delete: b'\x1b[3~',
                Qt.Key.Key_PageUp: b'\x1b[5~', Qt.Key.Key_PageDown: b'\x1b[6~',
                Qt.Key.Key_F1: b'\x1bOP', Qt.Key.Key_F2: b'\x1bOQ',
                Qt.Key.Key_F3: b'\x1bOR', Qt.Key.Key_F4: b'\x1bOS',
                **{Qt.Key.Key_F5 + i: f'\x1b[{n}~'.encode() for i, n in enumerate((15,17,18,19,20,21,23,24))}}
        arrows = {Qt.Key.Key_Up: 'A', Qt.Key.Key_Down: 'B', Qt.Key.Key_Right: 'C',
                  Qt.Key.Key_Left: 'D', Qt.Key.Key_Home: 'H', Qt.Key.Key_End: 'F'}
        modifier = 1 + int(shift) + 2 * int(bool(mods & Qt.KeyboardModifier.AltModifier)) + 4 * int(ctrl)
        modified_key = key in keys and modifier > 1 and (Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12 or key in (Qt.Key.Key_Insert, Qt.Key.Key_Delete, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown))
        if key in arrows and modifier > 1:
            data = f'\x1b[1;{modifier}{arrows[key]}'.encode()
        elif key in arrows:
            data = ('\x1b' + ('O' if (1 << 5) in self.screen.mode else '[') + arrows[key]).encode()
        elif modified_key:
            base = keys[key].decode()
            data = (f'\x1b[1;{modifier}{base[-1]}' if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F4
                    else f'{base[:-1]};{modifier}~').encode()
        elif ctrl and key in (Qt.Key.Key_Space, Qt.Key.Key_At):
            data = b'\x00'
        elif ctrl and key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_Backslash, Qt.Key.Key_BracketRight, Qt.Key.Key_AsciiCircum, Qt.Key.Key_Underscore):
            data = bytes([key & 0x1f])
        elif ctrl and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            data = bytes([key - Qt.Key.Key_A + 1])
        else:
            data = keys.get(key, event.text().encode())
        if mods & Qt.KeyboardModifier.AltModifier and key not in arrows and not modified_key:
            data = b'\x1b' + data
        self.send(data)
        event.accept()

    def paste(self):
        self.clear_selection()
        text = QApplication.clipboard().text().replace('\r\n', '\n').replace('\r', '\n')
        data = text.encode()
        if 2004 << 5 in self.screen.mode:
            data = b'\x1b[200~' + data + b'\x1b[201~'
        self.send(data)

    def contextMenuEvent(self, event):
        if self.mouse_reporting() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            event.accept()
            return
        menu = QMenu(self)
        copy = menu.addAction(action_icon(self, 'Copy'), self.tr('Copy selection'), self.copy_selection)
        copy.setEnabled(bool(self.selected_text()))
        menu.addAction(action_icon(self, 'Copy'), self.tr('Copy screen'), lambda: QApplication.clipboard().setText('\n'.join(self.screen.display)))
        menu.addAction(action_icon(self, 'Paste'), self.tr('Paste'), self.paste)
        menu.addSeparator()
        if self.session_status.protocol == 'SSH':
            for title, icon, upload in [('Upload file', 'Upload file', True),
                                        ('File manager', 'Open directory', False)]:
                action = menu.addAction(action_icon(self, icon), self.tr(title),
                                        lambda checked=False, upload=upload: self.open_file_transfer(upload))
                action.setEnabled(self.file_transfer_available())
                action.setToolTip(self.tr(title if upload else 'Browse and download remote files'))
        menu.addAction(self.tr('Terminal appearance…'), self.appearance_requested.emit)
        for action in menu.actions():
            action.setIconVisibleInMenu(True)
        menu.exec(event.globalPos())

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            size = max(6, min(72, self.font().pointSize() + (1 if delta > 0 else -1) * max(1, abs(delta) // 120)))
            self.apply_options(dict(self.options, font_size=size))
            event.accept()
            return
        if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.mouse_reporting():
                for _ in range(max(1, abs(delta) // 120)):
                    self.report_mouse(event, 64 if delta > 0 else 65)
                event.accept()
                return
            if self.screen.is_alternate:
                prefix = b'\x1bO' if 1 << 5 in self.screen.mode else b'\x1b['
                self.send((prefix + (b'A' if delta > 0 else b'B')) * 3)
                event.accept()
                return
        self.clear_selection()
        (self.screen.prev_page if delta > 0 else self.screen.next_page)()
        self.update()

    def mouse_reporting(self):
        return any(mode << 5 in self.screen.mode for mode in (1000, 1002, 1003))

    def report_mouse(self, event, button, release=False, motion=False):
        x = min(self.screen.columns, max(1, int(event.position().x()) // self.cell_w + 1))
        y = min(self.screen.lines, max(1, int(event.position().y()) // self.cell_h + 1))
        mods = event.modifiers()
        code = button + (32 if motion else 0)
        code += 4 * bool(mods & Qt.KeyboardModifier.ShiftModifier)
        code += 8 * bool(mods & Qt.KeyboardModifier.AltModifier)
        code += 16 * bool(mods & Qt.KeyboardModifier.ControlModifier)
        if 1006 << 5 in self.screen.mode:
            self.send(f'\x1b[<{code};{x};{y}{"m" if release else "M"}'.encode())
        elif x <= 223 and y <= 223:
            self.send(b'\x1b[M' + bytes([32 + (code - button + 3 if release else code), x + 32, y + 32]))

    def mousePressEvent(self, event):
        self.setFocus()
        button = {Qt.MouseButton.LeftButton: 0, Qt.MouseButton.MiddleButton: 1,
                  Qt.MouseButton.RightButton: 2}.get(event.button())
        if self.mouse_reporting() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier and button is not None:
            self.clear_selection()
            self.report_mouse(event, button)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.clear_selection()
            self.selection_anchor = self.selection_point(event)
            self.selection_end = self.selection_anchor
            self.selecting = True
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.selecting and event.button() == Qt.MouseButton.LeftButton:
            self.update_selection(event)
            self.selecting = False
            self.selection_timer.stop()
            self.update()
            event.accept()
            return
        button = {Qt.MouseButton.LeftButton: 0, Qt.MouseButton.MiddleButton: 1,
                  Qt.MouseButton.RightButton: 2}.get(event.button())
        if self.mouse_reporting() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier and button is not None:
            self.report_mouse(event, button, release=True)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self.selecting:
            self.update_selection(event)
            self.selection_pointer = event.position()
            if event.position().y() < 0 or event.position().y() >= self.screen.lines * self.cell_h:
                self.selection_timer.start()
            else:
                self.selection_timer.stop()
            self.update()
            event.accept()
            return
        dragging = bool(event.buttons())
        if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier and (
                1003 << 5 in self.screen.mode or (1002 << 5 in self.screen.mode and dragging)):
            button = next((code for flag, code in ((Qt.MouseButton.LeftButton, 0),
                          (Qt.MouseButton.MiddleButton, 1), (Qt.MouseButton.RightButton, 2))
                          if event.buttons() & flag), 3)
            self.report_mouse(event, button, motion=True)
        else:
            super().mouseMoveEvent(event)


    def selection_offset(self):
        return 0 if self.screen.is_alternate else len(self.screen.history.top)

    def selection_line(self, row):
        offset = self.selection_offset()
        if row < offset:
            return self.screen.history.top[row]
        if row < offset + self.screen.lines:
            return self.screen.buffer.get(row - offset, {})
        return self.screen.history.bottom[row - offset - self.screen.lines]

    def word_bounds(self, point):
        row, column = point
        column = min(column, self.screen.columns - 1)
        line = self.selection_line(row)

        def category(index):
            text = line[index].data if index in line else ' '
            if not text and index:
                return category(index - 1)
            return 0 if text.isspace() else 1 if any(c.isalnum() or c == '_' for c in text) else 2

        kind = category(column)
        left, right = column, column + 1
        while left and category(left - 1) == kind:
            left -= 1
        while right < self.screen.columns and category(right) == kind:
            right += 1
        return (row, left), (row, right)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or (self.mouse_reporting() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.mousePressEvent(event)
            return
        self.clear_selection()
        # Use the cell under the pointer rather than the nearest selection edge.
        point = (self.selection_offset() + min(self.screen.lines - 1, max(0, int(event.position().y()) // self.cell_h)),
                 min(self.screen.columns - 1, max(0, int(event.position().x()) // self.cell_w)))
        self.word_selection = self.word_bounds(point)
        self.selection_anchor, self.selection_end = self.word_selection
        self.selecting = True
        self.update()
        event.accept()

    def extend_selection(self, point):
        if self.word_selection:
            left, right = self.word_bounds(point)
            start, end = self.word_selection
            self.selection_anchor, self.selection_end = (end, left) if left < start else (start, right)
        else:
            self.selection_end = point

    def update_selection(self, event):
        self.extend_selection(self.selection_point(event))

    def scroll_selection(self):
        if not self.selecting or self.selection_pointer is None or self.screen.is_alternate:
            self.selection_timer.stop()
            return
        y = self.selection_pointer.y()
        if 0 <= y < self.screen.lines * self.cell_h:
            self.selection_timer.stop()
            return
        normal = self.screen.normal
        ratio = normal.history.ratio
        normal.history = normal.history._replace(ratio=1 / normal.lines)
        try:
            (self.screen.prev_page if y < 0 else self.screen.next_page)()
        finally:
            normal.history = normal.history._replace(ratio=ratio)
        row = 0 if y < 0 else self.screen.lines - 1
        column = max(0, min(self.screen.columns, round(self.selection_pointer.x() / self.cell_w)))
        self.extend_selection((row + self.selection_offset(), column))
        self.update()

    def clear_selection(self):
        self.selection_timer.stop()
        self.word_selection = None
        self.selection_pointer = None
        self.selection_anchor = self.selection_end = None
        self.selecting = False
        self.update()

    def selection_point(self, event):
        row = min(self.screen.lines - 1, max(0, int(event.position().y()) // self.cell_h))
        edge = 0 if self.word_selection else self.cell_w / 2
        column = min(self.screen.columns, max(0, int((event.position().x() + edge) // self.cell_w)))
        # Do not split a double-width glyph at its empty continuation cell.
        char = self.screen.buffer.get(row, {}).get(column)
        if column and char is not None and char.data == '':
            column -= 1
        return row + self.selection_offset(), column

    def selection_span(self, row):
        return self.absolute_selection_span(row + self.selection_offset())

    def absolute_selection_span(self, row):
        if self.selection_anchor is None or self.selection_end is None:
            return None
        start, end = sorted((self.selection_anchor, self.selection_end))
        if not start[0] <= row <= end[0]:
            return None
        left = start[1] if row == start[0] else 0
        right = end[1] if row == end[0] else self.screen.columns
        return (left, right) if right > left else None

    def selected_text(self):
        if self.selection_anchor is None or self.selection_end is None:
            return ''
        start, end = sorted((self.selection_anchor, self.selection_end))
        if start == end:
            return ''
        lines = []
        for row in range(start[0], end[0] + 1):
            span = self.absolute_selection_span(row)
            line = self.selection_line(row)
            text = ''.join(line[col].data if col in line else ' '
                           for col in range(*span)) if span else ''
            lines.append(text.rstrip(' '))
        return '\n'.join(lines)

    def copy_selection(self):
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)
