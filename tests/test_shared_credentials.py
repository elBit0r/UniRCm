import pytest
from PyQt6.QtWidgets import QWidget, QDialog

from remote_manager.storage.vault import Vault
from remote_manager.storage.archive import ArchiveVault
from remote_manager.ui.dialogs import ProfileDialog, GroupDefaultsDialog


def profile(**values):
    return dict(dict(name='Host', host='localhost', port=22, username='', identity_file=''), **values)


def test_shared_credentials_inheritance_and_encrypted_archive(tmp_path):
    path = tmp_path / 'shared.uni'
    vault = ArchiveVault(path, 'master', description='Test')
    first = vault.save_credential('Team credential', 'team', 'shared-secret-marker')
    second = vault.save_credential('Other', 'other', 'other-secret-marker')
    root = vault.save_folder('Root', defaults={'credential_id': first})
    child = vault.save_folder('Child', root)
    inherited = vault.save(profile(folder_id=child, credential_source='inherit'))
    explicit = vault.save(profile(credential_source='shared', credential_id=first))
    saved = {p['id']: p for p in vault.profiles()}
    assert all(p['password'] == '' for p in saved.values())
    assert vault.effective_profile(saved[inherited])['password'] == 'shared-secret-marker'
    assert vault.effective_profile(saved[explicit])['username'] == 'team'
    with pytest.raises(ValueError, match='in use'):
        vault.delete_credential(first)
    vault.save_credential('Team renamed', 'renamed', 'updated-secret-marker', first)
    assert vault.effective_profile(saved[explicit])['username'] == 'renamed'
    vault.set_folder_defaults(child, {'credential_id': second})
    assert vault.effective_profile(saved[inherited])['username'] == 'other'
    vault.set_folder_defaults(child, {'credential_id': None})
    assert vault.effective_profile(saved[inherited])['password'] == ''
    vault.set_folder_defaults(child, {})
    vault.move_profile(inherited, None)
    saved = {p['id']: p for p in vault.profiles()}
    assert vault.effective_profile(saved[inherited])['password'] == ''
    vault.delete(explicit)
    assert vault.credential(first) is not None
    with pytest.raises(ValueError, match='in use'):
        vault.delete_credential(first)  # Still referenced by group.
    vault.delete_folder(root)
    vault.delete_credential(first)
    vault.close()
    for secret in (b'shared-secret-marker', b'updated-secret-marker', b'other-secret-marker', b'Team credential'):
        assert secret not in path.read_bytes()
    vault = ArchiveVault(path, 'master')
    assert vault.credential(second)['password'] == 'other-secret-marker'
    assert 'password' not in vault.shared_credentials()[0]
    vault.close()


def test_credential_selection_and_local_isolation(qtbot, tmp_path):
    vault = Vault(tmp_path / 'vault.db', 'master')
    shared = vault.save_credential('Shared', 'tester', 'secret')
    parent = QWidget()
    parent.vault = vault
    qtbot.addWidget(parent)
    group = GroupDefaultsDialog({'name': 'Group'}, parent, save_callback=vault.save_folder)
    # Group callback has different argument order; capture explicit defaults below.
    group.save_callback = lambda name, parent_id, defaults: vault.save_folder(name, parent_id, defaults=defaults)
    qtbot.addWidget(group)
    selector = group.credential_selector
    selector.source.setCurrentIndex(selector.source.findData('shared'))
    selector.reference.setCurrentIndex(selector.reference.findData(shared))
    group.save()
    assert group.result() == QDialog.DialogCode.Accepted
    dialog = ProfileDialog(parent=parent, folders=vault.folders(), folder_id=group.folder_id, save_callback=vault.save)
    qtbot.addWidget(dialog)
    dialog.fields['name'].setText('Inherited')
    dialog.fields['host'].setText('localhost')
    selector = dialog.credential_selector
    selector.source.setCurrentIndex(selector.source.findData('inherit'))
    assert 'Shared' in selector.note.text()
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = vault.profiles()[0]
    assert vault.effective_profile(saved)['password'] == 'secret'
    saved.update(credential_source='shared', credential_id=shared)
    vault.save(saved)
    saved = vault.profiles()[0]
    # Switching to a local credential must not change the shared record.
    saved.update(credential_source='local', password='local-only')
    vault.save(saved)
    assert vault.credential(shared)['password'] == 'secret'
    assert vault.profiles()[0]['credential_id'] != shared
    with pytest.raises(ValueError):
        vault.save(profile(credential_source='shared', credential_id='missing'))
    with pytest.raises(ValueError):
        vault.set_folder_defaults(group.folder_id, {'credential_id': 'missing'})
    vault.close()


def test_manager_create_edit_delete(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QLineEdit, QPushButton, QListWidget, QMessageBox
    from remote_manager.ui.credentials import CredentialManager, CredentialsEditor
    vault = Vault(tmp_path / 'manager.db', 'master')
    parent = QWidget()
    qtbot.addWidget(parent)
    stage = []

    def execute(dialog):
        if dialog.windowTitle() == 'Shared credentials':
            buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
            assert all(not b.icon().isNull() and b.toolTip() for b in buttons.values())
            buttons['New credential'].click()
            listing = dialog.findChild(QListWidget)
            assert listing.count() == 1
            listing.setCurrentRow(0)
            buttons['Edit'].click()
            assert vault.shared_credentials()[0]['username'] == 'updated'
            listing.setCurrentRow(0)
            buttons['Delete'].click()
            assert listing.count() == 0
        else:
            fields = dialog.findChild(CredentialsEditor)
            name = next(f for f in dialog.findChildren(QLineEdit) if f not in (fields.username, fields.password, fields.key_passphrase))
            name.setText('Managed credential')
            fields.username.setText('updated' if stage else 'initial')
            fields.password.setText('managed-secret')
            stage.append(dialog.windowTitle())
            next(b for b in dialog.findChildren(QPushButton) if b.text().replace('&', '') == 'Save').click()
            assert dialog.result() == QDialog.DialogCode.Accepted
        return dialog.result()

    monkeypatch.setattr(QDialog, 'exec', execute)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    CredentialManager.open(vault, parent)
    assert stage == ['New credential', 'Edit credential']
    assert vault.shared_credentials() == []
    vault.close()


def test_v7_upgrade_preserves_private_credentials(tmp_path):
    path = tmp_path / 'legacy.db'
    vault = Vault(path, 'master')
    vault.save(profile(username='legacy', password='legacy-secret'))
    # Restore the preceding schema, including a real encrypted credential.
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_domain')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_advanced')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN connect_at_startup')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN telnet_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN credential_source')
    vault.connection.execute('ALTER TABLE credentials DROP COLUMN key_passphrase')
    vault.connection.execute('ALTER TABLE credentials DROP COLUMN name')
    vault.connection.execute('DROP TABLE ssh_private_keys')
    vault.connection.execute('PRAGMA user_version = 7')
    vault.connection.commit()
    vault.close()
    vault = Vault(path, 'master')
    saved = vault.profiles()[0]
    assert saved['credential_source'] == 'local'
    assert vault.effective_profile(saved)['password'] == 'legacy-secret'
    assert vault.shared_credentials() == []
    vault.close()
