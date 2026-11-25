"""Non-blocking SFTP browser and file transfers for an SSH terminal."""
import os
import posixpath
import stat
import threading

from PyQt6.QtCore import QDateTime, QLocale, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QMenu, QHeaderView,
                            QPushButton, QTreeWidget, QTreeWidgetItem, QLabel,
                            QProgressBar, QFileDialog, QMessageBox, QToolButton,
                            QFrame, QSplitter, QToolBar)

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
        self.history = []
        self.history_index = -1
        host = terminal.sftp_host
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        username = terminal.session_status.username.strip()
        self.location_prefix = f'{username}@{host}:' if username else f'{host}:'
        self.setWindowTitle(self.tr('SSH file manager'))
        self.setWindowIcon(action_icon(self, 'Open directory'))
        self.resize(1000, 580)
        layout = QVBoxLayout(self)
        self.path = QLineEdit(self.location_prefix + getattr(terminal, 'sftp_directory', '.'))
        self.path.setAccessibleName(self.tr('Remote location'))
        self.path.setToolTip(self.tr('Enter a remote path and press Enter.'))
        self.path.returnPressed.connect(self.refresh)
        layout.addWidget(self.path)
        self.location_shortcut = QShortcut(QKeySequence('Ctrl+L'), self, self.focus_location)

        toolbar = QToolBar(self.tr('File manager'), self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.back = self.toolbar_action(toolbar, 'Back', 'Back', lambda: self.visit_history(-1))
        self.forward = self.toolbar_action(toolbar, 'Forward', 'Forward', lambda: self.visit_history(1))
        self.up = self.toolbar_action(toolbar, 'Parent directory', 'Move up', self.parent_directory)
        self.reload = self.toolbar_action(toolbar, 'Refresh', 'Refresh', self.reload_directory)
        self.go = self.toolbar_action(toolbar, 'Open directory', 'Open directory', self.refresh)
        toolbar.addSeparator()

        self.new_folder_action = self.toolbar_action(toolbar, 'New folder', 'New group', self.new_folder)
        self.rename_action = self.toolbar_action(toolbar, 'Rename', 'Edit', self.rename_selected)
        self.delete_action = self.toolbar_action(toolbar, 'Delete', 'Delete', self.delete_selected)
        self.upload_action = self.toolbar_action(toolbar, 'Upload file', 'Upload file', self.choose_upload)
        self.download_action = self.toolbar_action(toolbar, 'Download selected files', 'Download file', self.download)
        layout.addWidget(toolbar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([self.tr('Name'), self.tr('Type'), self.tr('Size'),
                                   self.tr('Modified'), self.tr('Permissions')])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, self.tree.columnCount()):
            self.tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemSelectionChanged.connect(self.update_selection_actions)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_file_menu)
        browser = QSplitter()
        places = QFrame()
        places.setFrameShape(QFrame.Shape.StyledPanel)
        places_layout = QVBoxLayout(places)
        places_layout.addWidget(QLabel(self.tr('Remote places')))
        self.home = self.button('Remote home', 'Remote home', lambda: self.navigate('.'))
        self.root = self.button('Filesystem root', 'Filesystem root', lambda: self.navigate('/'))
        for button in (self.home, self.root):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        places_layout.addWidget(self.home, alignment=Qt.AlignmentFlag.AlignLeft)
        places_layout.addWidget(self.root, alignment=Qt.AlignmentFlag.AlignLeft)
        places_layout.addStretch()
        browser.addWidget(places)
        browser.addWidget(self.tree)
        browser.setCollapsible(0, False)
        browser.setCollapsible(1, False)
        browser.setStretchFactor(1, 1)
        layout.addWidget(browser, 1)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.gauge = QProgressBar()
        self.gauge.setMaximumWidth(180)
        row = QHBoxLayout()
        self.cancel_button = self.button('Cancel', 'Cancel', self.cancel)
        self.close_button = self.button('Close', 'Close tab', self.reject)
        row.addWidget(self.status, 1)
        row.addWidget(self.gauge)
        for button in (self.cancel_button, self.close_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.busy(False)
        self.refresh()

    def button(self, text, icon, callback):
        button = QToolButton()
        button.setText(self.tr(text))
        button.setIcon(action_icon(self, icon))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setToolTip(self.tr(text))
        button.setAccessibleName(self.tr(text))
        button.clicked.connect(callback)
        return button

    def toolbar_action(self, toolbar, text, icon, callback):
        label = self.tr(text)
        action = QAction(action_icon(self, icon), label, self)
        action.setToolTip(label)
        action.setIconVisibleInMenu(True)
        action.triggered.connect(callback)
        toolbar.addAction(action)
        toolbar.widgetForAction(action).setAccessibleName(label)
        return action

    def focus_location(self):
        if self.path.isEnabled():
            self.path.setFocus()
            self.path.selectAll()

    def busy(self, value):
        for widget in (self.path, self.go, self.tree, self.home, self.root):
            widget.setEnabled(not value)
        for action in (self.reload, self.upload_action, self.new_folder_action):
            action.setEnabled(not value and self.remote_path is not None)
        self.up.setEnabled(not value and self.remote_path not in (None, '/'))
        self.back.setEnabled(not value and self.history_index > 0)
        self.forward.setEnabled(not value and 0 <= self.history_index < len(self.history) - 1)
        self.update_selection_actions()
        self.cancel_button.setEnabled(value)
        self.gauge.setVisible(value)

    def update_selection_actions(self):
        selected = self.tree.selectedItems()
        available = self.job is None and self.tree.isEnabled()
        self.rename_action.setEnabled(available and len(selected) == 1)
        self.delete_action.setEnabled(available and len(selected) == 1)
        self.download_action.setEnabled(
            available and bool(selected)
            and all(not item.data(0, Qt.ItemDataRole.UserRole)[1] for item in selected)
        )

    def show_file_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            self.tree.clearSelection()
        elif not item.isSelected():
            self.tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addActions([self.new_folder_action, self.rename_action, self.delete_action,
                         self.download_action, self.reload])
        menu.exec(self.tree.viewport().mapToGlobal(position))

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
        if self.remote_path is not None:
            self.path.setText(self.location_prefix + self.remote_path)
        self.status.setText(self.tr('SFTP operation failed: %1').replace('%1', self.tr(message)))

    def finished(self):
        job, self.job = self.job, None
        job.deleteLater()
        self.busy(False)
        self.gauge.setRange(0, 100)
        if self.pending_upload:
            files, self.pending_upload = self.pending_upload, None
            self.upload(files)

    def refresh(self):
        path = self.path.text().removeprefix(self.location_prefix) or '.'
        self.navigate(path)

    def visit_history(self, step):
        index = self.history_index + step
        self.navigate(self.history[index], history_index=index)

    def navigate(self, path, *, history_index=None):
        self.status.setText(self.tr('Reading remote directory…'))

        def operation(client, job):
            canonical = client.realpath(path)
            return canonical, client.listing(canonical)

        def complete(result):
            canonical, _ = result
            if history_index is not None:
                self.history[history_index] = canonical
                self.history_index = history_index
            elif canonical != self.remote_path:
                del self.history[self.history_index + 1:]
                self.history.append(canonical)
                self.history_index = len(self.history) - 1
            self.listed(result)

        self.start(operation, complete)

    def listed(self, result):
        self.remote_path, self.entries = result
        self.terminal.sftp_directory = self.remote_path
        self.path.setText(self.location_prefix + self.remote_path)
        self.tree.clear()
        locale = QLocale()
        for entry in sorted(self.entries, key=lambda entry: (not entry.directory, entry.name)):
            size = '—'
            if not entry.directory and entry.size is not None:
                if entry.size < 2**63:
                    size = locale.formattedDataSize(entry.size, 1)
                else:
                    size = locale.toString(entry.size / 2**60, 'f', 1) + ' EiB'
            modified = '—'
            if entry.mtime is not None:
                modified = locale.toString(QDateTime.fromSecsSinceEpoch(entry.mtime), QLocale.FormatType.ShortFormat)
            permissions = stat.filemode(entry.mode)[1:] if entry.mode is not None else '—'
            item = QTreeWidgetItem([entry.name, self.tr('Directory') if entry.directory else self.tr('File'),
                                    size, modified, permissions])
            item.setData(0, Qt.ItemDataRole.UserRole, (entry.name, entry.directory))
            item.setIcon(0, action_icon(self, 'Remote folder' if entry.directory else 'Remote file'))
            if not entry.directory and entry.size is not None:
                item.setToolTip(2, self.tr('%1 bytes').replace('%1', locale.toString(entry.size)))
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)
        self.status.setText(self.tr('Items: %1').replace('%1', locale.toString(len(self.entries))))
        self.gauge.setValue(0)

    def parent_directory(self):
        self.navigate(posixpath.dirname(self.remote_path) or '/')

    def reload_directory(self):
        self.navigate(self.remote_path)

    def ask_name(self, title, initial=''):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr(title))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(self.tr('Name')))
        field = QLineEdit(initial)
        layout.addWidget(field)
        error = QLabel()
        layout.addWidget(error)
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton(action_icon(dialog, 'Connect'), '')
        cancel = QPushButton(action_icon(dialog, 'Cancel'), '')
        for button, label in ((ok, self.tr('OK')), (cancel, self.tr('Cancel'))):
            button.setToolTip(label)
            button.setAccessibleName(label)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

        def accept_name():
            name = field.text()
            if not name.strip() or name in ('.', '..') or '/' in name or '\x00' in name:
                error.setText(self.tr('Enter a single file or folder name.'))
            else:
                dialog.accept()

        ok.setDefault(True)
        ok.clicked.connect(accept_name)
        cancel.clicked.connect(dialog.reject)
        field.selectAll()
        field.setFocus()
        return field.text() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def new_folder(self):
        name = self.ask_name('New folder')
        if name is not None:
            path = posixpath.join(self.remote_path, name)
            self.change_directory_contents(lambda client: client.mkdir(path), 'Folder created.')

    def rename_selected(self):
        item, = self.tree.selectedItems()
        name, _ = item.data(0, Qt.ItemDataRole.UserRole)
        new_name = self.ask_name('Rename', name)
        if new_name is not None and new_name != name:
            source = posixpath.join(self.remote_path, name)
            destination = posixpath.join(self.remote_path, new_name)
            self.change_directory_contents(lambda client: client.rename(source, destination), 'Item renamed.')

    def delete_selected(self):
        item, = self.tree.selectedItems()
        name, directory = item.data(0, Qt.ItemDataRole.UserRole)
        path = posixpath.join(self.remote_path, name)
        prompt = 'Delete this empty remote folder?' if directory else 'Delete this remote file?'
        if self.confirm(self.tr(prompt) + '\n\n' + path):
            self.change_directory_contents(lambda client: client.remove(path, directory=directory), 'Item deleted.')

    def change_directory_contents(self, change, message):
        remote_path = self.remote_path

        def operation(client, job):
            change(client)
            return remote_path, client.listing(remote_path)

        def complete(result):
            self.listed(result)
            self.status.setText(self.tr(message))

        self.status.setText(self.tr('Updating remote directory…'))
        self.start(operation, complete)

    def open_item(self, item, column):
        name, directory = item.data(0, Qt.ItemDataRole.UserRole)
        if directory:
            self.navigate(posixpath.join(self.remote_path, name))
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
        existing = {entry.name for entry in self.entries}
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
            try:
                return client.listing(remote_path), None
            except (OSError, ValueError, KeyError) as error:
                return None, str(error)

        def complete(result):
            entries, refresh_error = result
            if entries is not None:
                self.listed((remote_path, entries))
            self.completed(refresh_error=refresh_error)

        self.start(operation, complete)

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
        self.start(operation, lambda result: self.completed())

    def confirm(self, text):
        box = QMessageBox(QMessageBox.Icon.Question, self.tr('SSH file manager'), text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        yes = box.button(QMessageBox.StandardButton.Yes)
        no = box.button(QMessageBox.StandardButton.No)
        yes.setIcon(action_icon(self, 'Connect'))
        no.setIcon(action_icon(self, 'Cancel'))
        for button, label in ((yes, self.tr('Yes')), (no, self.tr('No'))):
            button.setText('')
            button.setToolTip(label)
            button.setAccessibleName(label)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def completed(self, *, refresh_error=None):
        message = self.tr('Transfer completed.')
        if refresh_error is not None:
            message += '\n' + self.tr('Could not refresh remote directory: %1').replace('%1', self.tr(refresh_error))
        self.status.setText(message)
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
