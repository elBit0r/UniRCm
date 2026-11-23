"""Encrypted database settings and deliberate master-password maintenance."""
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                            QLineEdit, QPushButton, QSpinBox, QPlainTextEdit, QComboBox,
                            QVBoxLayout, QWidget, QScrollArea, QFrame, QCheckBox)
from remote_manager.storage.archive import ArchiveVault
from remote_manager.storage.kdf import KeyFileError
from remote_manager.storage.vault import BackupError

from .credentials import decorate_buttons
from .icons import action_icon
from .key_file import KeyFilePicker, remember_key_file, remembered_key_file
from .forms import (NamedButtonBox, polish_dialog, primary_action, section,
                    validated_field, require_fields, field_error)


class ChangePasswordDialog(QDialog):
    def __init__(self, vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.is_archive = isinstance(vault, ArchiveVault)
        self.setWindowTitle(self.tr('Change vault protection') if self.is_archive else self.tr('Change master password'))
        self.resize(620, 420)
        layout = QFormLayout(self)
        section(layout, 'Master password', 'The current password is required to protect the encrypted database with a new password.')
        self.fields = {}
        for key, title in [('current', 'Current master password'), ('new', 'New master password'), ('confirmation', 'Confirm new master password')]:
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setProperty('secret', True)
            self.fields[key] = field
            layout.addRow(self.tr(title), validated_field(self, field))
        self.show_passwords = QCheckBox(self.tr('Show passwords'))
        self.show_passwords.setIcon(action_icon(self, 'Credentials'))
        self.show_passwords.setToolTip(self.tr('Show or hide the entered master passwords.'))
        self.show_passwords.toggled.connect(lambda visible: [field.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
            for field in self.fields.values()])
        layout.addRow(self.show_passwords)
        self.current_key_file = None
        if self.is_archive:
            if vault.key_file_required:
                self.current_key_file = KeyFilePicker(self)
                self.current_key_file.field.setText(remembered_key_file(vault.archive_path))
                layout.addRow(self.tr('Current key file'), self.current_key_file)
            self.key_file_action = QComboBox()
            self.key_file_action.addItem(self.tr('Keep current key file') if vault.key_file_required else self.tr('Use password only'), 'keep')
            self.key_file_action.addItem(
                self.tr('Replace key file') if vault.key_file_required else self.tr('Add key file'), 'select')
            if vault.key_file_required:
                self.key_file_action.addItem(self.tr('Remove key file'), 'remove')
            layout.addRow(self.tr('Key file'), self.key_file_action)
            self.new_key_file = KeyFilePicker(self, allow_generate=True)
            layout.addRow(self.new_key_file)
            self.new_key_file.hide()
            self.key_file_action.currentIndexChanged.connect(
                lambda: self.new_key_file.setVisible(self.key_file_action.currentData() == 'select'))
            warning = QLabel(self.tr('If you lose a required key file, you cannot unlock the database. '
                                     'To change only the key file, leave the new password fields empty.'))
            warning.setWordWrap(True)
            layout.addRow(warning)
        backup = QLabel(self.tr('An encrypted backup is saved beside the database. It uses the current master password and any current key file.')
                        if self.is_archive else self.tr('An encrypted backup is saved beside the database. It uses the current master password.'))
        backup.setWordWrap(True)
        layout.addRow(backup)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addRow(self.error)
        buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        primary_action(buttons, 'Change vault protection' if self.is_archive else 'Change master password')
        layout.addRow(buttons)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.finished.connect(self.clear)
        polish_dialog(self)

    def clear(self, *_):
        self.show_passwords.setChecked(False)
        for field in self.fields.values():
            field.clear()
        if self.current_key_file:
            self.current_key_file.clear()
        if self.is_archive:
            self.new_key_file.clear()

    def save(self):
        self.error.clear()
        action = self.key_file_action.currentData() if self.is_archive else 'keep'
        required = [(self.fields['current'], 'Enter the current master password.')]
        if action == 'keep':
            required.append((self.fields['new'], 'Enter a new master password.'))
        if not require_fields(self, required):
            return
        current = self.fields['current'].text()
        replacement = self.fields['new'].text()
        if replacement != self.fields['confirmation'].text():
            field_error(self, self.fields['confirmation'], self.tr('New passwords do not match.'))
            return
        options = {}
        if self.current_key_file:
            options['key_file'] = self.current_key_file.path
        if action == 'select':
            if self.new_key_file.path is None:
                self.error.setText(self.tr('Choose or generate a new key file.'))
                return
            options['new_key_file'] = self.new_key_file.path
        elif action == 'remove':
            options['new_key_file'] = None
        try:
            self.vault.change_password(current, replacement or current, **options)
        except KeyFileError as error:
            self.error.setText(self.tr(str(error)))
            return
        except BackupError:
            self.error.setText(self.tr('Unable to create a verified encrypted backup. Check disk space and database access.'))
            return
        except Exception as error:
            message = str(error)
            field = ('current' if message == 'Current master password is incorrect.'
                     else 'new' if message == 'Choose a different new master password.' else None)
            if self.is_archive and self.current_key_file and field == 'current':
                self.error.setText(self.tr('The current master password or key file is incorrect.'))
            elif field == 'new' and action != 'keep':
                self.error.setText(self.tr('Choose a different key file or master password.'))
            elif isinstance(error, ValueError) and field:
                field_error(self, self.fields[field], self.tr(message))
            else:
                self.error.setText(self.tr(message) if isinstance(error, ValueError) else self.tr('Unable to change the master password.'))
            return
        if self.is_archive:
            key_file = options.get('new_key_file', options.get('key_file'))
            remember_key_file(self.vault.archive_path, key_file)
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle(self.tr('Database settings'))
        self.resize(660, 600)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QFormLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        section(layout, 'General settings')
        self.language = QComboBox()
        self.language.addItem(self.tr('English'), 'en')
        self.language.addItem(self.tr('Italian'), 'it')
        self.language.setCurrentIndex(self.language.findData(vault.language()))
        layout.addRow(self.tr('Language'), self.language)
        self.description = None
        if hasattr(vault, 'metadata'):
            self.description = QPlainTextEdit(vault.metadata['description'])
            self.description.setMaximumHeight(85)
            self.description.setToolTip(self.tr('Public archive description, visible before unlocking. Do not enter credentials or sensitive information.'))
            layout.addRow(self.tr('Archive description'), self.description)
        section(layout, 'Security')
        self.inactivity = QSpinBox()
        self.inactivity.setRange(0, 1440)
        self.inactivity.setSpecialValueText(self.tr('Disabled'))
        self.inactivity.setSuffix(self.tr(' min'))
        self.inactivity.setValue(vault.inactivity_minutes())
        self.inactivity.setToolTip(self.tr('Automatically disconnects all sessions and locks this database after no keyboard or mouse activity. Remote output does not reset the timeout.'))
        layout.addRow(self.tr('Inactivity lock'), self.inactivity)
        warning = QLabel(self.tr('Enabling inactivity lock closes active sessions and open editors automatically when the timeout expires.'))
        warning.setWordWrap(True)
        layout.addRow(warning)
        section(layout, 'Appearance and maintenance', 'These actions save their changes immediately.')
        profiles = QPushButton(action_icon(self, 'Edit'), self.tr('Terminal profiles…'))
        profiles.setToolTip(self.tr('Create and edit shared font and color profiles for SSH and Telnet. Changes are saved immediately.'))
        def manage_profiles():
            from .terminal_profiles import TerminalProfilesDialog
            TerminalProfilesDialog(vault, self).exec()
            if parent is not None and hasattr(parent, 'refresh'):
                parent.refresh()
        profiles.clicked.connect(manage_profiles)
        layout.addRow(profiles)
        if isinstance(vault, ArchiveVault):
            change = QPushButton(action_icon(self, 'Lock'), self.tr('Change vault protection…'))
            change.setToolTip(self.tr('Change the master password or add, replace or remove a key file.'))
        else:
            change = QPushButton(action_icon(self, 'Lock'), self.tr('Change master password…'))
            change.setToolTip(self.tr('Requires the current master password and verifies the encrypted database with the new password.'))
        change.clicked.connect(lambda: ChangePasswordDialog(vault, self).exec())
        layout.addRow(change)
        self.error = QLabel()
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        primary_action(buttons, 'Save settings')
        outer.addWidget(buttons)
        polish_dialog(self)

    def save(self):
        self.error.clear()
        try:
            if self.description is not None and self.description.toPlainText() != self.vault.metadata['description']:
                self.vault.set_description(self.description.toPlainText())
            self.vault.set_inactivity_minutes(self.inactivity.value())
            self.vault.set_language(self.language.currentData())
        except Exception:
            self.error.setText(self.tr('Unable to save encrypted database settings.'))
            return
        self.accept()
