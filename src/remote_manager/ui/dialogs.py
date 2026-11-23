from glob import escape
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont
from .credentials import CredentialsEditor, CredentialSelector, decorate_buttons
from .icons import connection_icon, action_icon
from .icon_picker import IconPicker
from .key_file import KeyFilePicker
from .visuals import brand_header, title_label, style_surface
from .forms import (NamedButtonBox, polish_dialog, primary_action, section,
                    validated_field, require_fields, icon_label)
from .ssh_advanced import AdvancedSSHOptions
from .rdp_options import RdpOptions

from PyQt6.QtWidgets import (QApplication, QButtonGroup, QRadioButton, QFontComboBox, QColorDialog, QTabWidget, QVBoxLayout, QWidget,QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                            QFormLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QFrame,
                            QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox)

from remote_manager.storage.archive import ArchiveInUse, ArchiveVault, RecoveryConflict, metadata, restore_backup
from remote_manager.storage.vault import Vault, SSH_DEFAULTS, resolve_ssh, validate_ssh_settings, validate_group_appearance
from remote_manager.storage.vault import DEFAULT_KDF_ITERATIONS, MAX_KDF_ITERATIONS, MAX_SSH_RECONNECT_DELAY
from remote_manager.storage.kdf import KeyFileError
from remote_manager.storage.vault import BackupError, UnsupportedSchemaVersion
from remote_manager.terminal.ssh import ssh_command
from remote_manager.terminal.private_key import read_imported_key
from remote_manager.terminal.appearance import DEFAULT_OPTIONS, default_font


