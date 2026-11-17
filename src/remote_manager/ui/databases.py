"""Startup database chooser; only public file locations enter QSettings."""
from pathlib import Path
from PyQt6.QtCore import QDateTime, QLocale, QSettings, Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget,
                            QTreeWidgetItem, QPushButton, QFileDialog, QInputDialog,
                            QLabel, QMessageBox, QWidget, QStackedWidget, QDialogButtonBox, QHeaderView)
from .dialogs import VaultUnlockPanel
from .icons import action_icon
from .visuals import brand_header, title_label, style_surface
from remote_manager.storage.archive import metadata


class DatabaseChooser(QDialog):
    def __init__(self, legacy_path, parent=None, excluded_path=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr('Open database'))
        self.resize(880, 520)
        style_surface(self)
        self.excluded_path = Path(excluded_path).resolve() if excluded_path else None
        self.vault = None
        self.path = None
        self.settings = QSettings()
        paths = self.settings.value('databases/recent', [], type=list)
        if legacy_path.exists() and str(legacy_path) not in paths:
            paths.append(str(legacy_path))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 20)
        outer.setSpacing(20)
        outer.addWidget(brand_header(self, self.tr('Your remote connections, securely organized.')))
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        self.list_page = QWidget()
        self.pages.addWidget(self.list_page)
        self.unlock_panel = None
        layout = QVBoxLayout(self.list_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(title_label(self.tr('Open database')))
        layout.addWidget(QLabel(self.tr('Choose an independent database for home, work or a customer.')))
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setMinimumHeight(150)
        self.tree.setHeaderLabels([self.tr('Description'), self.tr('Location'),
                                   self.tr('Last modified')])
        self.tree.headerItem().setToolTip(2, self.tr('Last modification time of the database file (local time).'))
        layout.addWidget(self.tree)
        self.empty_message = QLabel(self.tr('No databases in the list. Open a file or create a new database.'))
        self.empty_message.setWordWrap(True)
        layout.addWidget(self.empty_message)
        for path in paths:
            self.add_path(Path(path))
        self.tree.setColumnWidth(0, 180)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected())
        row = QHBoxLayout()
        row.setSpacing(8)
        layout.addLayout(row)
        self.buttons = {}
        for title, action, tooltip in [
                ('Unlock selected', self.open_selected, 'Unlock the selected database with its master password.'),
                ('Open file…', self.browse, 'Choose an existing database file to unlock.'),
                ('New database…', self.create, 'Create a new encrypted database with a description and master password.'),
                ('Remove from list', self.forget, 'Forget the selected database without deleting its file.'),
                ('Cancel', self.reject, 'Close the database chooser.')]:
            button = QPushButton(self.tr(title))
            button.setIcon(action_icon(self, title))
            button.setToolTip(self.tr(tooltip))
            button.clicked.connect(action)
            if title == 'Cancel':
                row.addStretch()
            row.addWidget(button)
            self.buttons[title] = button
            button.setAutoDefault(False)
            if title == 'Unlock selected':
                button.setProperty('primary', True)
                button.setDefault(True)
        self.tree.itemSelectionChanged.connect(self.update_actions)
        self.update_actions()

    def update_actions(self):
        selected = bool(self.tree.selectedItems())
        self.buttons['Unlock selected'].setEnabled(selected)
        self.buttons['Remove from list'].setEnabled(selected)
        self.empty_message.setVisible(self.tree.topLevelItemCount() == 0)

    def add_path(self, path):
        description = path.stem
        try:
            if path.suffix.lower() == '.uni':
                description = metadata(path)['description']
        except Exception:
            description += self.tr(' (unavailable or invalid)')
        try:
            modified = QDateTime.fromMSecsSinceEpoch(path.stat().st_mtime_ns // 1_000_000)
            last_modified = QLocale().toString(modified, QLocale.FormatType.ShortFormat)
        except OSError:
            last_modified = self.tr('Unavailable')
        item = QTreeWidgetItem([description, str(path), last_modified])
        item.setIcon(0, action_icon(self, 'Lock'))
        item.setToolTip(0, description)
        item.setToolTip(1, str(path))
        self.tree.addTopLevelItem(item)
        self.tree.setCurrentItem(item)

    def remember(self):
        self.settings.setValue('databases/recent', [
            self.tree.topLevelItem(i).text(1) for i in range(self.tree.topLevelItemCount())])

    def forget(self):
        item = self.tree.currentItem()
        if item:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
            self.remember()
            self.update_actions()

    def open_path(self, path, description=None):
        if self.excluded_path is not None and path.resolve() == self.excluded_path:
            QMessageBox.information(self, self.tr('Database already open'), self.tr('This database is already open in the current window.'))
            return
        if description is None and not path.is_file():
            QMessageBox.warning(self, self.tr('Database unavailable'), self.tr('The selected file does not exist.'))
            return
        self.clear_unlock_panel()
        panel = VaultUnlockPanel(path, self, description)
        self.unlock_panel = panel
        back = panel.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        back.setText(self.tr('Back to databases'))
        back.setProperty('unircmText', 'Back to databases')
        back.setIcon(action_icon(self, 'Open database'))
        back.setToolTip(self.tr('Return to the database list.'))
        panel.cancelled.connect(self.show_list)
        panel.unlocked.connect(lambda vault: self.finish_unlock(path, vault))
        self.pages.addWidget(panel)
        self.pages.setCurrentWidget(panel)
        self.setWindowTitle(self.tr('Set master password') if panel.setup else self.tr('Unlock database'))
        self.buttons['Unlock selected'].setDefault(False)
        panel.password.setFocus()

    def clear_unlock_panel(self):
        if self.unlock_panel is not None:
            self.unlock_panel.clear()
            self.pages.removeWidget(self.unlock_panel)
            self.unlock_panel.deleteLater()
            self.unlock_panel = None

    def show_list(self):
        self.pages.setCurrentWidget(self.list_page)
        self.clear_unlock_panel()
        self.setWindowTitle(self.tr('Open database'))
        self.buttons['Unlock selected'].setDefault(True)
        self.tree.setFocus()

    def done(self, result):
        if self.unlock_panel is not None:
            self.unlock_panel.clear()
        super().done(result)

    def reject(self):
        if self.unlock_panel is not None:
            self.show_list()
        else:
            super().reject()

    def closeEvent(self, event):
        self.clear_unlock_panel()
        super().closeEvent(event)

    def finish_unlock(self, path, vault):
        if not any(self.tree.topLevelItem(i).text(1) == str(path)
                   for i in range(self.tree.topLevelItemCount())):
            self.add_path(path)
        self.remember()
        self.path, self.vault = path, vault
        self.accept()

    def open_selected(self):
        item = self.tree.currentItem()
        if item:
            self.open_path(Path(item.text(1)))

    def browse(self):
        name, _ = QFileDialog.getOpenFileName(self, self.tr('Open database'), '',
                                               'UniRCm (*.uni);;Legacy SQLCipher (*.db)')
        if name:
            self.open_path(Path(name).resolve())

    def create(self):
        description, ok = QInputDialog.getText(self, self.tr('New database'),
            self.tr('Public description (visible without password):'))
        if not ok or not description.strip():
            return
        name, _ = QFileDialog.getSaveFileName(self, self.tr('Create database'), '', 'UniRCm (*.uni)')
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != '.uni':
            path = Path(str(path) + '.uni')
        if path.exists():
            QMessageBox.warning(self, self.tr('File exists'), self.tr('Choose a new filename. Existing databases cannot be overwritten.'))
            return
        self.open_path(path.resolve(), description.strip())
