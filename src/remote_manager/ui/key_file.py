"""Shared vault key file picker."""
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from remote_manager.storage.kdf import generate_key_file
from .icons import action_icon


class KeyFilePicker(QWidget):
    def __init__(self, parent=None, *, allow_generate=False, allow_clear=False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        selection = QHBoxLayout()
        actions = QHBoxLayout()
        layout.addLayout(selection)
        layout.addLayout(actions)
        self.field = QLineEdit()
        self.field.setReadOnly(True)
        self.field.setAccessibleName(self.tr('Key file'))
        selection.addWidget(self.field, 1)

        browse = QPushButton(action_icon(self, 'Open file…'), self.tr('Use existing file…'))
        browse.setToolTip(self.tr('Choose the file used alongside your master password.'))
        browse.clicked.connect(self.browse)
        actions.addWidget(browse)
        if allow_generate:
            generate = QPushButton(action_icon(self, 'New'), self.tr('Generate new key file…'))
            generate.setToolTip(self.tr('Save a new 32-byte random key file.'))
            generate.clicked.connect(self.generate)
            actions.addWidget(generate)
        if allow_clear:
            clear = QPushButton(action_icon(self, 'Cancel'), self.tr('Clear'))
            clear.setToolTip(self.tr('Clear the selected key file.'))
            clear.clicked.connect(self.clear)
            selection.addWidget(clear)
        actions.addStretch()

    @property
    def path(self):
        return Path(self.field.text()) if self.field.text() else None

    def clear(self):
        self.field.clear()

    def browse(self):
        name, _ = QFileDialog.getOpenFileName(self, self.tr('Select key file'))
        if name:
            self.field.setText(name)

    def generate(self):
        name, _ = QFileDialog.getSaveFileName(
            self, self.tr('Generate new key file…'), 'vault.key',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not name:
            return
        try:
            generate_key_file(name)
        except FileExistsError:
            QMessageBox.warning(self, self.tr('Key file'), self.tr('Choose a new filename. Existing key files cannot be overwritten.'))
        except OSError:
            QMessageBox.warning(self, self.tr('Key file'), self.tr('Unable to generate the key file. Check file access.'))
        else:
            self.field.setText(name)