class VaultUnlockPanel(QWidget):
    unlocked = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(self, path, parent=None, description=None):
        super().__init__(parent)
        self.path = path
        self.description = description
        self.is_archive = path.suffix.lower() == '.uni'
        self.setup = description is not None or not path.exists() or path.stat().st_size == 0
        style_surface(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 12)
        outer.addStretch()
        card = QFrame()
        card.setMaximumWidth(500)
        card.setObjectName('unlockCard')
        card.setStyleSheet('QFrame#unlockCard { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }')
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        layout = QFormLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        heading = title_label(self.tr('Set master password') if self.setup else self.tr('Unlock database'))
        layout.addRow(heading)
        name = description or path.stem
        key_required = False
        if description is None and self.is_archive:
            try:
                public = metadata(path)
                name = public['description']
                key_required = public.get('key_file_required') is True
            except Exception:
                pass
        self.key_file_required = key_required
        layout.addRow(title_label(name, size=12))
        destination = QLabel(str(path))
        destination.setTextFormat(Qt.TextFormat.PlainText)
        destination.setWordWrap(True)
        destination.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addRow(destination)
        hint = QLabel(self.tr('Protects all saved connection profiles. Password recovery is unavailable.'))
        hint.setWordWrap(True)
        layout.addRow(hint)
        self.password = QLineEdit()
        self.confirmation = QLineEdit()
        for field in (self.password, self.confirmation):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow(self.tr('Master password'), self.password)
        if self.setup:
            strength_row = QWidget()
            strength_layout = QHBoxLayout(strength_row)
            strength_layout.setContentsMargins(0, 0, 0, 0)
            self.password_strength = QProgressBar()
            self.password_strength.setRange(0, 3)
            self.password_strength.setTextVisible(False)
            self.password_strength.setFixedHeight(10)
            self.password_strength.setAccessibleName(self.tr('Password strength'))
            self.strength_label = QLabel()
            strength_layout.addWidget(self.password_strength, 1)
            strength_layout.addWidget(self.strength_label)
            strength_row.setToolTip(self.tr('Estimates strength from password length and character variety.'))
            layout.addRow(self.tr('Password strength'), strength_row)
            self.password.textChanged.connect(self.update_password_strength)
            self.update_password_strength('')
            layout.addRow(self.tr('Confirm password'), self.confirmation)
            if self.is_archive:
                self.kdf = QComboBox()
                self.kdf.addItem('Argon2id', 'argon2id')
                self.kdf.addItem('PBKDF2', 'pbkdf2')
                self.kdf.setToolTip(self.tr('Argon2id uses both memory and computation to slow offline password guessing.'))
                layout.addRow(self.tr('Key derivation'), self.kdf)
                self.kdf_iterations = QSpinBox()
                self.kdf_iterations.setRange(DEFAULT_KDF_ITERATIONS, MAX_KDF_ITERATIONS)
                self.kdf_iterations.setValue(DEFAULT_KDF_ITERATIONS)
                self.kdf_iterations.setSingleStep(128_000)
                self.kdf_iterations.setGroupSeparatorShown(True)
                self.kdf_iterations.setToolTip(self.tr('Higher values slow down both unlocking and offline password guessing.'))
                layout.addRow(self.tr('Key derivation iterations'), self.kdf_iterations)
                self.kdf.currentIndexChanged.connect(
                    lambda: self.kdf_iterations.setEnabled(self.kdf.currentData() == 'pbkdf2'))
                self.kdf_iterations.setEnabled(False)
        self.key_file = None
        if self.is_archive:
            self.key_file = KeyFilePicker(self, allow_generate=self.setup, allow_clear=True)
            label = self.tr('Key file (required)') if key_required else self.tr('Key file (optional)')
            layout.addRow(QLabel(label))
            layout.addRow(self.key_file)
            if self.setup or key_required:
                warning = QLabel(self.tr('If you lose a required key file, you cannot unlock the database.'))
                warning.setWordWrap(True)
                layout.addRow(warning)
        self.show_password = QCheckBox(self.tr('Show password'))
        self.show_password.toggled.connect(self.toggle_password)
        layout.addRow(self.show_password)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setMinimumHeight(self.error.fontMetrics().lineSpacing() * 3 + 4)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error.setAccessibleName(self.tr('Unlock error'))
        layout.addRow(self.error)
        if not self.setup:
            self.restore_button = QPushButton(action_icon(self, 'Copy'), self.tr('Restore encrypted backup…'))
            self.restore_button.setToolTip(
                self.tr('Verify a backup with the password and any key file used when it was created.')
                if self.is_archive else self.tr('Verify a backup using its master password and save it as a separate database.'))
            self.restore_button.clicked.connect(self.restore)
            layout.addRow(self.restore_button)
        self.buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(self.buttons)
        submit = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        submit.setText(self.tr('Create database') if self.setup else self.tr('Unlock database'))
        submit.setProperty('unircmText', 'Create database' if self.setup else 'Unlock database')
        submit.setToolTip(self.tr('Create a database protected by a master password.') if self.setup else
                          self.tr('Unlock the database with its password and key file.') if key_required else
                          self.tr('Unlock the database with its master password.'))
        submit.setIcon(action_icon(self, 'Unlock selected'))
        submit.setProperty('primary', True)
        submit.setDefault(False)
        # Explicit Return handling also works when embedded in QMainWindow.
        for button in self.buttons.buttons():
            button.setAutoDefault(False)
        layout.addRow(self.buttons)
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.cancelled.emit)
        self.password.returnPressed.connect(self.submit)
        self.confirmation.returnPressed.connect(self.submit)

    def update_password_strength(self, password):
        distinct = len({char for char in password.casefold()
                        if char.isprintable() and not char.isspace()})
        length = len(password.strip())
        categories = set()
        for char in password:
            if char.islower():
                categories.add('lower')
            elif char.isupper():
                categories.add('upper')
            elif char.isdigit():
                categories.add('digit')
            elif not char.isalnum() and not char.isspace():
                categories.add('symbol')

        if not password:
            level, label, color = 0, '', 'transparent'
        elif distinct >= 10 and (length >= 20 or (length >= 14 and len(categories) >= 3)):
            level, label, color = 3, self.tr('Strong'), '#238636'
        elif length >= 10 and distinct >= 6:
            level, label, color = 2, self.tr('Medium'), '#d4a000'
        else:
            level, label, color = 1, self.tr('Weak'), '#c9363e'
        self.password_strength.setValue(level)
        self.password_strength.setStyleSheet(
            'QProgressBar { background: palette(midlight); border: 1px solid palette(mid); border-radius: 3px; }'
            f' QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}'
        )
        self.strength_label.setText(label)

    def toggle_password(self, visible):
        for field in (self.password, self.confirmation):
            field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)

    def clear(self):
        self.password.clear()
        self.confirmation.clear()
        if self.key_file:
            self.key_file.clear()
        self.show_password.setChecked(False)
        self.error.clear()

    def restore(self):
        if not self.password.text():
            self.error.setText(self.tr('Enter the master password used when the backup was created.'))
            self.password.setFocus()
            return
        suffix = self.path.suffix
        backups = sorted(self.path.parent.glob(f'{escape(self.path.name)}.backup-*{suffix}'), reverse=True)
        start = str(backups[0] if backups else self.path.parent)
        file_filter = self.tr('Encrypted database (*%1)').replace('%1', suffix)
        source, _ = QFileDialog.getOpenFileName(self, self.tr('Select encrypted backup'), start, file_filter)
        if not source:
            return
        suggested = self.path.with_name(f'{self.path.stem}-restored{suffix}')
        destination, _ = QFileDialog.getSaveFileName(
            self, self.tr('Save restored database'), str(suggested), file_filter,
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not destination:
            return
        path = Path(destination)
        if path.suffix.lower() != suffix.lower():
            path = Path(str(path) + suffix)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            restore_backup(source, path, self.password.text(), is_archive=self.is_archive,
                           key_file=self.key_file.path if self.key_file else None)
        except FileExistsError:
            self.error.setText(self.tr('Choose a new filename. Existing databases cannot be overwritten.'))
        except UnsupportedSchemaVersion:
            self.error.setText(self.tr('This backup requires a newer version of UniRCm.'))
        except KeyFileError as error:
            self.error.setText(self.tr(str(error)))
        except Exception:
            self.error.setText(self.tr('Unable to restore the backup. Check its master password, key file and file access.')
                               if self.is_archive else self.tr('Unable to restore the backup. Check its master password and file access.'))
        else:
            self.clear()
            self.error.setText(self.tr('Backup restored. Open the new database at %1.').replace('%1', str(path)))
        finally:
            QApplication.restoreOverrideCursor()

    def submit(self):
        if not self.password.text():
            self.error.setText(self.tr('Enter a master password.'))
            return
        if self.setup and self.password.text() != self.confirmation.text():
            self.error.setText(self.tr('Passwords do not match.'))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self.is_archive:
                options = {}
                if self.setup and self.kdf.currentData() == 'pbkdf2':
                    options['kdf_iterations'] = self.kdf_iterations.value()
                vault = ArchiveVault(self.path, self.password.text(), self.description,
                                     key_file=self.key_file.path, **options)
            else:
                vault = Vault(self.path, self.password.text())
                if self.setup:
                    vault.close()
                    vault = Vault(self.path, self.password.text())
        except Exception as error:
            if isinstance(error, RecoveryConflict):
                self.error.setText(self.tr('The archive has changed. Its encrypted working copy was preserved.'))
            elif isinstance(error, ArchiveInUse):
                self.error.setText(self.tr('This database is already open. Close it before trying again.'))
            elif isinstance(error, KeyFileError):
                self.error.setText(self.tr(str(error)))
            elif isinstance(error, BackupError):
                self.error.setText(self.tr('Unable to create a verified encrypted backup. Check disk space and database access.'))
            elif isinstance(error, UnsupportedSchemaVersion):
                self.error.setText(self.tr('This database requires a compatible version of UniRCm. Open it with the version that last saved it or a newer version.'))
            else:
                self.error.setText(self.tr('Unable to unlock database. Check the password, key file and database access.')
                                   if self.key_file_required else self.tr('Unable to unlock database. Check the password and database access.'))
            self.password.selectAll()
            self.password.setFocus()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.clear()
        self.unlocked.emit(vault)


def unlock_vault(path, parent=None, description=None):
    dialog = QDialog(parent)
    panel = VaultUnlockPanel(path, dialog, description)
    dialog.setWindowTitle(dialog.tr('Set master password') if panel.setup else dialog.tr('Unlock database'))
    layout = QVBoxLayout(dialog)
    layout.addWidget(brand_header(dialog, dialog.tr('Your remote connections, securely organized.')))
    layout.addWidget(panel)
    result = []

    def unlocked(vault):
        result.append(vault)
        dialog.accept()

    panel.unlocked.connect(unlocked)
    panel.cancelled.connect(dialog.reject)
    panel.password.setFocus()
    dialog.exec()
    panel.clear()
    return result[0] if result else None


def folder_combo(folders, selected=None):
    combo = QComboBox()
    combo.addItem(QCoreApplication.translate('Groups', 'No group (root)'), None)
    by_id = {folder['id']: folder for folder in folders}
    choices = []
    for folder in folders:
        names = [folder['name']]
        ancestor = folder['parent_id']
        while ancestor is not None:
            names.append(by_id[ancestor]['name'])
            ancestor = by_id[ancestor]['parent_id']
        choices.append((' / '.join(reversed(names)), folder['id']))
    for label, folder_id in sorted(choices):
        combo.addItem(label, folder_id)
    combo.setCurrentIndex(max(0, combo.findData(selected)))
    return combo


def make_tabs_scrollable(tabs):
    """Keep tab pages stable while allowing their forms to exceed the viewport."""
    tabs.setUsesScrollButtons(True)
    for index in range(tabs.count()):
        page = tabs.widget(index)
        content = QWidget()
        content.setLayout(page.layout())
        content.layout().setContentsMargins(16, 16, 16, 16)
        content.layout().setSpacing(10)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        wrapper = QVBoxLayout(page)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(scroll)


class LocalTerminalProfileDialog(QDialog):
    def __init__(self, profile, save_profile, parent=None):
        super().__init__(parent)
        self.save_profile = save_profile
        self.setWindowTitle(self.tr('Local terminal profile'))
        self.resize(520, 330)
        form = QFormLayout(self)
        self.name = QLineEdit(profile.get('name', ''))
        self.directory = QLineEdit(profile.get('directory', ''))
        self.directory.setPlaceholderText('~')
        self.commands = QPlainTextEdit(profile.get('commands', ''))
        self.commands.setPlaceholderText(self.tr('Commands to run in the interactive shell when opened'))
        form.addRow(self.tr('Name'), self.name)
        form.addRow(self.tr('Working directory'), self.directory)
        form.addRow(self.tr('Startup commands'), self.commands)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self):
        try:
            self.save_profile(self.name.text(), self.directory.text(), self.commands.toPlainText())
        except ValueError as error:
            self.error.setText(self.tr(str(error)))
            return
        except Exception:
            self.error.setText(self.tr('Unable to save the local terminal profile.'))
            return
        super().accept()


