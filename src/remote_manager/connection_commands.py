"""Run profile commands on the client at connection lifecycle boundaries."""
import os
import signal
import subprocess
from threading import Thread

from PyQt6.QtCore import QCoreApplication, QObject, QProcess, QTimer, Qt, pyqtSignal
from PyQt6.sip import isdeleted
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from remote_manager.ui.icons import action_icon


class ConnectionCommands(QObject):
    def __init__(self, session, profile, report_error, *, watch_status=True):
        super().__init__(session)
        self.session = session
        self.report_error = report_error
        self.before = profile.get('before_connect_command', '').strip()
        self.after = profile.get('after_disconnect_command', '').strip()
        self.process = None
        self.prompt = None
        self.start_transport = None
        self.start_timer = QTimer(self)
        self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.run_before)
        if self.after and watch_status:
            session.session_status.changed.connect(self.status_changed)

    @property
    def starting(self):
        return self.start_transport is not None

    def start(self, start_transport):
        if self.before:
            self.start_transport = start_transport
            self.start_timer.start(0)
        else:
            start_transport()

    def run_before(self):
        self.run(self.before, self.before_finished)

    def status_changed(self):
        status = self.session.session_status
        if status.ended_at is not None and status.connected_at is not None:
            self.disconnected()

    def disconnected(self, finished_signal=None):
        if self.after:
            command, self.after = self.after, ''
            job = DisconnectCommand(self.session, self.report_error)
            if finished_signal is None:
                job.start(command)
            else:
                job.run_when_finished(finished_signal, command)
            return job

    def close_when_finished(self, finished_signal):
        if self.session.session_status.connected_at is not None:
            return self.disconnected(finished_signal)

    def run(self, command, callback):
        process = self.process = QProcess(self)
        if hasattr(process, 'setUnixProcessParameters'):
            process.setUnixProcessParameters(QProcess.UnixProcessFlag.CreateNewSession)
        process.setStandardOutputFile(QProcess.nullDevice())
        process.setStandardErrorFile(QProcess.nullDevice())

        def complete(code):
            if self.process is process:
                self.process = None
                process.deleteLater()
                callback(code)

        def started():
            process.write((command + '\n').encode())
            process.closeWriteChannel()

        def process_error(error):
            if error == QProcess.ProcessError.FailedToStart:
                complete(None)

        process.started.connect(started)
        process.finished.connect(lambda code, status: complete(
            code if status == QProcess.ExitStatus.NormalExit else None))
        process.errorOccurred.connect(process_error)
        process.start('/bin/sh', ['-s'])

    def before_finished(self, code):
        if code == 0:
            self.proceed()
            return
        box = self.prompt = QMessageBox(self.session)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tr('Before connection'))
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(command_error(code))
        proceed = box.addButton(self.tr('Continue'), QMessageBox.ButtonRole.AcceptRole)
        proceed.setIcon(action_icon(box, 'Connect'))
        proceed.setToolTip(self.tr('Open the connection despite the command error.'))
        cancel = box.addButton(self.tr('Cancel'), QMessageBox.ButtonRole.RejectRole)
        cancel.setIcon(action_icon(box, 'Cancel'))
        cancel.setToolTip(self.tr('Cancel this connection attempt.'))
        retry = box.addButton(self.tr('Retry'), QMessageBox.ButtonRole.ActionRole)
        retry.setIcon(action_icon(box, 'Reconnect'))
        retry.setToolTip(self.tr('Run the local command again before connecting.'))
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.finished.connect(lambda: self.resolve_prompt(box, proceed, retry))
        box.open()

    def resolve_prompt(self, box, proceed, retry):
        if self.prompt is not box:
            return
        self.prompt = None
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is retry:
            self.start_timer.start(0)
        elif clicked is proceed:
            self.proceed()
        else:
            self.start_transport = None
            self.before = ''
            self.report_error(self.tr('Connection attempt cancelled.'))
            self.session.session_status.finish(intentional=True)
            self.session.exited.emit(0)

    def proceed(self):
        start_transport, self.start_transport = self.start_transport, None
        self.before = ''
        try:
            start_transport()
        except (OSError, ValueError, RuntimeError):
            self.report_error(self.tr('Could not start the connection after running the local command.'))
            self.session.session_status.finish(1)
            self.session.exited.emit(1)

    def stop(self):
        self.start_timer.stop()
        self.start_transport = None
        self.before = ''
        box, self.prompt = self.prompt, None
        if box is not None:
            box.reject()
            box.deleteLater()
        process, self.process = self.process, None
        if process is not None:
            pid = process.processId()
            if pid and hasattr(process, 'setUnixProcessParameters'):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.kill()
            process.deleteLater()


def command_error(code):
    if code is None or code < 0:
        return QCoreApplication.translate('ConnectionCommands', 'The local command could not run.')
    return QCoreApplication.translate('ConnectionCommands', 'The local command exited with code %1.').replace('%1', str(code))


class DisconnectCommand(QObject):
    completed = pyqtSignal(object)

    def __init__(self, session, report_error):
        super().__init__(QCoreApplication.instance())
        self.session = session
        self.window = session.window()
        self.report_error = report_error
        self.completed.connect(self.finished)

    def run_when_finished(self, finished_signal, command):
        self.command = command
        finished_signal.connect(self.transport_finished)

    def transport_finished(self):
        if self.command:
            command, self.command = self.command, ''
            self.start(command)

    def start(self, command):
        # Deliver the command even if closing the last window also exits Qt.
        Thread(target=self.launch, args=(command,), daemon=False).start()

    def launch(self, command):
        try:
            process = subprocess.Popen(
                ['/bin/sh', '-s'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            self.notify(None)
            return
        try:
            with process.stdin:
                process.stdin.write((command + '\n').encode())
        except BrokenPipeError:
            pass
        Thread(target=self.reap, args=(process,), daemon=True).start()

    def reap(self, process):
        self.notify(process.wait())

    def notify(self, code):
        try:
            self.completed.emit(code)
        except RuntimeError:
            pass  # Qt can already be shutting down.

    def finished(self, code):
        if code != 0:
            message = self.tr('After disconnection: %1').replace('%1', command_error(code))
            if not isdeleted(self.session):
                self.report_error(message)
            elif isinstance(self.window, QMainWindow) and not isdeleted(self.window):
                self.window.statusBar().showMessage(message, 7000)
        self.deleteLater()
