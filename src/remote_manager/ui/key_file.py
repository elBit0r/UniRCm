"""Shared vault key file picker."""
from hashlib import sha256
from os import fsencode
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLayout, QLineEdit, QMessageBox,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from remote_manager.storage.kdf import generate_key_file
from .icons import action_icon


def _key_file_setting(archive_path):
    archive_id = sha256(fsencode(archive_path.resolve())).hexdigest()
    return f'databases/keyFiles/{archive_id}'


def remembered_key_file(archive_path):
    return QSettings().value(_key_file_setting(archive_path), '', type=str)


def remember_key_file(archive_path, key_file):
    settings = QSettings()
    key = _key_file_setting(archive_path)
    if key_file is None:
        settings.remove(key)
    else:
        settings.setValue(key, str(key_file.absolute()))


class KeyFilePicker(QWidget):
    cleared = pyqtSignal()

    def __init__(self, parent=None, *, allow_generate=False, allow_clear=False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        actions = QHBoxLayout()
        self.field = QLineEdit()
        self.field.setReadOnly(True)
        self.field.setAccessibleName(self.tr('Key file'))
        self.field.textChanged.connect(self.field.setToolTip)
        layout.addWidget(self.field)
        layout.addLayout(actions)

        browse = QPushButton(action_icon(self, 'Open file…'), self.tr('Use existing file…'))
        browse.setToolTip(self.tr('Choose the file used alongside your master password.'))
        browse.clicked.connect(self.browse)
        actions.addWidget(browse)
        if allow_generate:
            generate = QPushButton(action_icon(self, 'New'), self.tr('Generate new key file…'))
            generate.setToolTip(self.tr('Save a new 32-byte random key file.'))
            generate.clicked.connect(self.generate)
            layout.addWidget(generate, alignment=Qt.AlignmentFlag.AlignLeft)
        if allow_clear:
            clear = QPushButton(action_icon(self, 'Cancel'), self.tr('Clear'))
            clear.setToolTip(self.tr('Clear the selection and forget the saved key file path.'))
            clear.clicked.connect(self.clear)
            clear.clicked.connect(self.cleared.emit)
            actions.addWidget(clear)
        actions.addStretch()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    @property
    def path(self):
        return Path(self.field.text()) if self.field.text() else None

    def clear(self):
        self.field.clear()

    def browse(self):
        name, _ = QFileDialog.getOpenFileName(self, self.tr('Select key file'), self.field.text())
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