class ProfileDialog(QDialog):
    def __init__(self, profile=None, parent=None, folders=(), folder_id=None, save_callback=None):
        super().__init__(parent)
        self.profile = dict(profile or {})
        self.folders = folders
        self.save_callback = save_callback
        self.setWindowTitle(self.tr('Edit connection') if profile else self.tr('New connection'))
        self.resize(760, 660)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        general = QWidget()
        form = QFormLayout(general)
        self.general_form = form
        self.tabs.addTab(general, self.tr('General'))
        self.fields = {}
        for key in ('name', 'host'):
            self.fields[key] = QLineEdit(self.profile.get(key, ''))
        section(form, 'Connection details')
        form.addRow(icon_label(self, self.tr('Connection name'), 'file-code', self.fields['name']),
                    validated_field(self, self.fields['name']))
        self.folder = folder_combo(folders, self.profile.get('folder_id', folder_id))
        form.addRow(icon_label(self, self.tr('Group'), 'folder', self.folder), self.folder)
        self._ssh_port = self.profile.get('port', 22)
        self.protocol = QComboBox()
        self.protocol.addItem('SSH', 'ssh')
        self.protocol.addItem('RDP — embedded desktop', 'rdp')
        self.protocol.addItem(self.tr('VNC — embedded desktop'), 'vnc')
        self.protocol.addItem('Telnet — unencrypted', 'telnet')
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(self.profile.get('protocol', 'ssh'))))
        self.connect_at_startup = QCheckBox(self.tr('Connect at startup'))
        self.connect_at_startup.setIcon(connection_icon('terminal', self.palette()))
        self.connect_at_startup.setChecked(bool(self.profile.get('connect_at_startup', False)))
        self.connect_at_startup.setToolTip(self.tr('Open this connection automatically after unlocking the database at application startup.'))
        section(form, 'Destination')
        form.addRow(icon_label(self, self.tr('Protocol'), 'network', self.protocol), self.protocol)
        form.addRow(icon_label(self, self.tr('Hostname / SSH alias'), 'server', self.fields['host']),
                    validated_field(self, self.fields['host']))
        self.desktop_port = QSpinBox()
        self.desktop_port.setRange(1, 65535)
        self.desktop_port.setValue(self.profile.get('port', 3389))
        self.port = self.desktop_port
        self.port_row = QWidget()
        port_layout = QHBoxLayout(self.port_row)
        port_layout.setContentsMargins(0, 0, 0, 0)
        port_layout.addWidget(self.port)
        form.addRow(icon_label(self, self.tr('Port'), 'plug', self.port), self.port_row)
        self.desktop_port.setToolTip(self.tr('Connection port. Editing the SSH port overrides the inherited group value.'))
        self._protocol_ports = dict(ssh=22, rdp=3389, vnc=5900, telnet=23)
        self._protocol_ports[self.profile.get('protocol', 'ssh')] = self.profile.get('port', 22)
        self._port_protocol = None
        ssh = QWidget()
        ssh_form = QFormLayout(ssh)
        self.tabs.addTab(ssh, self.tr('SSH'))
        self.credentials = CredentialsEditor(self.profile, self)
        self.finished.connect(self.credentials.hide_secrets)
        form.addRow(self.connect_at_startup)
        saved_delay = self.profile.get('ssh_reconnect_delay', 0)
        self.auto_reconnect = QCheckBox(self.tr('Reconnect after SSH connection loss'))
        self.auto_reconnect.setIcon(action_icon(self, 'Reconnect'))
        self.auto_reconnect.setToolTip(self.tr('Retry after an established SSH session loses its connection.'))
        self.auto_reconnect.setChecked(saved_delay > 0)
        self.reconnect_delay = QSpinBox()
        self.reconnect_delay.setRange(1, MAX_SSH_RECONNECT_DELAY)
        self.reconnect_delay.setSuffix(self.tr(' s'))
        self.reconnect_delay.setValue(saved_delay or 5)
        self.reconnect_delay.setEnabled(self.auto_reconnect.isChecked())
        self.reconnect_delay.setToolTip(self.tr('Time to wait before trying to reconnect.'))
        self.auto_reconnect.toggled.connect(self.reconnect_delay.setEnabled)
        form.addRow(self.auto_reconnect)
        form.addRow(icon_label(self, self.tr('Reconnect delay'), 'gauge', self.reconnect_delay), self.reconnect_delay)
        section(form, 'Authentication')
        form.addRow(self.credentials)
        self.rdp_domain = QLineEdit(self.profile.get('rdp_domain', ''))
        self.rdp_domain.setMaxLength(255)
        self.rdp_domain.setToolTip(self.tr('Windows domain or server name for RDP authentication. Leave empty to use a domain prefix already present in the username.'))
        form.addRow(self.tr('Domain'), self.rdp_domain)
        self.credential_selector = CredentialSelector(getattr(parent, 'vault', None), self.profile.get('credential_source', 'local'), self.profile.get('credential_id'), parent=self)
        form.insertRow(form.getWidgetPosition(self.credentials)[0], self.credential_selector)
        self.credential_selector.source_changed.connect(self.update_effective_values)
        self.fields['username'] = self.credentials.username
        self.identity = QLineEdit(self.profile.get('identity_file', ''))
        self.imported_key_name = self.profile.get('imported_key_name')
        self.imported_key_change = None
        self.finished.connect(self.clear_imported_key_change)
        self.browse_identity = QPushButton(action_icon(self, 'Open file…'), self.tr('Browse…'))
        self.browse_identity.setToolTip(self.tr('Use a private key from its file path.'))
        self.browse_identity.clicked.connect(self.browse)
        import_key = QPushButton(action_icon(self, 'Download file'), self.tr('Import key…'))
        import_key.setToolTip(self.tr('Copy an OpenSSH private key into the encrypted database when you save.'))
        import_key.clicked.connect(self.import_key)
        self.remove_imported_key = QPushButton(action_icon(self, 'Delete'), self.tr('Remove imported key'))
        self.remove_imported_key.setToolTip(self.tr('Remove this connection’s imported key from the database when you save.'))
        self.remove_imported_key.clicked.connect(self.remove_key)
        identity_row = QHBoxLayout()
        identity_row.addWidget(self.identity)
        identity_row.addWidget(self.browse_identity)
        identity_row.addWidget(import_key)
        identity_row.addWidget(self.remove_imported_key)
        self.update_identity_field()
        identity_widget = QWidget()
        identity_widget.setLayout(identity_row)
        hint = QLabel(self.tr('Uses the common credentials, OpenSSH config and agent. Leave the password empty for interactive authentication. Host keys are verified by OpenSSH.'))
        hint.setWordWrap(True)
        ssh_form.addRow(hint)
        self.connect_timeout = QSpinBox()
        self.connect_timeout.setRange(1, 600)
        self.connect_timeout.setSuffix(self.tr(' s'))
        self.connect_timeout.setValue(self.profile.get('connect_timeout', 15))
        self.connect_timeout.setToolTip(self.tr('Limits connection establishment and the initial SSH handshake. Does not limit session duration.'))

        self.ssh_modes = {}
        self.effective_labels = {}
        for key, label, field in [('port', 'Port source', self.port),
                                  ('username', 'Username source', self.fields['username']),
                                  ('identity_file', 'Private key source', self.identity),
                                  ('connect_timeout', 'Timeout source', self.connect_timeout)]:
            selected = self.profile.get('ssh_modes', {}).get(key, 'override' if profile else 'inherit')
            if key == 'username':
                mode = UsernameSource(selected)
                changed = mode.changed
            else:
                mode = source_combo(selected)
                changed = mode.currentIndexChanged
            if key == 'port':
                self.ssh_modes[key] = mode
                mode.setToolTip(self.tr('Port source'))
                self.port_row.layout().addWidget(mode, 1)
                changed.connect(self.update_effective_values)
                continue
            changed.connect(lambda *_args, m=mode, f=field: f.setEnabled(m.currentData() == 'override'))
            field.setEnabled(mode.currentData() == 'override')
            self.ssh_modes[key] = mode
            value_widget = identity_widget if key == 'identity_file' else field
            row, note = inheritance_row(mode, value_widget, stacked=key == 'username')
            if key == 'username':
                self.username_row = row
                self.credentials.form.insertRow(0, icon_label(self, self.tr('Username'), 'user', field), row)
            else:
                icon = 'key-round' if key == 'identity_file' else 'gauge'
                ssh_form.addRow(icon_label(self, self.tr(label.replace(' source', '')), icon, field), row)
            self.effective_labels[key] = (note, value_widget)
            changed.connect(self.update_effective_values)
        self.ssh_advanced = AdvancedSSHOptions(self.profile.get('ssh_advanced', {}), self)
        advanced_page = QWidget()
        self.advanced_page = advanced_page
        advanced_form = QFormLayout(advanced_page)
        advanced_mode = source_combo(self.profile.get('ssh_modes', {}).get('ssh_advanced', 'override' if profile else 'inherit'), self)
        row, note = inheritance_row(advanced_mode, self.ssh_advanced)
        section(advanced_form, 'SSH advanced')
        advanced_mode.setToolTip(self.tr('Advanced options source'))
        advanced_form.addRow(row)
        self.ssh_modes['ssh_advanced'] = advanced_mode
        self.effective_labels['ssh_advanced'] = (note, self.ssh_advanced)
        advanced_mode.currentIndexChanged.connect(lambda: self.ssh_advanced.setEnabled(advanced_mode.currentData() == 'override'))
        self.ssh_advanced.setEnabled(advanced_mode.currentData() == 'override')
        advanced_mode.currentIndexChanged.connect(self.update_effective_values)
        telnet = QWidget()
        telnet_form = QFormLayout(telnet)
        self.tabs.addTab(advanced_page, self.tr('SSH advanced'))
        self.telnet_page = telnet
        self.tabs.addTab(telnet, self.tr('Telnet'))
        self.rdp_options = RdpOptions(self.profile.get('rdp_options', {}), self)
        self.tabs.addTab(self.rdp_options, self.tr('RDP'))
        warning = QLabel(self.tr('Telnet is unencrypted: credentials and session data are sent in clear text. Stored credentials are sent only when an automatic login mode is explicitly selected.'))
        warning.setWordWrap(True)
        telnet_form.addRow(warning)
        self.telnet_timeout = QSpinBox()
        self.telnet_timeout.setRange(1, 600)
        self.telnet_timeout.setSuffix(self.tr(' s'))
        self.telnet_timeout.setValue(self.profile.get('connect_timeout', 15))
        options = self.profile.get('telnet_options', {})
        self.telnet_term = QLineEdit(options.get('term', 'xterm-256color'))
        self.telnet_encoding = QComboBox()
        for encoding in ('utf-8', 'latin-1', 'cp437', 'ascii'):
            self.telnet_encoding.addItem(encoding, encoding)
        self.telnet_encoding.setCurrentIndex(max(0, self.telnet_encoding.findData(options.get('encoding', 'utf-8'))))
        self.telnet_login = QComboBox()
        for label, value in [('Manual login — do not send stored credentials', 'manual'),
                             ('Send password only at password prompt', 'password'),
                             ('Send username and password at login prompts', 'username_password')]:
            self.telnet_login.addItem(self.tr(label), value)
        self.telnet_login.setCurrentIndex(max(0, self.telnet_login.findData(options.get('login_mode', 'manual'))))
        self.telnet_login.setToolTip(self.tr('Automatic login sends each stored field once at its configured prompt, or a recognized prompt when blank. Other prompts and retries require manual input. Credentials come from General, including group inheritance.'))
        self.telnet_username_prompt = QLineEdit(options.get('username_prompt', ''))
        self.telnet_password_prompt = QLineEdit(options.get('password_prompt', ''))
        self.telnet_username_prompt.setPlaceholderText(self.tr('Automatic (login:, username:)'))
        self.telnet_password_prompt.setPlaceholderText(self.tr('Automatic (password:)'))
        for field in (self.telnet_username_prompt, self.telnet_password_prompt):
            field.setMaxLength(256)
            field.setToolTip(self.tr('Literal text expected at the end of the prompt line, ignoring letter case. Leave blank for automatic detection. Not a regular expression.'))
        form.insertRow(form.getWidgetPosition(self.port_row)[0] + 1, self.tr('Login mode'), self.telnet_login)
        self.telnet_login.currentIndexChanged.connect(self.update_telnet_prompts)
        self.update_telnet_prompts()
        for label, field in [('Connection timeout', self.telnet_timeout), ('Terminal type', self.telnet_term), ('Encoding', self.telnet_encoding), ('Username prompt', self.telnet_username_prompt), ('Password prompt', self.telnet_password_prompt)]:
            telnet_form.addRow(self.tr(label), field)
        self.desktop_port.valueChanged.connect(self.update_general_port)
        self.protocol.currentIndexChanged.connect(self.update_protocol)
        self.update_protocol()
        appearance = QWidget()
        visual = QFormLayout(appearance)
        self.tabs.addTab(appearance, self.tr('Appearance'))
        self.icon = IconPicker(self.profile.get('icon', 'terminal'), parent=self)
        visual.addRow(self.tr('Connection icon'), self.icon)
        self.tab_color = self.profile.get('tab_color', '')
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.choose_color)
        reset = QPushButton(self.tr('Use default'))
        reset.clicked.connect(lambda: self.set_color(''))
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_button)
        color_row.addWidget(reset)
        color_widget = QWidget()
        color_widget.setLayout(color_row)
        self.set_color(self.tab_color)
        self.terminal_options = TerminalOptions(self.profile.get('terminal_options', {}), self, inheritance=True)
        terminal_page = self.terminal_page = QWidget()
        terminal_layout = QVBoxLayout(terminal_page)
        terminal_layout.addWidget(self.terminal_options)
        self.tabs.addTab(terminal_page, self.tr('Terminal'))
        self.appearance_modes = {}
        for key, label, field, target in [('tab_color', 'Tab color source', self.color_button, visual),
                                           ('terminal_options', 'Terminal appearance source', self.terminal_options, terminal_layout)]:
            mode = source_combo(self.profile.get('ssh_modes', {}).get(key, 'override' if profile else 'inherit'), self)
            mode.currentIndexChanged.connect(lambda _, m=mode, f=field: f.setEnabled(m.currentData() == 'override'))
            field.setEnabled(mode.currentData() == 'override')
            if key == 'tab_color':
                mode.currentIndexChanged.connect(lambda _, m=mode: reset.setEnabled(m.currentData() == 'override'))
                reset.setEnabled(mode.currentData() == 'override')
                row, note = inheritance_row(mode, color_widget)
                target.addRow(self.tr('Tab label color'), row)
                self.effective_labels[key] = (note, color_widget)
            else:
                note = QLabel()
                note.setWordWrap(True)
                target.insertWidget(0, mode)
                target.insertWidget(1, note)
                self.effective_labels[key] = (note, field)
            self.appearance_modes[key] = mode
            mode.currentIndexChanged.connect(self.update_effective_values)
        buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        primary_action(buttons, 'Save connection' if profile else 'Create connection')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.terminal_options.changed.connect(self.update_effective_values)
        self.folder.currentIndexChanged.connect(self.update_effective_values)
        self.update_effective_values()
        make_tabs_scrollable(self.tabs)
        polish_dialog(self)

    def update_telnet_prompts(self, *_):
        mode = self.telnet_login.currentData()
        self.telnet_username_prompt.setEnabled(mode == 'username_password')
        self.telnet_password_prompt.setEnabled(mode != 'manual')
        self.update_credential_controls()

    def update_protocol(self, *_):
        is_ssh = self.protocol.currentData() == 'ssh'
        protocol = self.protocol.currentData()
        if self._port_protocol is not None:
            self._protocol_ports[self._port_protocol] = self.desktop_port.value()
        self._port_protocol = protocol
        self.desktop_port.blockSignals(True)
        self.desktop_port.setValue(self._protocol_ports[protocol])
        self.desktop_port.blockSignals(False)
        self.desktop_port.setEnabled(protocol in ('ssh', 'rdp', 'vnc', 'telnet'))
        self.ssh_modes['port'].setVisible(is_ssh)
        if is_ssh:
            self.update_effective_values()
        self.tabs.setTabEnabled(1, is_ssh)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.telnet_page), self.protocol.currentData() == 'telnet')
        self.tabs.setTabEnabled(self.tabs.indexOf(self.advanced_page), is_ssh)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.rdp_options), protocol == 'rdp')
        self.update_credential_controls()

    def update_general_port(self, value):
        if self.protocol.currentData() == 'ssh':
            self._ssh_port = value
            mode = self.ssh_modes['port']
            mode.setCurrentIndex(mode.findData('override'))

    def sync_ssh_port(self, value):
        if self.protocol.currentData() == 'ssh':
            self.desktop_port.blockSignals(True)
            self.desktop_port.setValue(value)
            self.desktop_port.blockSignals(False)

    def update_effective_values(self, *_):
        if not hasattr(self, 'appearance_modes'):
            return
        self.credential_selector.inherited(self.folder.currentData(), self.folders)
        modes = dict(self.ssh_modes, **self.appearance_modes)
        effective = resolve_ssh(dict(self.profile, port=self._ssh_port, folder_id=self.folder.currentData(), terminal_options=self.terminal_options.options(), ssh_modes={key: mode.currentData() for key, mode in modes.items()}), self.folders)
        if self.protocol.currentData() == 'ssh':
            self.sync_ssh_port(effective['port'])
        self.terminal_options.set_effective_values(effective['terminal_options'])
        for key, (note, field) in self.effective_labels.items():
            mode = modes[key].currentData()
            field.setVisible(mode == 'override')
            note.setVisible(mode != 'override')
            note.setText(inherited_description(key, mode, self.folder.currentData(), self.folders))
        self.update_credential_controls()

    def update_credential_controls(self):
        if not hasattr(self, 'appearance_modes'):
            return
        protocol = self.protocol.currentData()
        source = self.credential_selector.selected_source()
        local = source == 'local'
        terminal = protocol in ('ssh', 'telnet')
        manual_telnet = protocol == 'telnet' and self.telnet_login.currentData() == 'manual'
        self.general_form.setRowVisible(self.rdp_domain, protocol == 'rdp')
        self.general_form.setRowVisible(self.telnet_login, protocol == 'telnet')
        self.credential_selector.setEnabled(not manual_telnet)
        self.credential_selector.setToolTip(self.tr('Manual Telnet login does not use stored credentials.') if manual_telnet else '')
        username_used = protocol != 'telnet' or self.telnet_login.currentData() == 'username_password'
        password_used = protocol in ('ssh', 'rdp') or (protocol == 'telnet' and self.telnet_login.currentData() != 'manual')
        self.general_form.setRowVisible(self.auto_reconnect, protocol == 'ssh')
        self.general_form.setRowVisible(self.reconnect_delay, protocol == 'ssh')
        self.general_form.setRowVisible(self.credentials, source in ('local', 'none'))
        if not (local and password_used):
            self.credentials.show_secrets.setChecked(False)
        if not (local and protocol == 'ssh'):
            self.credentials.show_key_passphrase.setChecked(False)
        self.credentials.form.setRowVisible(self.credentials.show_secrets, local and password_used)
        self.credentials.form.setRowVisible(self.credentials.show_key_passphrase, local and protocol == 'ssh')
        self.username_row.setEnabled(username_used)
        self.credentials.username.setEnabled(username_used and self.ssh_modes['username'].currentData() == 'override')
        self.credentials.password.setEnabled(local and password_used)
        self.credentials.form.setRowVisible(self.credentials.key_passphrase, protocol == 'ssh')
        self.credentials.key_passphrase.setEnabled(local and protocol == 'ssh')
        self.credentials.password.setToolTip(self.tr(
            'Stored only in the encrypted database. Leave empty to authenticate interactively or with a key/agent.'
            if password_used else 'Stored passwords are not sent in this mode. Enter the password in the remote client or terminal.'))
        if protocol == 'rdp':
            self.credentials.password.setToolTip(self.tr('Stored in the encrypted database and supplied directly to FreeRDP in memory. Leave empty to enter it when connecting.'))
        if protocol == 'telnet' and password_used:
            self.credentials.password.setToolTip(self.tr('Stored in the encrypted database and sent once at the Telnet password prompt. Telnet transmits it without encryption.'))
        username_note = self.effective_labels['username'][0]
        username_mode = self.ssh_modes['username'].currentData()
        description = inherited_description('username', username_mode, self.folder.currentData(), self.folders)
        if protocol != 'ssh':
            description = description.replace(self.tr('OpenSSH configuration / agent'), self.tr('No username configured'))
        username_note.setText(description)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.terminal_page), terminal)

    def set_color(self, color):
        self.tab_color = color
        self.color_button.setText(color or self.tr('Choose color…'))
        self.color_button.setStyleSheet(f'border: 3px solid {color};' if color else '')

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.tab_color) if self.tab_color else self.palette().windowText().color(), self, self.tr('Choose tab color'))
        if color.isValid():
            self.set_color(color.name())

    def browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, self.tr('Select private key'), str(Path.home() / '.ssh'))
        if filename:
            self.remove_key()
            self.identity.setText(filename)

    def import_key(self):
        filename, _ = QFileDialog.getOpenFileName(self, self.tr('Select private key'), str(Path.home() / '.ssh'))
        if not filename:
            return
        try:
            self.imported_key_change = read_imported_key(filename)
        except (ValueError, OSError) as error:
            message = str(error) if isinstance(error, ValueError) else 'Unable to open an anonymous file for the SSH key.'
            self.error.setText(self.tr(message))
            return
        self.error.clear()
        self.imported_key_name = self.imported_key_change[0]
        self.identity.clear()
        self.update_identity_field()

    def remove_key(self):
        if self.imported_key_name is not None:
            self.imported_key_name = None
            self.imported_key_change = False
            self.identity.clear()
            self.update_identity_field()

    def clear_imported_key_change(self, *_):
        self.imported_key_change = None

    def update_identity_field(self):
        imported = self.imported_key_name is not None
        self.identity.setReadOnly(imported)
        if imported:
            self.identity.setText(self.tr('Imported: %1').replace('%1', self.imported_key_name))
        self.browse_identity.setVisible(not imported)
        self.remove_imported_key.setVisible(imported)

    def save(self):
        self.error.clear()
        if not require_fields(self, [(self.fields['name'], 'Enter a connection name.'),
                                     (self.fields['host'], 'Enter a hostname or SSH alias.')]):
            return
        profile = {key: field.text().strip() for key, field in self.fields.items()}
        profile.update(self.credentials.values())
        profile['rdp_options'] = self.rdp_options.options()
        profile['rdp_domain'] = self.rdp_domain.text().strip()
        profile['connect_at_startup'] = self.connect_at_startup.isChecked()
        profile['ssh_reconnect_delay'] = (
            self.reconnect_delay.value() if self.protocol.currentData() == 'ssh' and self.auto_reconnect.isChecked() else 0
        )
        profile['ssh_advanced'] = self.ssh_advanced.options()
        profile['credential_id'] = self.profile.get('credential_id')
        profile.update(connect_timeout=self.connect_timeout.value(), id=self.profile.get('id'), port=self._ssh_port, identity_file=self.identity.text().strip(), folder_id=self.folder.currentData(), protocol=self.protocol.currentData(), icon=self.icon.selected_icon(), tab_color=self.tab_color, terminal_options=self.terminal_options.options())
        if self.imported_key_name is not None:
            profile['identity_file'] = ''
        if self.imported_key_change is not None:
            profile['imported_key'] = self.imported_key_change or None
        try:
            profile['credential_source'], reference = self.credential_selector.values()
            profile['credential_id'] = reference if profile['credential_source'] != 'local' else self.profile.get('credential_id')
            if not profile['name']:
                raise ValueError('Enter a connection name.')
            profile['ssh_modes'] = {key: mode.currentData() for key, mode in self.ssh_modes.items()}
            profile['ssh_modes'].update({key: mode.currentData() for key, mode in self.appearance_modes.items()})
            profile['telnet_options'] = dict(term=self.telnet_term.text().strip(), encoding=self.telnet_encoding.currentData(), login_mode=self.telnet_login.currentData(), username_prompt=self.telnet_username_prompt.text().strip(), password_prompt=self.telnet_password_prompt.text().strip())
            if profile['protocol'] == 'telnet':
                from remote_manager.terminal.telnet import validate_profile
                profile.update(port=self.port.value(), connect_timeout=self.telnet_timeout.value())
                profile['ssh_modes'].update(port='override', connect_timeout='override')
                validate_profile(profile)
            elif profile['protocol'] in ('rdp', 'vnc'):
                from remote_manager.protocols.validation import validate_profile
                profile['port'] = self.desktop_port.value()
                profile['ssh_modes']['port'] = 'override'
                validate_profile(profile)
            else:
                ssh_command(resolve_ssh(profile, self.folders))
            if self.save_callback:
                profile['id'] = self.save_callback(profile)
                profile.pop('imported_key', None)
                profile['imported_key_name'] = self.imported_key_name
        except Exception as error:
            self.error.setText(self.tr(str(error)) if isinstance(error, ValueError) else self.tr('Unable to save connection to the encrypted database.'))
            return
        self.profile = profile
        self.accept()


