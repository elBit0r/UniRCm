"""Workspace lifecycle exercised with real loopback SSH processes."""
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox, QMenu
from remote_manager.storage.vault import Vault
from remote_manager.ui.main_window import MainWindow
from remote_manager.ui.session_workspace import SessionWorkspace
from test_ssh import ssh_server


def test_drag_live_session_between_workspaces(qtbot, tmp_path, ssh_server, monkeypatch):
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
    from PyQt6.QtWidgets import QApplication
    from remote_manager.ui.session_workspace import SessionDragData

    path = tmp_path / 'drag.db'
    vault = Vault(path, 'master')
    vault.save(ssh_server)
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    try:
        profile = vault.profiles()[0]
        terminal, other = (window.open_profile(profile) for _ in range(2))
        source = window.ensure_workspace(terminal)
        target = window.ensure_workspace(other)
        target.arrange('grid')
        process = terminal.process
        left = Qt.MouseButton.LeftButton
        shift = Qt.KeyboardModifier.ShiftModifier
        move = Qt.DropAction.MoveAction
        bar = window.tabs.tabBar()
        drags = []
        monkeypatch.setattr(SessionDragData, 'start', lambda widget, term: drags.append(term))

        def mouse_drag(widget, origin, modifiers):
            qtbot.mousePress(widget, left, modifier=modifiers, pos=origin)
            point = QPointF(origin + QPoint(QApplication.startDragDistance() + 1, 0))
            QApplication.sendEvent(widget, QMouseEvent(QEvent.Type.MouseMove, point, point,
                                                      Qt.MouseButton.NoButton, left, modifiers))
            qtbot.mouseRelease(widget, left, modifier=modifiers, pos=origin)

        window.tabs.setCurrentWidget(source)
        mouse_drag(source.panels[terminal][1], QPoint(5, 5), Qt.KeyboardModifier.NoModifier)
        assert drags == [terminal]
        data = SessionDragData(drags.pop())
        origin = bar.tabRect(window.tabs.indexOf(source)).center()
        assert bar.tabAt(origin) >= 0
        enter = QDragEnterEvent(origin, move, data, left, Qt.KeyboardModifier.NoModifier)
        bar.dragEnterEvent(enter)
        assert enter.isAccepted()
        rejected = QDragMoveEvent(origin, move, data, left, Qt.KeyboardModifier.NoModifier)
        bar.dragMoveEvent(rejected)
        assert not rejected.isAccepted()
        destination = bar.tabRect(window.tabs.indexOf(target)).center()
        drop = QDropEvent(QPointF(destination), move, data, left, Qt.KeyboardModifier.NoModifier)
        bar.dropEvent(drop)
        assert drop.isAccepted()
        assert window.tabs.count() == 1 and target.active is terminal and target.mode == 'grid'

        # A Shift-drag from a standalone tab can fill an exact vacant pane.
        window.detach_terminal(terminal)
        window.tabs.setCurrentWidget(target)
        mouse_drag(bar, bar.tabRect(window.tabs.indexOf(terminal)).center(), shift)
        assert drags == [terminal]
        assert window.tabs.currentWidget() is target
        empty = next(pane for pane in target.empty_panes if pane.slot == 3)
        data = SessionDragData(drags.pop())
        drop = QDropEvent(QPointF(5, 5), move, data, left, shift)
        empty.dropEvent(drop)
        assert drop.isAccepted() and target.positions[terminal] == 3
        assert terminal.process is process
        terminal.send(b"printf '\\nDRAGGED_SESSION\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'DRAGGED_SESSION' for line in terminal.screen.display),
                        timeout=15000)
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()


