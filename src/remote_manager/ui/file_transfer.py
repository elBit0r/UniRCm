"""Non-blocking SFTP browser and file transfers for an SSH terminal."""
import os
import posixpath
import threading

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
                            QPushButton, QTreeWidget, QTreeWidgetItem, QLabel,
                            QProgressBar, QFileDialog, QMessageBox)

from remote_manager.terminal.sftp import SFTPClient, UploadCleanupError
from .icons import action_icon


class TransferJob(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str, object, object)

    def __init__(self, terminal, operation, parent):
        super().__init__(parent)
        self.socket_path = terminal.control_path
        self.host = terminal.sftp_host
        self.operation = operation
        self.cancelled = threading.Event()

    def run(self):
        client = None
        try:
            client = SFTPClient(self.socket_path, self.host, self.cancelled)
            self.result.emit(self.operation(client, self))
        except UploadCleanupError as error:
            self.failed.emit(self.tr('Temporary upload could not be removed: %1. Check the connection and remove this file manually.').replace('%1', error.path))
        except (OSError, ValueError, KeyError) as error:
            self.failed.emit(str(error))
        finally:
            if client is not None:
                client.close()


class FileTransferDialog(QDialog):
    def __init__(self, terminal, files=None):
        super().__init__(terminal)
        self.terminal = terminal
        self.job = None
        self.pending_upload = files
        self.entries = []
        self.remote_path = None
        self.setWindowTitle(self.tr('SSH file transfer'))
        self.resize(680, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr('Remote directory (independent of the terminal):')))
        row = QHBoxLayout()
        self.path = QLineEdit(getattr(terminal, 'sftp_directory', '.'))
        row.addWidget(self.path)
        self.go = self.button('Open directory', 'Open database', self.refresh)
        row.addWidget(self.go)
        self.up = self.button('Parent directory', 'Move up', self.parent_directory)
        row.addWidget(self.up)
        layout.addLayout(row)
        self.path.returnPressed.connect(self.refresh)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([self.tr('Name'), self.tr('Type'), self.tr('Bytes')])
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self.open_item)
        layout.addWidget(self.tree)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.gauge = QProgressBar()
        layout.addWidget(self.gauge)
        row = QHBoxLayout()
        self.upload_button = self.button('Upload file', 'Upload file', self.choose_upload)
        self.download_button = self.button('Download file', 'Download file', self.download)
        self.cancel_button = self.button('Cancel', 'Cancel', self.cancel)
        self.close_button = self.button('Close', 'Close tab', self.reject)
        for button in (self.upload_button, self.download_button, self.cancel_button, self.close_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def button(self, text, icon, callback):
        button = QPushButton(action_icon(self, icon), self.tr(text))
        button.setToolTip(self.tr(text))
        button.clicked.connect(callback)
        return button

    def busy(self, value):
        for widget in (self.path, self.go, self.up, self.tree, self.upload_button, self.download_button):
            widget.setEnabled(not value)
        self.cancel_button.setEnabled(value)

    def start(self, operation, complete):
        if self.job is not None:
            return
        if not self.terminal.file_transfer_available():
            self.status.setText(self.tr('An active SSH connection is required.'))
            return
        self.busy(True)
        self.gauge.setRange(0, 0)
        self.job = TransferJob(self.terminal, operation, self)
        self.job.result.connect(complete)
        self.job.failed.connect(self.failed)
        self.job.progress.connect(self.progress)
        self.job.finished.connect(self.finished)
        self.job.start()

    def failed(self, message):
        self.pending_upload = None
        self.status.setText(self.tr('Transfer failed: ') + self.tr(message))

    def finished(self):
        job, self.job = self.job, None
        job.deleteLater()
        self.busy(False)
        self.gauge.setRange(0, 100)
        if self.pending_upload:
            files, self.pending_upload = self.pending_upload, None
            self.upload(files)

    def refresh(self):
        path = self.path.text() or '.'
        self.status.setText(self.tr('Reading remote directory…'))
        self.start(lambda client, job: (client.realpath(path), client.listing(path)), self.listed)

    def listed(self, result):
        self.remote_path, self.entries = result
        self.terminal.sftp_directory = self.remote_path
        self.path.setText(self.remote_path)
        self.tree.clear()
        for name, directory, size in sorted(self.entries, key=lambda entry: (not entry[1], entry[0])):
            item = QTreeWidgetItem([name, self.tr('Directory') if directory else self.tr('File'), str(size)])
            item.setData(0, Qt.ItemDataRole.UserRole, (name, directory))
            item.setIcon(0, action_icon(self, 'New group' if directory else 'New'))
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)
        self.status.setText(self.tr('Select files to download, or upload local files.'))
        self.gauge.setValue(0)

    def parent_directory(self):
        self.path.setText(posixpath.dirname(self.remote_path or '.') or '/')
        self.refresh()

    def open_item(self, item, column):
        name, directory = item.data(0, Qt.ItemDataRole.UserRole)
        if directory:
            self.path.setText(posixpath.join(self.remote_path, name))
            self.refresh()
        else:
            self.download()

    def choose_upload(self):
        files, _ = QFileDialog.getOpenFileNames(self, self.tr('Upload file'))
        if files:
            self.upload(files)

    def upload(self, files):
        if self.remote_path is None or self.job is not None:
            return
        if any(not os.path.isfile(path) for path in files):
            self.status.setText(self.tr('Only regular files can be transferred.'))
            return
        names = [os.path.basename(path) for path in files]
        if len(set(names)) != len(names):
            self.status.setText(self.tr('Files with the same name must be uploaded separately.'))
            return
        existing = {name for name, directory, size in self.entries}
        conflicts = existing.intersection(names)
        text = self.tr('Upload these files to: ') + self.remote_path + '\n\n' + '\n'.join(names)
        if conflicts:
            text += '\n\n' + self.tr('Replace existing files?') + '\n' + '\n'.join(sorted(conflicts))
        if not self.confirm(text):
            return
        remote_path = self.remote_path
        def operation(client, job):
            for local, name in zip(files, names):
                client.upload(local, posixpath.join(remote_path, name),
                              lambda done, total: job.progress.emit(name, done, total), name in conflicts)
            return remote_path, client.listing(remote_path)
        self.start(operation, self.completed)

    def download(self):
        entries = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()]
        if not entries or any(directory for name, directory in entries):
            self.status.setText(self.tr('Select regular files to download.'))
            return
        directory = QFileDialog.getExistingDirectory(self, self.tr('Download folder'))
        if not directory:
            return
        targets = [(name, os.path.join(directory, name)) for name, _ in entries]
        conflicts = {local for name, local in targets if os.path.lexists(local)}
        if conflicts and not self.confirm(self.tr('Replace existing files?') + '\n' + '\n'.join(sorted(conflicts))):
            return
        remote_path = self.remote_path
        def operation(client, job):
            for name, local in targets:
                client.download(posixpath.join(remote_path, name), local,
                                lambda done, total: job.progress.emit(name, done, total), local in conflicts)
            return remote_path, client.listing(remote_path)
        self.start(operation, self.completed)

    def confirm(self, text):
        return QMessageBox.question(self, self.tr('SSH file transfer'), text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def completed(self, result):
        self.listed(result)
        self.status.setText(self.tr('Transfer completed.'))
        self.gauge.setRange(0, 100)
        self.gauge.setValue(100)

    def progress(self, name, done, total):
        self.gauge.setRange(0, 100)
        self.gauge.setValue(min(100, int(done * 100 / total)) if total else 0)
        self.status.setText(f'{name}: {done} / {total} ' + self.tr('bytes'))

    def cancel(self):
        self.pending_upload = None
        if self.job is not None:
            self.job.cancelled.set()

    def shutdown(self):
        self.cancel()
        if self.job is not None:
            self.job.wait()
        self.hide()

    def closeEvent(self, event):
        if self.job is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self):
        if self.job is not None:
            self.cancel()
            self.status.setText(self.tr('Cancelling…'))
            return
        super().reject()