class TerminalOptions(QWidget):
    changed = pyqtSignal()
    def __init__(self, options, parent=None, inheritance=False, profiles=True):
        super().__init__(parent)
        self.profile_choice = None
        vault_parent = parent
        while vault_parent is not None and not hasattr(vault_parent, 'vault'):
            vault_parent = vault_parent.parent()
        vault = getattr(vault_parent, 'vault', None)
        self.profile_vault = vault
        original_options = options
        if profiles and vault is not None:
            self.profile_choice = QComboBox(self)
            self.profile_choice.addItem(self.tr('Custom appearance'), '')
            for profile in vault.terminal_profiles():
                self.profile_choice.addItem(profile['name'], profile['id'])
            self.profile_choice.setCurrentIndex(max(0, self.profile_choice.findData(options.get('profile_id', ''))))
            options = vault.expand_terminal_options(options)
        options = {key: value for key, value in options.items() if value is not None and value != {'source': 'default'}}
        self.property_modes = {}
        self.property_notes = {}
        form = QFormLayout(self)
        if self.profile_choice is not None:
            form.addRow(self.tr('Terminal profile'), self.profile_choice)
            self.profile_choice.currentIndexChanged.connect(self.profile_changed)
        font = default_font()
        self.family = QFontComboBox()
        self.family.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self.family.setCurrentFont(QFont(options.get('font_family', font.family())))
        form.addRow(self.tr('Font'), self.family)
        self.size = QSpinBox()
        self.size.setRange(6, 72)
        self.size.setValue(options.get('font_size', max(6, font.pointSize())))
        form.addRow(self.tr('Font size (pt)'), self.size)
        self.colors = {}
        for key, label in [('background', 'Background'), ('foreground', 'Text'), ('cursor_color', 'Cursor color')]:
            button = QPushButton(options.get(key, DEFAULT_OPTIONS[key]))
            button.setIcon(action_icon(self, 'Edit'))
            self.colors[key] = button
            button.clicked.connect(lambda checked=False, b=button: self.choose_color(b))
            form.addRow(self.tr(label), button)
        self.shape = QComboBox()
        for label, value in [('Outline', 'outline'), ('Block', 'block'), ('Underline', 'underline'), ('Bar', 'bar')]:
            self.shape.addItem(self.tr(label), value)
        self.shape.setCurrentIndex(max(0, self.shape.findData(options.get('cursor_shape', DEFAULT_OPTIONS['cursor_shape']))))
        form.addRow(self.tr('Cursor shape'), self.shape)
        self.blink = QCheckBox(self.tr('Blink cursor'))
        self.blink.setChecked(options.get('cursor_blink', DEFAULT_OPTIONS['cursor_blink']))
        form.addRow(self.blink)
        if inheritance:
            fields = dict(font_family=self.family, font_size=self.size, cursor_shape=self.shape,
                          cursor_blink=self.blink, **self.colors)
            for key, field in fields.items():
                mode = source_combo('inherit' if key in original_options and original_options[key] is None else 'default' if original_options.get(key) == {'source': 'default'} else 'override', self)
                row = form.getWidgetPosition(field)[0]
                form.removeWidget(field)
                wrapper, note = inheritance_row(mode, field)
                form.setWidget(row, QFormLayout.ItemRole.FieldRole, wrapper)
                self.property_modes[key] = mode
                self.property_notes[key] = (note, field)
                mode.currentIndexChanged.connect(self.changed.emit)
        reset = QPushButton(action_icon(self, 'Edit'), self.tr('Restore defaults'))
        reset.clicked.connect(self.reset)
        form.addRow(reset)
        self.family.currentFontChanged.connect(self.changed.emit)
        self.size.valueChanged.connect(self.changed.emit)
        self.shape.currentIndexChanged.connect(self.changed.emit)
        self.blink.toggled.connect(self.changed.emit)
        if self.profile_choice is not None:
            self.profile_changed()

    def profile_changed(self, *_):
        selected = bool(self.profile_choice.currentData())
        if selected:
            values = self.profile_vault.expand_terminal_options({'profile_id': self.profile_choice.currentData()})
            widgets = (self.family, self.size, self.shape, self.blink)
            for widget in widgets:
                widget.blockSignals(True)
            self.family.setCurrentFont(QFont(values.get('font_family', default_font().family())))
            self.size.setValue(values.get('font_size', 12))
            self.shape.setCurrentIndex(self.shape.findData(values.get('cursor_shape', 'block')))
            self.blink.setChecked(values.get('cursor_blink', True))
            for key, button in self.colors.items():
                button.setText(values.get(key, DEFAULT_OPTIONS[key]))
            for widget in widgets:
                widget.blockSignals(False)
        for widget in (self.family, self.size, self.shape, self.blink, *self.colors.values(), *self.property_modes.values()):
            widget.setEnabled(not selected)
        self.changed.emit()

    def choose_color(self, button):
        color = QColorDialog.getColor(QColor(button.text()), self, self.tr('Choose terminal color'))
        if color.isValid():
            button.setText(color.name())
            self.changed.emit()

    def reset(self):
        if self.profile_choice is not None:
            self.profile_choice.setCurrentIndex(0)
        for mode in self.property_modes.values():
            mode.setCurrentIndex(mode.findData('override'))
        font = default_font()
        self.family.setCurrentFont(font)
        self.size.setValue(max(6, font.pointSize()))
        for key in self.colors:
            self.colors[key].setText(DEFAULT_OPTIONS[key])
        self.shape.setCurrentIndex(self.shape.findData(DEFAULT_OPTIONS['cursor_shape']))
        self.blink.setChecked(DEFAULT_OPTIONS['cursor_blink'])
        self.changed.emit()

    def options(self):
        if self.profile_choice is not None and self.profile_choice.currentData():
            return {'profile_id': self.profile_choice.currentData()}
        values = dict(font_family=self.family.currentFont().family(), font_size=self.size.value(),
                    cursor_shape=self.shape.currentData(), cursor_blink=self.blink.isChecked(),
                    **{key: button.text() for key, button in self.colors.items()})
        for key, mode in self.property_modes.items():
            if mode.currentData() == 'inherit':
                values[key] = None
            elif mode.currentData() == 'default':
                values[key] = {'source': 'default'}
        return values

    def set_effective_values(self, options):
        font = default_font()
        defaults = dict(DEFAULT_OPTIONS, font_family=font.family(), font_size=max(6, font.pointSize()))
        for key, (note, field) in self.property_notes.items():
            mode = self.property_modes[key].currentData()
            field.setVisible(mode == 'override')
            note.setVisible(mode != 'override')
            value = options.get(key, defaults[key])
            if isinstance(value, bool):
                value = self.tr('On') if value else self.tr('Off')
            note.setText(self.tr('Inherited value: %1').replace('%1', str(value)) if mode == 'inherit' else self.tr('Default value: %1').replace('%1', str(value)))


