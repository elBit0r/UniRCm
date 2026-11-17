from PyQt6.QtWidgets import QDialog, QMenu

from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import GroupDefaultsDialog, ProfileDialog
from remote_manager.ui.main_window import MainWindow

PROFILE = dict(name='Host', host='server.example', username='', identity_file='', port=22)


def test_effective_values_preserve_local_overrides(qtbot):
    folders = [dict(id=1, name='Servers', parent_id=None, ssh_defaults=dict(port=2222, username='admin')),
               dict(id=2, name='Other', parent_id=None, ssh_defaults=dict(port=2200))]
    dialog = ProfileDialog(dict(PROFILE, folder_id=1, port=2022, ssh_modes={'port': 'inherit', 'username': 'inherit'}), folders=folders)
    qtbot.addWidget(dialog)
    assert '2222' in dialog.effective_labels['port'][0].text()
    assert 'Servers' in dialog.effective_labels['port'][0].text()
    assert 'admin' in dialog.effective_labels['username'][0].text()
    dialog.folder.setCurrentIndex(dialog.folder.findData(2))
    assert '2200' in dialog.effective_labels['port'][0].text()
    dialog.ssh_modes['port'].setCurrentIndex(dialog.ssh_modes['port'].findData('override'))
    assert dialog.port.value() == 2022
    dialog.save()
    assert dialog.profile['port'] == 2022
    assert dialog.profile['ssh_modes']['port'] == 'override'


def test_tree_search_state_and_shared_actions(qtbot, tmp_path, monkeypatch):
    vault = Vault(tmp_path / 'vault.db', 'master')
    root = vault.save_folder('Servers', defaults={'username': 'administrator'})
    child = vault.save_folder('Linux', root)
    pid = vault.save(dict(PROFILE, folder_id=child, ssh_modes={'username': 'inherit'}))
    window = MainWindow(vault, tmp_path / 'vault.db')
    qtbot.addWidget(window)
    window.show()
    assert not window.actions['Connect'].isEnabled()
    window.refresh(selected_folder=root)
    item = window.tree.currentItem()
    assert window.actions['Edit'].text() == 'Group properties…'
    item.setExpanded(False)
    window.refresh()
    assert window.tree.currentItem().text(0) == 'Servers'
    assert not window.tree.currentItem().isExpanded()
    window.search.setText('ADMINISTRATOR')
    assert window.tree.topLevelItem(0).isExpanded()
    assert not next(i for i in window.tree_items() if i.text(0) == 'Host').isHidden()
    window.search.clear()
    assert not window.tree.topLevelItem(0).isExpanded()
    window.refresh(pid)
    assert window.actions['Connect'].isEnabled()
    assert window.tree.currentItem().parent().isExpanded()
    window.refresh()
    assert window.selected()['id'] == pid
    window.search.setText('absent')
    assert window.tree.topLevelItem(0).isHidden()
    assert not window.actions['Connect'].isEnabled()
    window.search.clear()
    assert window.selected()['id'] == pid
    window.refresh(selected_folder=child)
    menus = []
    monkeypatch.setattr(QMenu, 'exec', lambda menu, _: menus.append(menu))
    window.tree_context_menu(window.tree.visualItemRect(window.tree.currentItem()).center())
    actions = [a for a in menus[0].actions() if not a.isSeparator()]
    assert [a.text() for a in actions] == ['New', 'Group properties…', 'Cut', 'Copy', 'Paste', 'Delete', 'Order']
    assert actions[1] is window.actions['Edit']
    window.close()


def test_group_validation_and_failed_save_keep_editor_open(qtbot, tmp_path):
    vault = Vault(tmp_path / 'vault.db', 'master')
    root = vault.save_folder('Root')
    child = vault.save_folder('Child', root)
    folders = vault.folders()
    def save(name, parent_id, defaults):
        return vault.save_folder(name, parent_id, root, defaults=defaults)
    dialog = GroupDefaultsDialog(folders[1] if folders[1]['id'] == root else folders[0], folders=folders, save_callback=save)
    qtbot.addWidget(dialog)
    assert dialog.parent_group.findData(root) < 0
    assert dialog.parent_group.findData(child) < 0
    dialog.name.setText('')
    dialog.save()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error.text()
    dialog.name.setText('Renamed')
    mode, field = dialog.fields['connect_timeout']
    mode.setCurrentIndex(mode.findData('override'))
    field.setValue(30)
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = next(f for f in vault.folders() if f['id'] == root)
    assert saved['name'] == 'Renamed' and saved['ssh_defaults']['connect_timeout'] == 30
    profile = ProfileDialog(PROFILE, save_callback=lambda _: (_ for _ in ()).throw(OSError()))
    qtbot.addWidget(profile)
    profile.save()
    assert profile.result() != QDialog.DialogCode.Accepted
    assert profile.fields['host'].text() == 'server.example'
    assert profile.error.text()
    vault.close()


def test_reorder_and_reconnect_ended_session(qtbot, tmp_path, local_pty_client):
    vault = Vault(tmp_path / 'vault.db', 'master')
    pid = vault.save(PROFILE)
    window = MainWindow(vault, tmp_path / 'vault.db')
    qtbot.addWidget(window)
    try:
        window.refresh(pid)
        window.connect_profile()
        first = window.tabs.widget(0)
        window.connect_profile()
        second = window.tabs.widget(1)
        window.tabs.tabBar().moveTab(1, 0)
        assert window.tabs.widget(0) is second
        window.reconnect_terminal(second)
        assert window.tabs.count() == 2  # Running sessions are untouched.
        assert window.tabs.widget(0) is second
        second.stop()
        window.reconnect_terminal(second)
        assert window.tabs.count() == 2
        assert window.tabs.widget(1) is first
        replacement = window.tabs.currentWidget()
        assert window.tabs.widget(0) is replacement and replacement is not second
        assert replacement.is_running() and first.is_running()
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()
