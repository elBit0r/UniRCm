import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QDialog, QMenu

from remote_manager.storage.archive import ArchiveVault
from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import GroupDefaultsDialog
from remote_manager.ui.main_window import MainWindow

PROFILE = dict(name='Host', host='localhost', port=22, username='', identity_file='')


def keys(vault, parent=None):
    return [(entry['kind'], entry['id']) for entry in vault.tree_children(parent)]


def test_mixed_order_moves_validation_and_archive_reopen(tmp_path):
    path = tmp_path / 'order.uni'
    vault = ArchiveVault(path, 'master', description='Test')
    root = vault.save_folder('Root')
    subgroup = vault.save_folder('Z subgroup', root)
    first = vault.save(dict(PROFILE, name='A host', folder_id=root))
    second = vault.save(dict(PROFILE, name='B host', folder_id=root))
    assert keys(vault, root) == [('folder', subgroup), ('profile', first), ('profile', second)]
    vault.move_tree_item('profile', second, root, ('folder', subgroup))
    assert keys(vault, root) == [('profile', second), ('folder', subgroup), ('profile', first)]
    vault.move_tree_item('folder', subgroup, root, ('profile', first), after=True)
    assert keys(vault, root) == [('profile', second), ('profile', first), ('folder', subgroup)]
    before = keys(vault, root)
    for parent, anchor in [(subgroup, None), (root, ('profile', 9999))]:
        with pytest.raises(ValueError):
            vault.move_tree_item('folder', root, parent, anchor)
    assert keys(vault, root) == before
    vault.move_tree_item('profile', second, subgroup)
    assert keys(vault, subgroup) == [('profile', second)]
    vault.sort_tree_children(root)
    assert keys(vault, root) == [('folder', subgroup), ('profile', first)]
    vault.delete_folder(subgroup)
    assert keys(vault, root) == [('profile', second), ('profile', first)]
    vault.close()
    vault = ArchiveVault(path, 'master')
    assert keys(vault, root) == [('profile', second), ('profile', first)]
    vault.delete(second)
    assert ('profile', second) not in vault.tree_positions()
    vault.close()


def test_group_appearance_atomic_validation_and_editor(qtbot, tmp_path, monkeypatch):
    path = tmp_path / 'appearance.db'
    vault = Vault(path, 'master')
    group = vault.save_folder('Customer', appearance={'icon': 'router', 'color': '#3478ab'})
    with pytest.raises(ValueError):
        vault.save_folder('Changed', None, group, appearance={'icon': 'invalid', 'color': '#123456'})
    assert vault.folders()[0]['name'] == 'Customer'
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    window.refresh(selected_folder=group)
    assert window.tree.currentItem().foreground(0).color().name() == '#3478ab'
    def execute(dialog):
        assert dialog.group_icon.selected_icon() == 'router'
        assert dialog.group_color.text() == '#3478ab'
        dialog.group_icon.set_icon('database')
        dialog.group_color.setText('#12ab34')
        dialog.save()
        return dialog.result()
    monkeypatch.setattr(GroupDefaultsDialog, 'exec', execute)
    window.edit_profile()
    assert vault.folders()[0]['appearance'] == {'icon': 'database', 'color': '#12ab34'}
    assert window.tree.currentItem().foreground(0).color().name() == '#12ab34'
    window.close()
    assert b'#12ab34' not in path.read_bytes()
    vault = Vault(path, 'master')
    assert vault.folders()[0]['appearance']['icon'] == 'database'
    vault.save_folder('Customer', None, group, appearance={'icon': 'folder', 'color': ''})
    assert 'appearance' not in vault.folders()[0]
    vault.close()