class GroupDefaultsDialog(QDialog):
    def __init__(self, folder, parent=None, folders=(), save_callback=None):
        super().__init__(parent)
        self.folders = folders
        self.save_callback = save_callback
        self.folder_id = folder.get('id')
        self.setWindowTitle(self.tr('Group properties') if self.folder_id else self.tr('New group'))
        self.resize(740, 620)
        layout = QVBoxLayout(self)
        tabs = self.tabs = QTabWidget()
        layout.addWidget(tabs)
        ssh_page = QWidget()
        form = QFormLayout(ssh_page)
        general = QWidget()
        general_form = QFormLayout(general)
        self.name = QLineEdit(folder['name'])
        self.parent_group = folder_combo(valid_parent_folders(folders, self.folder_id), folder.get('parent_id'))
        section(general_form, 'Group details')
        general_form.addRow(self.tr('Group name'), validated_field(self, self.name))
        general_form.addRow(self.tr('Parent group'), self.parent_group)
        tabs.addTab(general, self.tr('General'))
        tabs.addTab(ssh_page, self.tr('SSH'))
        self.fields = {}
        self.effective_labels = {}
        section(form, 'SSH defaults', 'Choose which settings connections inherit from this group.')
        settings = folder.get('ssh_defaults', {})
        self.credential_selector = CredentialSelector(getattr(parent, 'vault', None), 'inherit' if 'credential_id' not in settings else 'shared' if settings['credential_id'] else 'none', settings.get('credential_id'), group=True, parent=self)
        section(general_form, 'Authentication', 'Connections can inherit a shared credential from this group.')
        general_form.addRow(self.credential_selector)
        self.credential_selector.source_changed.connect(self.update_effective_values)
        for key, label, default in [('port', 'Port', 22), ('username', 'Username', ''), ('identity_file', 'Private key', ''), ('connect_timeout', 'Connection timeout (seconds)', 15)]:
            mode = QComboBox()
            for title, value in [('Inherit from parent', 'inherit'), ('Override', 'override'), ('Application default', 'default')]:
                mode.addItem(self.tr(title), value)
            mode.setCurrentIndex(mode.findData('inherit' if key not in settings else 'default' if settings[key] is None else 'override'))
            field = QSpinBox() if key in ('port', 'connect_timeout') else QLineEdit()
            value = settings.get(key)
            if key in ('port', 'connect_timeout'):
                field.setRange(1, 65535 if key == 'port' else 600)
                field.setValue(default if value is None else value)
            else:
                field.setText(default if value is None else value)
            mode.currentIndexChanged.connect(lambda _, m=mode, f=field: f.setEnabled(m.currentData() == 'override'))
            field.setEnabled(mode.currentData() == 'override')
            if key == 'identity_file':
                browse = QPushButton(self.tr('Browse…'))
                browse.clicked.connect(lambda _, f=field: browse_key(self, f))
                widget = QWidget()
                key_row = QHBoxLayout(widget)
                key_row.setContentsMargins(0, 0, 0, 0)
                key_row.addWidget(field)
                key_row.addWidget(browse)
            else:
                widget = field
            row, note = inheritance_row(mode, widget)
            form.addRow(self.tr(label), row)
            self.effective_labels[key] = (note, widget)
            self.fields[key] = (mode, field)
            mode.currentIndexChanged.connect(self.update_effective_values)
        form.addRow(QLabel(self.tr('Blank overrides use OpenSSH configuration/agent.')))
        advanced_page = QWidget()
        advanced_form = QFormLayout(advanced_page)
        tabs.addTab(advanced_page, self.tr('SSH advanced'))
        self.ssh_advanced = AdvancedSSHOptions(settings.get('ssh_advanced') or {}, self)
        mode = source_combo('inherit' if 'ssh_advanced' not in settings else 'default' if settings['ssh_advanced'] is None else 'override', self)
        mode.setItemText(mode.findData('inherit'), self.tr('Inherit from parent'))
        row, note = inheritance_row(mode, self.ssh_advanced)
        section(advanced_form, 'SSH advanced')
        mode.setToolTip(self.tr('Advanced options source'))
        advanced_form.addRow(row)
        self.fields['ssh_advanced'] = (mode, self.ssh_advanced)
        self.effective_labels['ssh_advanced'] = (note, self.ssh_advanced)
        mode.currentIndexChanged.connect(lambda _, m=mode: self.ssh_advanced.setEnabled(m.currentData() == 'override'))
        self.ssh_advanced.setEnabled(mode.currentData() == 'override')
        mode.currentIndexChanged.connect(self.update_effective_values)

        appearance_page = QWidget()
        appearance_form = QFormLayout(appearance_page)
        tabs.addTab(appearance_page, self.tr('Appearance'))
        appearance = folder.get('appearance', {})
        self.group_icon = IconPicker(appearance.get('icon', 'folder'), include_folder=True, parent=self)
        appearance_form.addRow(self.tr('Group icon'), self.group_icon)
        self.group_color = QLineEdit(appearance.get('color', ''))
        self.group_color.setPlaceholderText(self.tr('#RRGGBB (blank: default)'))
        self.group_color.setToolTip(self.tr('Color of this group name in the tree. Does not change connection or tab colors.'))
        color_widget = QWidget()
        color_row = QHBoxLayout(color_widget)
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.addWidget(self.group_color)
        choose = QPushButton(self.tr('Choose…'))
        choose.clicked.connect(lambda: choose_field_color(self, self.group_color))
        reset = QPushButton(self.tr('Use default'))
        reset.clicked.connect(self.group_color.clear)
        color_row.addWidget(choose)
        color_row.addWidget(reset)
        appearance_form.addRow(self.tr('Group name color'), color_widget)
        for key, label in [('tab_color', 'Tab label color'), ('terminal_options', 'Terminal appearance')]:
            mode = source_combo('inherit' if key not in settings else 'default' if settings[key] is None else 'override', self)
            mode.setItemText(mode.findData('inherit'), self.tr('Inherit from parent'))
            field = QLineEdit(settings.get(key) or '') if key == 'tab_color' else TerminalOptions(settings.get(key) or {}, self, inheritance=True)
            if key == 'tab_color':
                field.setPlaceholderText(self.tr('#RRGGBB (blank: default)'))
            mode.currentIndexChanged.connect(lambda _, m=mode, f=field: f.setEnabled(m.currentData() == 'override'))
            field.setEnabled(mode.currentData() == 'override')
            widget = field
            if key == 'tab_color':
                widget = QWidget()
                colors = QHBoxLayout(widget)
                colors.setContentsMargins(0, 0, 0, 0)
                colors.addWidget(field)
                choose = QPushButton(self.tr('Choose…'))
                choose.clicked.connect(lambda _, f=field: choose_field_color(self, f))
                colors.addWidget(choose)
            row, note = inheritance_row(mode, widget)
            appearance_form.addRow(self.tr(label), row)
            self.effective_labels[key] = (note, widget)
            mode.currentIndexChanged.connect(self.update_effective_values)
            self.fields[key] = (mode, field)
        layout.addWidget(QLabel(self.tr('Appearance changes also update open terminals. SSH changes apply to new sessions.')))
        buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        primary_action(buttons, 'Save group' if self.folder_id else 'Create group')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.fields['terminal_options'][1].changed.connect(self.update_effective_values)
        self.parent_group.currentIndexChanged.connect(self.update_effective_values)
        self.update_effective_values()
        make_tabs_scrollable(tabs)
        polish_dialog(self)

    def update_effective_values(self, *_):
        self.credential_selector.inherited(self.parent_group.currentData(), self.folders)
        mode, editor = self.fields['terminal_options']
        effective = resolve_ssh(dict(folder_id=self.parent_group.currentData(), terminal_options=editor.options(), ssh_modes={'terminal_options': mode.currentData()}), self.folders)
        editor.set_effective_values(effective['terminal_options'])
        for key, (note, widget) in self.effective_labels.items():
            mode = self.fields[key][0].currentData()
            widget.setVisible(mode == 'override')
            note.setVisible(mode != 'override')
            note.setText(inherited_description(key, mode, self.parent_group.currentData(), self.folders))

    def appearance(self):
        return dict(icon=self.group_icon.selected_icon(), color=self.group_color.text().strip())

    def save(self):
        self.error.clear()
        if not require_fields(self, [(self.name, 'Enter a group name.')]):
            return
        self.defaults = {}
        for key, (mode, field) in self.fields.items():
            if mode.currentData() == 'default':
                self.defaults[key] = None
            elif mode.currentData() == 'override':
                self.defaults[key] = field.options() if key in ('terminal_options', 'ssh_advanced') else field.value() if key in ('port', 'connect_timeout') else field.text().strip()
        try:
            source, reference = self.credential_selector.values()
            if source != 'inherit':
                self.defaults['credential_id'] = reference
            if not self.name.text().strip():
                raise ValueError('Enter a group name.')
            validate_ssh_settings(self.defaults)
            validate_group_appearance(self.appearance())
            if self.save_callback:
                self.folder_id = self.save_callback(self.name.text().strip(), self.parent_group.currentData(), self.defaults)
        except Exception as error:
            self.error.setText(self.tr(str(error)) if isinstance(error, ValueError) else self.tr('Unable to save group to the encrypted database.'))
            return
        self.accept()