def test_live_workspace_layout_focus_detach_close(qtbot, tmp_path, ssh_server, monkeypatch):
    vault = Vault(tmp_path / 'workspace.db', 'master')
    vault.save(ssh_server)
    window = MainWindow(vault, tmp_path / 'workspace.db')
    qtbot.addWidget(window)
    window.resize(1500, 1000)
    window.show()
    terms = []
    try:
        for i in range(4):
            term = window.open_profile(vault.profiles()[0])
            terms.append(term)
            term.send(f"printf '\\nWORKSPACE_{i}\\n'\r".encode())
            qtbot.waitUntil(lambda t=term, n=i: any(line.strip() == f'WORKSPACE_{n}' for line in t.screen.display), timeout=15000)
        processes = [t.process for t in terms]
        window.move_to_workspace(terms[1], terms[0], 'side')
        group = window.tabs.widget(0)
        assert isinstance(group, SessionWorkspace)
        assert window.tabs.count() == 3
        window.move_to_workspace(terms[2], group, 'stack')
        menu = QMenu(window)
        window.populate_workspace_menu(menu, group)
        assert [a.text() for a in menu.actions()] == [
            'Rename tab', 'Layout', 'Add connection', 'Move open session here',
            'Detach active pane', 'Close active pane']
        layouts = menu.actions()[1].menu().actions()
        assert [a.isChecked() for a in layouts] == [False, True, False]
        layouts[2].trigger()
        assert group.mode == 'grid'
        assert [a.isChecked() for a in layouts] == [False, False, True]
        # Moving through the menu keeps the chosen layout and the live process.
        menu.actions()[3].menu().actions()[0].trigger()
        assert window.tabs.count() == 1
        assert group.root.count() == 2
        assert all(group.root.widget(i).count() == 2 for i in range(2))
        assert [t.process for t in terms] == processes
        qtbot.waitUntil(lambda: all(t.isVisible() for t in terms))
        qtbot.wait(100)  # Allow Qt to finish deferred layout events before visual capture.
        assert group.layout_box.count() == 1
        assert group.root.height() >= group.height() - 2
        window.grab().save(str(tmp_path / "workspace.png"))
        for terminal in terms:
            terminal.setFocus()
            qtbot.waitUntil(lambda: group.active is terminal)
            assert all(panel.active == (term is terminal) for term, (panel, _) in group.panels.items())
            assert window.actions['Disconnect'].isEnabled()
            qtbot.waitUntil(lambda: terminal.screen.columns > 10)
            rows, cols = terminal.screen.lines, terminal.screen.columns
            terminal.send(b'stty size\r')
            qtbot.waitUntil(lambda t=terminal, r=rows, c=cols: any(line.strip() == f'{r} {c}' for line in t.screen.display))
        terms[0].session_status.bell.emit()
        terms[1].session_status.activity.emit('rx')
        assert window.tabs.tabBar().tabTextColor(0) == QColor('#e67e22')
        group.toggle_maximize(terms[0])
        assert all(not group.panels[t][0].isVisible() for t in terms[1:])
        group.toggle_maximize(terms[0])
        assert all(group.panels[t][0].isVisible() for t in terms)
        window.detach_terminal(terms[3])
        assert window.tabs.count() == 2 and terms[3].process is processes[3]
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
        window.close_tab(0)
        assert all(t.is_running() for t in terms)
        monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
        window.close_pane(terms[1])
        assert terms[1].process.poll() is not None
        assert terms[0].is_running() and terms[2].is_running()
        window.close_tab(0)
        assert terms[0].process.poll() is not None and terms[2].process.poll() is not None
        assert terms[3].is_running()
        assert all(t not in window.tabs._notifications for t in terms[:3])
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()


