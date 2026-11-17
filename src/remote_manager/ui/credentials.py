"""Protocol-independent username/password editor."""
from PyQt6.QtWidgets import QWidget, QFormLayout, QLineEdit, QCheckBox

from .visuals import title_label
from .forms import (NamedButtonBox, polish_dialog, primary_action, section,
                    validated_field, require_fields, field_error, clear_field)


class CredentialsEditor(QWidget):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.username = QLineEdit(profile.get('username', ''))
        self.password = QLineEdit(profile.get('password', ''))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_passphrase = QLineEdit(profile.get('key_passphrase', ''))
        self.key_passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_passphrase.setToolTip(self.tr('SSH private-key passphrase, stored in the common encrypted credential. Select or import the matching private key in SSH properties. Other protocols do not send it. Automatic key unlocking disables SSH keyboard-interactive authentication for this session.'))
        self.username.setToolTip(self.tr('Username used to authenticate to the remote server.'))
        self.password.setToolTip(self.tr('Stored only in the encrypted database. Leave empty to authenticate interactively or with a key/agent.'))
        self.form.addRow(self.tr('Password'), self.password)
        self.form.addRow(self.tr('Private-key passphrase (SSH)'), self.key_passphrase)
        self.show_secrets = QCheckBox(self.tr('Show passwords'))
        from .icons import action_icon
        self.show_secrets.setIcon(action_icon(self, 'Credentials'))
        self.show_secrets.setToolTip(self.tr('Show or hide the password and private-key passphrase.'))
        self.show_secrets.toggled.connect(lambda visible: [field.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
            for field in (self.password, self.key_passphrase)])
        self.form.addRow(self.show_secrets)

    def values(self):
        return {'username': self.username.text().strip(), 'password': self.password.text(), 'key_passphrase': self.key_passphrase.text()}


