import pytest
from sqlcipher3 import dbapi2 as sqlcipher
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QInputDialog, QLineEdit, QMessageBox

from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import GroupDefaultsDialog, ProfileDialog
from remote_manager.ui.main_window import MainWindow


PROFILE = dict(name='SSH', host='localhost', port=22, username='tester', identity_file='')


def test_encrypted_v1_migration_preserves_profiles(tmp_path):
    path = tmp_path / 'connections.db'
    connection = sqlcipher.connect(str(path))
    connection.set_key('master')
    connection.execute('''CREATE TABLE profiles (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL,
        port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
        username TEXT NOT NULL, identity_file TEXT NOT NULL DEFAULT '')''')
    connection.execute('INSERT INTO profiles VALUES(1,?,?,?,?,?)', tuple(PROFILE.values()))
    connection.execute('PRAGMA user_version = 1')
    connection.commit()
    connection.close()
    vault = Vault(path, 'master')
    assert vault.profiles() == [dict(PROFILE, rdp_options={}, rdp_domain='', ssh_advanced={}, connect_at_startup=0, key_passphrase='', telnet_options={}, credential_id=None, credential_source='local', password='', id=1, folder_id=None, protocol="ssh", icon="terminal", tab_color="", terminal_options={}, connect_timeout=15)]
    folder = vault.save_folder('private-folder-marker')
    vault.move_profile(1, folder)
    vault.close()
    assert b'private-folder-marker' not in path.read_bytes()
    vault = Vault(path, 'master')
    assert vault.connection.execute('PRAGMA user_version').fetchone()[0] == 17
    assert vault.profiles()[0]['folder_id'] == folder
    assert vault.folders()[0]['name'] == 'private-folder-marker'
    assert not vault.connection.execute('PRAGMA foreign_key_check').fetchall()
    vault.close()


def test_nested_folder_moves_and_safe_delete(tmp_path):
    path = tmp_path / 'connections.db'
    vault = Vault(path, 'master')
    root = vault.save_folder('Infrastructure')
    child = vault.save_folder('Linux', root)
    grandchild = vault.save_folder('Servers', child)
    profile = vault.save(dict(PROFILE, folder_id=child))
    for invalid_parent in (root, child, grandchild):
        with pytest.raises(ValueError):
            vault.save_folder('Infrastructure', invalid_parent, root)
    with pytest.raises(sqlcipher.IntegrityError):
        vault.move_profile(profile, 99999)
    with pytest.raises(sqlcipher.IntegrityError):
        vault.save_folder('Invalid', 99999)
    vault.save_folder('Unix', root, child)
    vault.delete_folder(child)
    assert vault.profiles()[0]['folder_id'] == root
    assert {f['id']: f for f in vault.folders()}[grandchild]['parent_id'] == root
    vault.save_folder('Servers', None, grandchild)
    vault.delete_folder(root)
    assert vault.profiles()[0]['folder_id'] is None
    assert vault.folders() == [dict(id=grandchild, name='Servers', parent_id=None)]
    vault.close()


def accept_dialog(fields=None, folder_id=None, button=QDialogButtonBox.StandardButton.Ok):
    dialog = QApplication.activeModalWidget()
    if fields:
        (dialog.name if isinstance(dialog, GroupDefaultsDialog) else dialog.findChild(QLineEdit)).setText(fields)
    combo = dialog.parent_group if isinstance(dialog, GroupDefaultsDialog) else dialog.findChild(QComboBox)
    if combo is not None:
        combo.setCurrentIndex(combo.findData(folder_id))
    dialog.findChild(QDialogButtonBox).button(button).click()