def test_reconnect_within_group(qtbot, tmp_path, ssh_server):
    vault = Vault(tmp_path / 'reconnect.db', 'master')
    vault.save(ssh_server)
    window = MainWindow(vault, tmp_path / 'reconnect.db')
    qtbot.addWidget(window)
    window.show()
    try:
        first = window.open_profile(vault.profiles()[0])
        group = window.ensure_workspace(first)
        group.arrange('stack')
        menu = QMenu(window)
        window.populate_workspace_menu(menu, group)
        menu.actions()[2].menu().actions()[0].trigger()
        assert group.mode == 'stack'
        group = window.tabs.currentWidget()
        second = group.active
        second.send(b"printf '\\nCONNECTED_PANE\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'CONNECTED_PANE' for line in second.screen.display), timeout=15000)
        second.send(b'exit 7\r')
        qtbot.waitUntil(lambda: '[exit 7]' in second._workspace_title, timeout=5000)
        assert group.panels[second][1].text().endswith('[exit 7]')
        original = first.process
        window.reconnect_terminal(second)
        assert window.tabs.count() == 1 and len(group.terminals) == 2
        assert first.process is original and first.is_running()
        replacement = group.active
        assert replacement is not second
        replacement.send(b"printf '\\nRECONNECTED_PANE\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'RECONNECTED_PANE' for line in replacement.screen.display), timeout=15000)
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()


def test_empty_panes_toolbar_menu_and_tree_drop(qtbot, tmp_path, ssh_server):
    from PyQt6.QtCore import Qt, QPointF
    from PyQt6.QtGui import QDropEvent
    vault = Vault(tmp_path / 'empty-panes.db', 'master')
    vault.save(ssh_server)
    window = MainWindow(vault, tmp_path / 'empty-panes.db')
    qtbot.addWidget(window)
    window.show()
    try:
        assert not window.actions['Split vertically'].isEnabled()
        profile = vault.profiles()[0]
        first = window.open_profile(profile)
        first.send(b"printf '\\nFIRST_PANE\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'FIRST_PANE' for line in first.screen.display), timeout=15000)
        process = first.process
        window.actions['Split vertically'].trigger()
        group = window.tabs.currentWidget()
        assert group.root.orientation() == Qt.Orientation.Horizontal
        assert group.root.count() == 2 and len(group.empty_panes) == 1
        menu = QMenu(window)
        window.populate_empty_pane_menu(group, menu, 1)
        assert len(menu.actions()) == 1 and not menu.actions()[0].isEnabled()
        window.actions['Split horizontally'].trigger()
        assert group.root.orientation() == Qt.Orientation.Vertical
        assert group.root.count() == 2
        window.actions['Grid 2 × 2'].trigger()
        assert len(group.empty_panes) == 3
        assert group.root.count() == 2 and group.root.widget(1).count() == 2
        second = window.open_profile(profile)
        second_process = second.process
        menu = QMenu(window)
        window.populate_empty_pane_menu(group, menu, 3)
        assert len(menu.actions()) == 1 and menu.actions()[0].isEnabled()
        menu.actions()[0].trigger()
        assert group.positions[second] == 3 and second.process is second_process
        assert len(group.empty_panes) == 2
        window.tree.setCurrentItem(window.tree.topLevelItem(0))
        assert group.accepts_drop(window.tree)
        assert not group.accepts_drop(window.tabs)
        mime = window.tree.mimeData(window.tree.selectedItems())
        class TreeDrop(QDropEvent):
            def source(self):
                return window.tree
        event = TreeDrop(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        empty = next(pane for pane in group.empty_panes if pane.slot == 1)
        empty.dropEvent(event)
        assert event.isAccepted()
        third = group.active
        assert group.positions[third] == 1
        third.send(b"printf '\\nDROPPED_PANE\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'DROPPED_PANE' for line in third.screen.display), timeout=15000)
        assert first.process is process and first.is_running()
        group.toggle_maximize(first)
        assert all(not pane.isVisible() for pane in group.empty_panes)
        group.toggle_maximize(first)
        assert all(pane.isVisible() for pane in group.empty_panes)
        window.detach_terminal(second)
        assert any(pane.slot == 3 for pane in group.empty_panes)
        assert group.positions[third] == 1
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()


def test_layout_preserves_slots_focus_and_splitter_sizes(qtbot):
    from PyQt6.QtWidgets import QLineEdit
    workspace = SessionWorkspace()
    qtbot.addWidget(workspace)
    workspace.resize(1500, 900)
    first, second = QLineEdit(), QLineEdit()
    workspace.add_terminal(first, 'grid', 0)
    workspace.add_terminal(second, slot=3)
    workspace.show()
    workspace.activateWindow()
    second.setFocus()
    qtbot.waitUntil(lambda: second.hasFocus())
    workspace.root.setSizes([300, 600])
    workspace.root.widget(0).setSizes([900, 600])
    workspace.root.widget(1).setSizes([550, 950])
    qtbot.wait(30)
    original = (workspace.root.sizes(), [workspace.root.widget(i).sizes() for i in range(2)])
    root = workspace.root
    workspace.arrange('grid')
    assert workspace.root is root
    workspace.arrange('side')
    qtbot.waitUntil(lambda: second.hasFocus())
    assert workspace.positions == {first: 0, second: 3}
    workspace.root.setSizes([600, 300, 300, 300])
    qtbot.wait(30)
    side_sizes = workspace.root.sizes()
    workspace.arrange('grid')
    qtbot.wait(30)
    assert workspace.root.sizes() == original[0]
    assert [workspace.root.widget(i).sizes() for i in range(2)] == original[1]
    assert workspace.active is second and second.hasFocus()
    workspace.toggle_maximize(second)
    qtbot.wait(30)
    assert not workspace.root.widget(0).isVisible()
    workspace.toggle_maximize(second)
    qtbot.wait(30)
    assert workspace.root.sizes() == original[0]
    assert [workspace.root.widget(i).sizes() for i in range(2)] == original[1]
    workspace.arrange('side')
    qtbot.wait(30)
    assert workspace.root.sizes() == side_sizes


def test_removing_inactive_pane_keeps_active_session(qtbot):
    from PyQt6.QtWidgets import QLineEdit
    workspace = SessionWorkspace()
    qtbot.addWidget(workspace)
    terms = [QLineEdit() for _ in range(3)]
    for term in terms:
        workspace.add_terminal(term)
    workspace.show()
    workspace.activate(terms[2])
    removed = workspace.take_terminal(terms[0])
    qtbot.addWidget(removed)
    assert workspace.active is terms[2]
    assert workspace.positions[terms[2]] == 2
    assert workspace.panels[terms[2]][0].active
