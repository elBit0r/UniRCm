import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

from remote_manager.storage.vault import Vault
from remote_manager.storage.archive import ArchiveVault
from remote_manager.ui.main_window import MainWindow

PROFILE = dict(name='Server', host='localhost', port=22, username='user', password='fake-password-marker', key_passphrase='fake-key-phrase', identity_file='')


def test_icon_bar_copy_cut_paste_and_system_clipboard(qtbot, tmp_path):
    vault = Vault(tmp_path / 'tools.db', 'master')
    first = vault.save_folder('First')
    second = vault.save_folder('Second')
    source = vault.save(dict(PROFILE, folder_id=first))
    window = MainWindow(vault, tmp_path / 'tools.db')
    qtbot.addWidget(window)
    window.show()
    assert list(window.tree_tool_buttons) == ['Add', 'Delete', 'Move up', 'Move down', 'Cut', 'Copy', 'Paste']
    assert window.tree_tools.mapTo(window, QPoint()).y() >= window.tree.mapTo(window, QPoint(0, window.tree.height())).y()
    for button in window.tree_tool_buttons.values():
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert not button.icon().isNull() and button.toolTip() and button.accessibleName()
    assert window.tree_tool_buttons['Add'].menu().actions() == [window.actions['New connection'], window.actions['New group']]
    QApplication.clipboard().setText('keep-system-clipboard')
    window.refresh(source)
    qtbot.mouseClick(window.tree_tool_buttons['Copy'], Qt.MouseButton.LeftButton)
    assert window._tree_clipboard == dict(mode='copy', kind='profile', id=source)
    window.refresh(selected_folder=second)
    assert not window.actions['Copy'].isEnabled()  # No group duplication.
    qtbot.mouseClick(window.tree_tool_buttons['Paste'], Qt.MouseButton.LeftButton)
    copied = window.selected()
    assert copied['name'] == 'Server (copy)' and copied['folder_id'] == second
    assert copied['credential_id'] != vault.profiles(source)[0]['credential_id']
    assert copied['password'] == PROFILE['password']
    assert QApplication.clipboard().text() == 'keep-system-clipboard'
    qtbot.mouseClick(window.tree_tool_buttons['Cut'], Qt.MouseButton.LeftButton)
    assert window.tree.currentItem().font(0).italic()
    window.refresh(selected_folder=first)
    qtbot.mouseClick(window.tree_tool_buttons['Paste'], Qt.MouseButton.LeftButton)
    assert window.selected()['id'] == copied['id'] and window.selected()['folder_id'] == first
    assert window._tree_clipboard is None
    assert not window.tree.currentItem().font(0).italic()
    from remote_manager.ui.language import set_language
    set_language('it')
    assert window.tree_tool_buttons['Copy'].accessibleName() == 'Copia'
    set_language('en')
    window.close()
    assert window._tree_clipboard is None
    assert b'fake-password-marker' not in (tmp_path / 'tools.db').read_bytes()


def test_cut_group_cycle_and_delete_source_clears_buffer(qtbot, tmp_path, monkeypatch):
    vault = Vault(tmp_path / 'group.db', 'master')
    root = vault.save_folder('Root')
    child = vault.save_folder('Child', root)
    other = vault.save_folder('Other')
    window = MainWindow(vault, tmp_path / 'group.db')
    qtbot.addWidget(window)
    window.show()
    window.refresh(selected_folder=root)
    window.actions['Cut'].trigger()
    assert not window.actions['Paste'].isEnabled()
    window.tree.setFocus()
    window.activateWindow()
    qtbot.waitUntil(window.tree.hasFocus)
    qtbot.keyClick(window.tree, Qt.Key.Key_Escape)
    assert window._tree_clipboard is None
    assert not window.tree.currentItem().font(0).italic()
    window.actions['Cut'].trigger()
    window.refresh(selected_folder=child)
    assert not window.actions['Paste'].isEnabled()
    window.refresh(selected_folder=other)
    window.actions['Paste'].trigger()
    assert next(folder for folder in vault.folders() if folder['id'] == root)['parent_id'] == other
    assert next(folder for folder in vault.folders() if folder['id'] == child)['parent_id'] == root
    assert window._tree_clipboard is None
    source = vault.save(PROFILE)
    window.refresh(source)
    window.actions['Copy'].trigger()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window.actions['Delete'].trigger()
    assert window._tree_clipboard is None and not window.actions['Paste'].isEnabled()
    window.close()


