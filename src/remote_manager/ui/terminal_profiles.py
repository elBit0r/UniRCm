"""Manage shared terminal appearance profiles in the encrypted vault."""
import uuid
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QLineEdit, QLabel, QDialogButtonBox, QMessageBox)
from .dialogs import TerminalOptions
from .icons import action_icon
from .credentials import decorate_buttons


class TerminalProfilesDialog(QDialog):
    def __init__(self, vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle(self.tr('Terminal profiles'))
        self.resize(540, 580)
        layout = QVBoxLayout(self)
        self.choice = QComboBox()
        layout.addWidget(self.choice)
        actions = QHBoxLayout()
        for title, callback in [('New', self.new), ('Duplicate', self.duplicate), ('Edit', self.edit), ('Delete', self.delete)]:
            button = QPushButton(action_icon(self, title), self.tr(title))
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.reload()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        decorate_buttons(close)
        close.rejected.connect(self.accept)
        layout.addWidget(close)

    def reload(self):
        selected = self.choice.currentData()
        self.profiles = self.vault.terminal_profiles()
        self.choice.clear()
        for profile in self.profiles:
            self.choice.addItem(profile['name'], profile['id'])
        self.choice.setCurrentIndex(max(0, self.choice.findData(selected)))

    def current(self):
        return next((p for p in self.profiles if p['id'] == self.choice.currentData()), None)

    def new(self):
        self.edit_profile(dict(id=uuid.uuid4().hex, name='', options={}))

    def duplicate(self):
        profile = self.current()
        if profile:
            self.edit_profile(dict(profile, id=uuid.uuid4().hex, name=profile['name'] + ' copy'))

    def edit(self):
        if self.current():
            self.edit_profile(self.current())

    def edit_profile(self, profile):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('Edit terminal profile'))
        layout = QVBoxLayout(dialog)
        name = QLineEdit(profile['name'])
        name.setPlaceholderText(self.tr('Profile name'))
        layout.addWidget(name)
        editor = TerminalOptions(profile['options'], dialog, profiles=False)
        layout.addWidget(editor)
        preview = QLabel('user@host:~$ ls -l\nSolaris Unix Linux 0123456789')
        layout.addWidget(preview)
        def update():
            values = editor.options()
            preview.setFont(QFont(values['font_family'], values['font_size']))
            preview.setStyleSheet('color: %s; background: %s; padding: 12px;' % (values['foreground'], values['background']))
        editor.changed.connect(update)
        update()
        error = QLabel()
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        layout.addWidget(buttons)
        def save():
            updated = dict(profile, name=name.text().strip(), options=editor.options())
            profiles = [p for p in self.profiles if p['id'] != profile['id']] + [updated]
            try:
                self.vault.save_terminal_profiles(profiles)
            except Exception as exc:
                error.setText(str(exc) if isinstance(exc, ValueError) else self.tr('Unable to save terminal profiles.'))
                return
            dialog.accept()
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec():
            self.reload()

    def delete(self):
        profile = self.current()
        if not profile:
            return
        others = [p for p in self.profiles if p['id'] != profile['id']]
        if not others:
            QMessageBox.warning(self, self.tr('Delete'), self.tr('Keep at least one terminal profile.'))
            return
        dialog = QDialog(self)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(self.tr('Replace references to this profile with:')))
        replacement = QComboBox()
        for item in others:
            replacement.addItem(item['name'], item['id'])
        layout.addWidget(replacement)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec():
            try:
                self.vault.replace_terminal_profile(profile['id'], replacement.currentData())
            except Exception:
                QMessageBox.warning(self, self.tr('Delete'), self.tr('Unable to delete terminal profile.'))
                return
            self.reload()
