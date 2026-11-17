"""Searchable visual picker shared by connection and group editors."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLineEdit, QListWidget,
                            QListWidgetItem, QListView, QDialogButtonBox, QPushButton)
from .icons import CONNECTION_ICONS, group_icon
from .credentials import decorate_buttons


class IconDialog(QDialog):
    def __init__(self, selected, include_folder=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr('Choose icon'))
        self.resize(650, 480)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr('Search icons…'))
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setIconSize(QSize(48, 48))
        self.grid.setGridSize(QSize(112, 98))
        self.grid.setWordWrap(True)
        self.grid.setAccessibleName(self.tr('Available icons'))
        choices = dict(folder='Group', **CONNECTION_ICONS) if include_folder else CONNECTION_ICONS
        for key, title in choices.items():
            item = QListWidgetItem(group_icon(self, key), self.tr(title))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(self.tr(title))
            self.grid.addItem(item)
            if key == selected:
                self.grid.setCurrentItem(item)
        if self.grid.currentItem() is None:
            self.grid.setCurrentRow(0)
        layout.addWidget(self.grid)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(self.buttons)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.grid.itemActivated.connect(lambda _: self.accept())
        self.search.textChanged.connect(self.filter_icons)
        self.grid.currentItemChanged.connect(lambda *_: self.update_accept())
        self.search.setFocus()

    def filter_icons(self, text):
        text = text.strip().casefold()
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            item.setHidden(text not in (item.text() + ' ' + item.data(Qt.ItemDataRole.UserRole)).casefold())
        if self.grid.currentItem() is None or self.grid.currentItem().isHidden():
            visible = next((self.grid.item(row) for row in range(self.grid.count()) if not self.grid.item(row).isHidden()), None)
            self.grid.setCurrentItem(visible)
        self.update_accept()

    def update_accept(self):
        item = self.grid.currentItem()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(item is not None and not item.isHidden())

    def accept(self):
        item = self.grid.currentItem()
        if item is not None and not item.isHidden():
            super().accept()

    def selected_icon(self):
        return self.grid.currentItem().data(Qt.ItemDataRole.UserRole)


class IconPicker(QPushButton):
    def __init__(self, selected='terminal', include_folder=False, parent=None):
        super().__init__(parent)
        self.include_folder = include_folder
        self.setIconSize(QSize(32, 32))
        self.setToolTip(self.tr('Choose an icon from the library.'))
        self.set_icon(selected)
        self.clicked.connect(self.choose_icon)

    def set_icon(self, name):
        self._selected = name if name in CONNECTION_ICONS or (name == 'folder' and self.include_folder) else 'terminal'
        title = 'Group' if self._selected == 'folder' else CONNECTION_ICONS[self._selected]
        self.setText(self.tr(title) + '…')
        self.setIcon(group_icon(self, self._selected))

    def selected_icon(self):
        return self._selected

    def choose_icon(self):
        dialog = IconDialog(self._selected, self.include_folder, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_icon(dialog.selected_icon())