@pytest.mark.parametrize('mode', ['local', 'shared', 'inherit'])
def test_copy_profiles_atomic_credentials_and_archive_reopen(tmp_path, monkeypatch, mode):
    path = tmp_path / 'copy.uni'
    vault = ArchiveVault(path, 'master', description='Copy')
    shared = vault.save_credential('Shared', 'shared-user', 'shared-password', key_passphrase='shared-phrase')
    target = vault.save_folder('Target', defaults={'credential_id': shared})
    source = vault.save(dict(PROFILE, credential_source=mode, credential_id=shared if mode == 'shared' else None))
    copied = vault.copy_profile(source, target)
    original, copy = vault.profiles(source)[0], vault.profiles(copied)[0]
    if mode == 'local':
        assert original['credential_id'] != copy['credential_id']
        assert copy['password'] == PROFILE['password'] and copy['key_passphrase'] == PROFILE['key_passphrase']
    elif mode == 'shared':
        assert copy['credential_id'] == shared
    else:
        assert copy['credential_source'] == 'inherit'
        assert vault.effective_profile(copy)['password'] == 'shared-password'
    count = vault.connection.execute('SELECT count(*) FROM credentials').fetchone()[0]
    before = path.read_bytes()
    def fail(keys):
        raise OSError('Order write failed')
    with monkeypatch.context() as patch:
        patch.setattr(vault, '_write_tree_order', fail)
        with pytest.raises(OSError):
            vault.copy_profile(source, target)
    assert len(vault.profiles()) == 2
    assert vault.connection.execute('SELECT count(*) FROM credentials').fetchone()[0] == count
    assert path.read_bytes() == before
    vault.close()
    vault = ArchiveVault(path, 'master')
    assert vault.profiles(copied)[0]['folder_id'] == target
    vault.close()


def test_tree_clipboard_shortcuts_are_not_terminal_clipboard(qtbot, tmp_path, monkeypatch, local_pty_client):
    vault = Vault(tmp_path / 'shortcuts.db', 'master')
    source = vault.save(dict(PROFILE, password='', key_passphrase=''))
    window = MainWindow(vault, tmp_path / 'shortcuts.db')
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    window.refresh(source)
    window.tree.setFocus()
    qtbot.waitUntil(window.tree.hasFocus)
    qtbot.keyClick(window.tree, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert window._tree_clipboard['id'] == source
    window.open_profile(vault.profiles(source)[0])
    terminal = window.tabs.currentWidget()
    terminal.setFocus()
    qtbot.waitUntil(terminal.hasFocus)
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    qtbot.keyClick(terminal, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert sent == [b'\x03']  # Remote interrupt, not a tree copy action.
    terminal.stop()
    window.actions['Close tab'].trigger()
    window.close()


def test_tree_buffer_is_cleared_on_lock_and_database_switch(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    from remote_manager.ui.databases import DatabaseChooser
    import remote_manager.ui.main_window as main
    first, second = tmp_path / 'first.db', tmp_path / 'second.db'
    vault = Vault(first, 'master')
    source = vault.save(PROFILE)
    Vault(second, 'second').close()
    window = MainWindow(vault, first)
    qtbot.addWidget(window)
    window.show()
    window.refresh(source)
    window.actions['Copy'].trigger()
    assert window._tree_clipboard is not None
    window.lock_vault()
    assert window._tree_clipboard is None and not window.actions['Paste'].isEnabled()
    window.unlock_panel.password.setText('master')
    window.unlock_panel.submit()
    window.refresh(source)
    window.actions['Copy'].trigger()
    def choose(dialog):
        dialog.path, dialog.vault = second, Vault(second, 'second')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DatabaseChooser, 'exec', choose)
    window.switch_database()
    assert window._tree_clipboard is None and not window.actions['Paste'].isEnabled()
    window.close()