def test_order_actions_and_view_state_restore(qtbot, tmp_path):
    path = tmp_path / 'view.db'
    vault = Vault(path, 'master')
    alpha = vault.save_folder('Alpha')
    beta = vault.save_folder('Beta')
    child = vault.save_folder('Child', alpha)
    host = vault.save(dict(PROFILE, folder_id=alpha))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    window.refresh(selected_folder=beta)
    window.actions['Move up'].trigger()
    assert [window.tree.topLevelItem(i).text(0) for i in range(2)] == ['Beta', 'Alpha']
    assert not window.actions['Move up'].isEnabled()
    assert window.actions['Move down'].isEnabled()
    window.search.setText('Alpha')
    assert not window.actions['Move down'].isEnabled()
    assert not window.tree.dragEnabled()
    window.search.clear()
    assert window.tree.dragEnabled()
    window.refresh(selected_folder=alpha)
    window.tree.currentItem().setExpanded(False)
    window.search.setText('Host')  # This temporarily expands Alpha.
    window.save_tree_state()
    assert alpha in vault.tree_view_state()['collapsed']
    window.close()
    vault = Vault(path, 'master')
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    assert window.tabs.count() == 0
    assert window.tree.currentItem().text(0) == 'Alpha'
    assert not window.tree.currentItem().isExpanded()
    assert window.tree.topLevelItem(0).text(0) == 'Beta'
    window.actions['Expand all groups'].trigger()
    assert all(item.isExpanded() for item in window.tree_items() if item.data(0, Qt.ItemDataRole.UserRole).get('kind') == 'folder')
    window.actions['Collapse all groups'].trigger()
    assert not window.tree.currentItem().isExpanded()
    window.close()


def test_schema11_adds_customization_without_changing_profiles(tmp_path):
    path = tmp_path / 'legacy.db'
    vault = Vault(path, 'master')
    vault.save(dict(PROFILE))
    profile = vault.profiles()[0]
    vault.connection.execute('DROP TABLE tree_order')
    vault.connection.execute('DROP TABLE folder_appearance')
    vault.connection.execute('DROP TABLE ssh_private_keys')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_domain')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_advanced')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN connect_at_startup')
    vault.connection.execute('PRAGMA user_version = 11')
    vault.connection.commit()
    vault.close()
    vault = Vault(path, 'master')
    assert vault.profiles()[0] == profile
    assert vault.tree_positions() == {}
    assert vault.connection.execute('PRAGMA user_version').fetchone()[0] == 17
    vault.close()