class UsernameSource(QWidget):
    changed = pyqtSignal()

    def __init__(self, selected):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.options = {}
        for value, label, icon in (
            ('override', 'Use this username', 'user'),
            ('inherit', 'Inherit from group', 'folder'),
            ('default', 'Application default', 'terminal'),
        ):
            button = QRadioButton(self.tr(label))
            button.setIcon(connection_icon(icon, self.palette()))
            self.group.addButton(button)
            self.options[value] = button
            layout.addWidget(button)
        self.options.get(selected, self.options['inherit']).setChecked(True)
        self.group.buttonToggled.connect(self.selection_changed)

    def selection_changed(self, _button, checked):
        if checked:
            self.changed.emit()

    def currentData(self):
        return next(value for value, button in self.options.items() if button.isChecked())


def source_combo(selected, parent=None):
    combo = QComboBox(parent)
    for label, value in [('Override', 'override'), ('Inherit from group', 'inherit'), ('Application default', 'default')]:
        combo.addItem(combo.tr(label), value)
    combo.setCurrentIndex(combo.findData(selected))
    return combo


class TerminalAppearanceDialog(QDialog):
    def __init__(self, terminal, save_options, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr('Terminal appearance'))
        self.terminal = terminal
        self.original = dict(terminal.options)
        self.save_options = save_options
        layout = QVBoxLayout(self)
        self.editor = TerminalOptions(terminal.options, self)
        layout.addWidget(self.editor)
        layout.addWidget(QLabel(self.tr('Changes are previewed in the current session.')))
        buttons = NamedButtonBox(QDialogButtonBox.StandardButton.Cancel)
        decorate_buttons(buttons)
        self.apply_button = buttons.addButton(self.tr('Apply'), QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.clicked.connect(self.accept)
        if save_options is not None:
            self.save_button = buttons.addButton(self.tr('Save for this connection'), QDialogButtonBox.ButtonRole.ActionRole)
            self.save_button.clicked.connect(self.save)
        decorate_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.editor.changed.connect(self.preview)

    def preview(self):
        options = self.editor.options()
        vault = getattr(self.parent(), "vault", None)
        self.terminal.apply_options(vault.expand_terminal_options(options) if vault else options)

    def accept(self):
        self.preview()
        super().accept()

    def reject(self):
        self.terminal.apply_options(self.original)
        super().reject()

    def save(self):
        try:
            self.save_options(self.editor.options())
        except Exception:
            QMessageBox.warning(self, self.tr('Save failed'), self.tr('Unable to save terminal appearance to the encrypted database.'))
            return
        self.accept()


def inheritance_row(mode, field, *, stacked=False):
    widget = QWidget()
    note = QLabel()
    note.setWordWrap(True)
    note.setProperty('effectiveValue', True)
    compact = not stacked and (isinstance(field, (QLineEdit, QSpinBox)) or isinstance(field.layout(), QHBoxLayout))
    layout = QHBoxLayout(widget) if compact else QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(mode)
    layout.addWidget(field, 1 if compact else 0)
    layout.addWidget(note, 1 if compact else 0)
    return widget, note


def valid_parent_folders(folders, folder_id):
    if folder_id is None:
        return list(folders)
    excluded = {folder_id}
    while True:
        children = {f['id'] for f in folders if f['parent_id'] in excluded}
        if children <= excluded:
            return [f for f in folders if f['id'] not in excluded]
        excluded.update(children)


def inherited_description(key, mode, folder_id, folders):
    if mode == 'override':
        return ''
    tr = lambda text: QCoreApplication.translate('Inheritance', text)
    value = SSH_DEFAULTS[key]
    source = tr('Application default')
    by_id = {f['id']: f for f in folders}
    ancestor = folder_id if mode == 'inherit' else None
    while ancestor is not None:
        folder = by_id[ancestor]
        settings = folder.get('ssh_defaults', {})
        if key in settings:
            if settings[key] is not None:
                value = settings[key]
                names = [folder['name']]
                parent = folder['parent_id']
                while parent is not None:
                    names.insert(0, by_id[parent]['name'])
                    parent = by_id[parent]['parent_id']
                source = tr('Inherited from %1').replace('%1', ' / '.join(names))
            break
        ancestor = folder['parent_id']
    if key == 'terminal_options':
        value = resolve_ssh(dict(folder_id=folder_id, ssh_modes={'terminal_options': mode}), folders)['terminal_options']
        value = ', '.join(f'{tr(k.replace("_", " ").capitalize())}: {tr("On") if v is True else tr("Off") if v is False else v}' for k, v in value.items()) or tr('Default terminal appearance')
    elif key == 'ssh_advanced':
        from remote_manager.ssh_options import ADVANCED_DEFAULTS
        options = {**ADVANCED_DEFAULTS, **value}
        value = ', '.join(f'{k}: {len(v) if k == "forwards" else v}' for k, v in options.items() if v != '' and v != 'config' and v != [])
    elif key == 'connect_timeout':
        value = f'{value} s'
    elif value == '':
        value = tr('OpenSSH configuration / agent') if key in ('username', 'identity_file') else tr('Default color')
    return f'{value} — {source}'


def browse_key(parent, field):
    filename, _ = QFileDialog.getOpenFileName(parent, parent.tr('Select private key'), str(Path.home() / '.ssh'))
    if filename:
        field.setText(filename)


def choose_field_color(parent, field):
    color = QColorDialog.getColor(QColor(field.text()) if field.text() else parent.palette().windowText().color(), parent, parent.tr('Choose tab color'))
    if color.isValid():
        field.setText(color.name())