def test_folder_ui_create_rename_move_profiles_and_delete(qtbot, tmp_path, monkeypatch):
    path = tmp_path / 'connections.db'
    vault = Vault(path, 'master')
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    QTimer.singleShot(20, lambda: accept_dialog('Z Root', button=QDialogButtonBox.StandardButton.Save))
    window.new_folder()
    root = vault.folders()[0]['id']
    assert window.selected_folder_id() == root
    QTimer.singleShot(20, lambda: accept_dialog('A Child', root, QDialogButtonBox.StandardButton.Save))
    window.new_folder()
    child = next(f['id'] for f in vault.folders() if f['parent_id'] == root)
    assert window.selected_folder_id() == child
    assert window.tree.currentItem().parent().text(0) == 'Z Root'

    def rename():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GroupDefaultsDialog)
        dialog.name.setText('Renamed child')
        dialog.save()

    QTimer.singleShot(20, rename)
    window.edit_profile()
    assert window.tree.currentItem().text(0) == 'Renamed child'
    editor = ProfileDialog(PROFILE, window, vault.folders(), child)
    assert editor.folder.currentData() == child
    editor.save()
    profile = vault.save(editor.profile)
    window.refresh(profile)
    assert window.tree.currentItem().parent().text(0) == 'Renamed child'
    window.actions['Cut'].trigger()
    window.refresh(selected_folder=root)
    window.actions['Paste'].trigger()
    assert vault.profiles()[0]['folder_id'] == root
    assert window.tree.currentItem().parent().text(0) == 'Z Root'
    # The same handler services drag/drop requests; persist before rebuilding.
    folder = next(f for f in vault.folders() if f['id'] == child)
    window.tree.move_requested.emit(dict(folder, kind='folder'), None, None, False)
    assert next(f for f in vault.folders() if f['id'] == child)['parent_id'] is None
    window.refresh(selected_folder=root)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window.delete_profile()
    assert vault.profiles()[0]['folder_id'] is None
    assert window.tree.topLevelItemCount() == 2  # Child folder and preserved SSH.
    window.close()


def test_tree_context_menu_targets_clicked_connection(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu

    path = tmp_path / 'connections.db'
    vault = Vault(path, 'master')
    group = vault.save_folder('Servers')
    original = vault.save(dict(PROFILE, folder_id=group))
    other = vault.save(dict(PROFILE, name='Other'))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    window.refresh(original)
    clicked = window.tree.currentItem()
    position = window.tree.visualItemRect(clicked).center()
    window.refresh(other)
    edited = []
    monkeypatch.setattr(window, 'edit_profile', lambda: edited.append(window.selected()['id']))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    command = ['Edit']

    def execute(menu, point):
        actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
        if command[0] == 'empty':
            assert set(actions) == {'New', 'Paste', 'Order'}
            assert actions['New'].isEnabled()
            return
        assert set(actions) == {'New', 'Connect', 'Edit', 'Delete', 'Duplicate', 'Order', 'Cut', 'Copy', 'Paste'}
        assert window.selected()['id'] == original
        actions[command[0]].trigger()

    monkeypatch.setattr(QMenu, 'exec', execute)
    window.tree_context_menu(position)
    assert edited == [original]
    command[0] = 'Duplicate'
    window.tree_context_menu(position)
    copy = window.selected()
    assert copy == dict(PROFILE, rdp_options={}, rdp_domain='', ssh_advanced={}, connect_at_startup=0, key_passphrase='', telnet_options={}, credential_id=copy['credential_id'], credential_source='local', password='', id=copy['id'], name='SSH (copy)', folder_id=group, protocol='ssh', icon='terminal', tab_color='', terminal_options={}, connect_timeout=15)
    window.tree_context_menu(position)
    assert window.selected()['name'] == 'SSH (copy 2)'
    command[0] = 'Delete'
    window.tree_context_menu(position)
    assert original not in {p['id'] for p in vault.profiles()}
    assert other in {p['id'] for p in vault.profiles()}
    command[0] = 'empty'
    window.tree_context_menu(QPoint(window.tree.viewport().width() - 2, window.tree.viewport().height() - 2))
    assert window.selected_item() is None
    window.close()
    reopened = Vault(path, 'master')
    assert {'SSH (copy)', 'SSH (copy 2)'} <= {p['name'] for p in reopened.profiles()}
    reopened.close()