def test_drop_before_after_and_inside_group(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QAbstractItemView
    vault = Vault(tmp_path / 'drop.db', 'master')
    first = vault.save_folder('A')
    second = vault.save_folder('B')
    host = vault.save(dict(PROFILE))
    window = MainWindow(vault, tmp_path / 'drop.db')
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    def drop(source_key, target_key, position):
        source = next(item for item in window.tree_items() if window.item_key(item) == source_key)
        target = next(item for item in window.tree_items() if window.item_key(item) == target_key)
        window.tree.setCurrentItem(source)
        point = QPointF(window.tree.visualItemRect(target).center())
        class Event:
            ignored = False
            def source(self):
                return window.tree
            def position(self):
                return point
            def ignore(self):
                self.ignored = True
        monkeypatch.setattr(window.tree, 'dropIndicatorPosition', lambda: position)
        event = Event()
        window.tree.dropEvent(event)
        assert event.ignored  # The model must not repeat the persisted move.

    drop(('profile', host), ('folder', first), QAbstractItemView.DropIndicatorPosition.AboveItem)
    assert keys(vault) == [('profile', host), ('folder', first), ('folder', second)]
    drop(('folder', first), ('folder', second), QAbstractItemView.DropIndicatorPosition.BelowItem)
    assert keys(vault) == [('profile', host), ('folder', second), ('folder', first)]
    drop(('profile', host), ('folder', second), QAbstractItemView.DropIndicatorPosition.OnItem)
    assert keys(vault, second) == [('profile', host)]
    assert keys(vault) == [('folder', second), ('folder', first)]
    window.close()


def test_new_items_append_and_editing_parent_drops_old_rank(tmp_path):
    vault = Vault(tmp_path / 'append.db', 'master')
    group = vault.save_folder('Group')
    first = vault.save(dict(PROFILE, name='First'))
    second = vault.save(dict(PROFILE, name='Second'))
    vault.move_tree_item('profile', second, None, ('folder', group))
    third = vault.save(dict(PROFILE, name='Third'))
    assert keys(vault) == [('profile', second), ('folder', group), ('profile', first), ('profile', third)]
    saved = next(profile for profile in vault.profiles() if profile['id'] == second)
    saved['folder_id'] = group
    vault.save(saved)
    assert keys(vault, group) == [('profile', second)]
    assert ('profile', second) not in vault.tree_positions()
    vault.close()


def test_order_shortcuts_are_scoped_to_tree_and_sort_root(qtbot, tmp_path, monkeypatch):
    vault = Vault(tmp_path / 'shortcuts.db', 'master')
    first = vault.save_folder('Alpha')
    second = vault.save_folder('Beta')
    window = MainWindow(vault, tmp_path / 'shortcuts.db')
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    window.refresh(selected_folder=second)
    window.search.setFocus()
    qtbot.waitUntil(window.search.hasFocus)
    qtbot.keyClick(window.search, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert keys(vault) == [('folder', first), ('folder', second)]
    window.tree.setFocus()
    qtbot.waitUntil(window.tree.hasFocus)
    qtbot.keyClick(window.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert keys(vault) == [('folder', second), ('folder', first)]
    def execute(menu, _):
        order = next(action.menu() for action in menu.actions() if action.text() == 'Order')
        assert [action.text() for action in order.actions()] == ['Move up', 'Move down', 'Sort alphabetically', 'Expand all groups', 'Collapse all groups']
        order.actions()[2].trigger()
    monkeypatch.setattr(QMenu, 'exec', execute)
    window.tree_context_menu(QPoint(window.tree.viewport().width() - 2, window.tree.viewport().height() - 2))
    assert keys(vault) == [('folder', first), ('folder', second)]
    for title in ('Move up', 'Move down', 'Sort alphabetically', 'Expand all groups', 'Collapse all groups'):
        action = window.actions[title]
        assert action.text() and action.toolTip() and not action.icon().isNull()
    window.close()


def test_tree_state_is_isolated_between_databases(qtbot, tmp_path, monkeypatch):
    from remote_manager.ui.databases import DatabaseChooser
    first_path, second_path = tmp_path / 'first.db', tmp_path / 'second.db'
    first = Vault(first_path, 'master')
    first_group = first.save_folder('First group')
    first.save_tree_view_state([first_group], ('folder', first_group), 0)
    second = Vault(second_path, 'master')
    second_group = second.save_folder('Second group')
    second_child = second.save_folder('Second child', second_group)
    second.save_tree_view_state([], ('folder', second_child), 0)
    second.close()
    window = MainWindow(first, first_path)
    qtbot.addWidget(window)
    window.show()
    assert not window.tree.currentItem().isExpanded()
    def choose(dialog):
        path = second_path if dialog.excluded_path == first_path.resolve() else first_path
        dialog.path, dialog.vault = path, Vault(path, 'master')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DatabaseChooser, 'exec', choose)
    window.switch_database()
    assert window.tree.currentItem().text(0) == 'Second child'
    assert window.tree.currentItem().parent().isExpanded()
    window.switch_database()
    assert window.tree.currentItem().text(0) == 'First group'
    assert not window.tree.currentItem().isExpanded()
    assert window.tabs.count() == 0
    window.close()


def test_unicode_default_order_matches_reordering_view(qtbot, tmp_path):
    vault = Vault(tmp_path / 'unicode.db', 'master')
    for name in ('école', 'Écran', 'Zebra'):
        vault.save_folder(name)
    window = MainWindow(vault, tmp_path / 'unicode.db')
    qtbot.addWidget(window)
    window.show()
    assert [window.tree.topLevelItem(i).text(0) for i in range(3)] == [entry['name'] for entry in vault.tree_children(None)] == ['Zebra', 'école', 'Écran']
    window.tree.setCurrentItem(window.tree.topLevelItem(2))
    window.actions['Move up'].trigger()
    assert [entry['name'] for entry in vault.tree_children(None)] == ['Zebra', 'Écran', 'école']
    window.close()


def test_tree_scroll_restored_after_window_layout(qtbot, tmp_path):
    path = tmp_path / 'scroll.db'
    vault = Vault(path, 'master')
    for index in range(80):
        vault.save_folder(f'Group {index:03d}')
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    window.tree.verticalScrollBar().setValue(35)
    saved_scroll = window.tree.verticalScrollBar().value()
    assert saved_scroll > 0
    window.close()
    vault = Vault(path, 'master')
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    qtbot.waitUntil(lambda: window.tree.verticalScrollBar().value() == saved_scroll)
    window.close()