class CredentialSelector(QWidget):
    """References only: never display a shared secret in connection/group editors."""
    def __init__(self, vault, source='local', credential_id=None, group=False, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QComboBox, QLabel
        self.vault = vault
        self.group = group
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.source = QComboBox()
        choices = [('Inherit from parent' if group else 'Inherit from group', 'inherit'),
                   ('Shared credential', 'shared'), ('No shared credential', 'none')]
        if not group:
            choices.insert(0, ('Connection credentials', 'local'))
        for label, value in choices:
            self.source.addItem(self.tr(label), value)
        self.source.setCurrentIndex(max(0, self.source.findData(source)))
        self.reference = QComboBox()
        self.reference.addItem(self.tr('Select credential…'), None)
        for credential in vault.shared_credentials() if vault else ():
            self.reference.addItem(f"{credential['name']} ({credential['username']})", credential['id'])
        self.reference.setCurrentIndex(max(0, self.reference.findData(credential_id)))
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty('effectiveValue', True)
        self.form.addRow(self.tr('Credential source'), self.source)
        self.reference_row = validated_field(self, self.reference)
        self.form.addRow(self.tr('Shared credential'), self.reference_row)
        self.form.addRow(self.note)
        self.source.currentIndexChanged.connect(self.update_state)
        self.update_state()

    def update_state(self, *_):
        self.form.setRowVisible(self.reference_row, self.source.currentData() == 'shared')
        clear_field(self, self.reference)
        self.reference.setEnabled(self.source.currentData() == 'shared')

    def inherited(self, folder_id, folders):
        from remote_manager.storage.vault import resolve_ssh
        result = resolve_ssh({'folder_id': folder_id, 'ssh_modes': {'credential_id': 'inherit'}}, folders)
        reference = result.get('credential_id')
        credential = next((item for item in self.vault.shared_credentials()
                           if item['id'] == reference), None) if self.vault and reference else None
        origin = ''
        by_id = {folder['id']: folder for folder in folders}
        ancestor = folder_id
        while ancestor in by_id:
            folder = by_id[ancestor]
            if 'credential_id' in folder.get('ssh_defaults', {}):
                names = [folder['name']]
                parent = folder.get('parent_id')
                while parent in by_id:
                    names.insert(0, by_id[parent]['name'])
                    parent = by_id[parent].get('parent_id')
                origin = ' — ' + self.tr('Inherited from %1').replace('%1', ' / '.join(names))
                break
            ancestor = folder.get('parent_id')
        self.note.setText(self.tr('Inherited credential: ') + (credential['name'] if credential else self.tr('None')) + origin)
        self.note.setVisible(self.source.currentData() == 'inherit')

    def values(self):
        source = self.source.currentData()
        reference = self.reference.currentData() if source == 'shared' else None
        if source == 'shared' and not reference:
            field_error(self, self.reference, self.tr('Select a shared credential.'))
            raise ValueError(self.tr('Select a shared credential.'))
        return source, reference


def decorate_buttons(buttons):
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QDialogButtonBox, QStyle
    for button in buttons.buttons():
        standard = buttons.standardButton(button)
        accepted = buttons.buttonRole(button) in (QDialogButtonBox.ButtonRole.AcceptRole, QDialogButtonBox.ButtonRole.ApplyRole, QDialogButtonBox.ButtonRole.YesRole)
        theme = 'document-save' if standard == buttons.StandardButton.Save else 'dialog-ok' if accepted else 'dialog-cancel'
        fallback = QStyle.StandardPixmap.SP_DialogSaveButton if standard == buttons.StandardButton.Save else QStyle.StandardPixmap.SP_DialogOkButton if accepted else QStyle.StandardPixmap.SP_DialogCancelButton
        button.setIcon(QIcon.fromTheme(theme, button.style().standardIcon(fallback)))
        button.setToolTip(button.text().replace('&', ''))


class CredentialManager:
    @staticmethod
    def open(vault, parent):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QMessageBox, QLabel
        from .icons import action_icon
        dialog = QDialog(parent)
        dialog.setWindowTitle(parent.tr('Shared credentials'))
        dialog.resize(640, 430)
        layout = QVBoxLayout(dialog)
        layout.addWidget(title_label(parent.tr('Shared credentials')))
        listing = QListWidget()
        listing.setSpacing(5)
        layout.addWidget(listing)
        empty_message = QLabel(parent.tr('No shared credentials yet. Use New credential to create one.'))
        empty_message.setWordWrap(True)
        layout.addWidget(empty_message)
        actions = {}

        def update_actions():
            has_selection = bool(listing.selectedItems())
            for title in ('Edit', 'Delete'):
                actions[title].setEnabled(has_selection)
            empty_message.setVisible(listing.count() == 0)

        def refresh():
            reference = selected()
            listing.clear()
            for credential in vault.shared_credentials():
                from PyQt6.QtCore import Qt
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(f"{credential['name']} ({credential['username']})")
                item.setData(Qt.ItemDataRole.UserRole, credential['id'])
                listing.addItem(item)
                if credential['id'] == reference:
                    listing.setCurrentItem(item)
            update_actions()

        def selected():
            from PyQt6.QtCore import Qt
            return listing.currentItem().data(Qt.ItemDataRole.UserRole) if listing.currentItem() else None

        def edit(new=False):
            reference = None if new else selected()
            if not new and reference is None:
                return
            data = vault.credential(reference) if reference else {}
            editor = QDialog(dialog)
            editor.setWindowTitle(parent.tr('New credential') if new else parent.tr('Edit credential'))
            form = QFormLayout(editor)
            name = QLineEdit(data.get('name', ''))
            fields = CredentialsEditor(data, editor)
            fields.form.insertRow(0, parent.tr('Username'), fields.username)
            section(form, 'Credential details')
            form.addRow(parent.tr('Name'), validated_field(editor, name))
            form.addRow(fields)
            from PyQt6.QtWidgets import QDialogButtonBox, QLabel
            error = QLabel()
            form.addRow(error)
            buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            decorate_buttons(buttons)
            primary_action(buttons, 'Save')
            form.addRow(buttons)
            def save():
                error.clear()
                if not require_fields(editor, [(name, 'Enter a credential name.')]):
                    return
                try:
                    vault.save_credential(name.text(), **fields.values(), credential_id=reference)
                except Exception as exc:
                    error.setText(str(exc) if isinstance(exc, ValueError) else parent.tr('Unable to save encrypted credential.'))
                    return
                editor.accept()
            buttons.accepted.connect(save)
            buttons.rejected.connect(editor.reject)
            editor.resize(620, 360)
            polish_dialog(editor)
            editor.exec()
            fields.show_secrets.setChecked(False)
            fields.password.clear()
            fields.key_passphrase.clear()
            refresh()

        def delete():
            reference = selected()
            if reference and QMessageBox.question(dialog, parent.tr('Delete credential'), parent.tr('Delete selected shared credential?')) == QMessageBox.StandardButton.Yes:
                try:
                    vault.delete_credential(reference)
                except Exception as exc:
                    QMessageBox.warning(dialog, parent.tr('Delete failed'), str(exc) if isinstance(exc, ValueError) else parent.tr('Unable to delete encrypted credential.'))
                refresh()

        row = QHBoxLayout()
        for title, icon, callback in [('New credential', 'New', lambda: edit(True)), ('Edit', 'Edit', edit), ('Delete', 'Delete', delete), ('Close', 'Cancel', dialog.accept)]:
            button = QPushButton(action_icon(dialog, icon), parent.tr(title))
            button.setToolTip(parent.tr(title))
            button.clicked.connect(lambda checked=False, cb=callback: cb())
            row.addWidget(button)
            actions[title] = button
        layout.addLayout(row)
        listing.itemSelectionChanged.connect(update_actions)
        refresh()
        polish_dialog(dialog)
        dialog.exec()
