from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QMessageBox

from remote_manager import APP_NAME, __version__
from remote_manager.storage.vault import Vault
from remote_manager.ui.main_window import MainWindow
from remote_manager.ui.help import HelpDialog

PROFILE = dict(name='Local session', host='localhost', port=22, username='', identity_file='')


def make_window(qtbot, tmp_path):
    vault = Vault(tmp_path / 'menu.db', 'master')
    window = MainWindow(vault, tmp_path / 'menu.db')
    qtbot.addWidget(window)
    window.show()
    return window


def test_menu_structure_shared_actions_and_visibility(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    assert [action.text() for action in window.menuBar().actions()] == ['File', 'Edit', 'Session', 'View', 'Help']
    assert window.actions['New connection'] in window.menus['File'].actions()
    assert window.actions['Edit'] in window.menus['Edit'].actions()
    assert 'Move' not in window.actions
    for title in ('Cut', 'Copy', 'Paste'):
        assert window.actions[title] in window.menus['Edit'].actions()
    assert window.actions['Connect'] in window.menus['Session'].actions()
    assert window.actions['About'] in window.menus['Help'].actions()
    assert [action.text() for action in window.toolbar.actions() if not action.isSeparator()] == ['New connection', 'Open database', 'Edit', 'Connect', 'Disconnect', 'Lock', 'Split vertically', 'Split horizontally', 'Grid 2 × 2']
    assert window.toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    assert all(action.text() and not action.icon().isNull() for action in window.toolbar.actions() if not action.isSeparator())
    assert not window.actions['Close tab'].isEnabled()
    assert not window.actions['Disconnect'].isEnabled()
    width = window.tabs.width()
    window.actions['Connection tree'].trigger()
    qtbot.waitUntil(lambda: window.tabs.width() > width)
    assert not window.sidebar.isVisible()
    assert not window.search.isVisible()
    window.actions['Find connection'].trigger()
    qtbot.waitUntil(lambda: window.sidebar.isVisible())
    assert window.actions['Connection tree'].isChecked()
    qtbot.waitUntil(window.search.hasFocus)
    qtbot.mouseDClick(window.tree_handle, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not window.sidebar.isVisible())
    assert not window.actions['Connection tree'].isChecked()
    assert window.tree_handle.isVisible() and window.tree_toggle.isVisible()
    qtbot.mouseClick(window.tree_toggle, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.sidebar.isVisible())
    expanded_width = window.sidebar.width()
    qtbot.mouseClick(window.tree_toggle, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not window.sidebar.isVisible())
    assert window.tree_toggle.isVisible()
    qtbot.mouseClick(window.tree_toggle, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.sidebar.isVisible())
    assert abs(window.sidebar.width() - expanded_width) <= 2
    window.actions['Connection tree'].setChecked(True)
    qtbot.waitUntil(lambda: window.sidebar.isVisible())
    qtbot.waitUntil(lambda: window.tree_handle.isVisible())
    window.actions['Status bar'].trigger()
    assert not window.statusBar().isVisible()
    window.actions['Status bar'].trigger()
    assert window.statusBar().isVisible()
    window.close()


def test_toolbar_modes_and_persistence(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    toolbar_menu = next(action.menu() for action in window.menus['View'].actions()
                        if action.text() == 'Toolbar')
    large, small, disabled = toolbar_menu.actions()
    assert [action.text() for action in (large, small, disabled)] == [
        'Large (icons and text)', 'Small (icons only)', 'Disabled']
    assert large.isChecked()
    large_height = window.toolbar.sizeHint().height()
    small.trigger()
    assert small.isChecked() and not large.isChecked()
    assert window.toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert window.toolbar.sizeHint().height() < large_height
    assert all(window.toolbar.widgetForAction(action).toolTip()
               for action in window.toolbar.actions() if not action.isSeparator())
    popup = window.createPopupMenu()
    assert popup.actions() == [large, small, disabled]
    popup.close()
    disabled.trigger()
    assert disabled.isChecked() and not small.isChecked()
    assert window.toolbar.isHidden()
    window.close()

    window = make_window(qtbot, tmp_path)
    assert window.toolbar.isHidden()
    assert window.toolbar_mode_actions['disabled'].isChecked()
    window.toolbar_mode_actions['large'].trigger()
    assert window.toolbar.isVisible()
    assert window.toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    window.close()


def test_quick_connect_toolbar(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    toolbar = window.quick_connect_toolbar
    toggle = window.actions['Quick Connect']
    assert toggle in window.menus['View'].actions()
    assert toolbar.isVisible() and toggle.isChecked()
    assert toolbar.geometry().top() > window.toolbar.geometry().bottom()
    connect = window.quick_connect_action
    assert connect.text() == 'Connect' and not connect.icon().isNull()
    controls = (window.quick_host, window.quick_port, window.quick_protocol, toolbar.widgetForAction(connect))
    geometry = [widget.geometry() for widget in controls]
    window.resize(window.width() + 300, window.height())
    qtbot.waitUntil(lambda: toolbar.width() == window.width())
    assert [widget.geometry() for widget in controls] == geometry
    assert not connect.isEnabled()
    assert window.quick_port.value() == 22
    for protocol, port in (('RDP', 3389), ('VNC', 5900), ('Telnet', 23), ('SSH', 22)):
        window.quick_protocol.setCurrentText(protocol)
        assert window.quick_port.value() == port
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[-1]))
    profiles = []
    monkeypatch.setattr(window, 'open_profile', profiles.append)
    window.quick_host.setText('-invalid')
    connect.trigger()
    assert warnings and not profiles
    window.quick_host.setText('  example.test  ')
    window.quick_port.setValue(2222)
    qtbot.keyClick(window.quick_host, Qt.Key.Key_Return)
    assert profiles == [dict(name='example.test', host='example.test', port=2222, protocol='ssh',
                             username='', identity_file='', credential_source='none',
                             authentication='prompt_both')]
    window.toolbar_mode_actions['disabled'].trigger()
    assert toolbar.isVisible()
    toggle.trigger()
    assert toolbar.isHidden()
    window.close()

    window = make_window(qtbot, tmp_path)
    assert window.quick_connect_toolbar.isHidden()
    assert not window.actions['Quick Connect'].isChecked()
    window.actions['Quick Connect'].trigger()
    assert window.quick_connect_toolbar.isVisible()
    window.close()


def test_file_help_about_actions(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    chosen = []
    monkeypatch.setattr(window, 'switch_database', lambda create=False: chosen.append(create))
    window.actions['New database'].trigger()
    window.actions['Open database'].trigger()
    assert chosen == [True, False]
    help_contents = []
    def show_help(dialog):
        help_contents.append(dialog.browser.toPlainText())
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(HelpDialog, 'exec', show_help)
    window.actions['Help'].trigger()
    assert 'Telnet is unencrypted' in help_contents[0]
    assert '.uni' in help_contents[0]
    about = []
    monkeypatch.setattr(QMessageBox, 'about', lambda parent, title, text: about.append(text))
    window.actions['About'].trigger()
    assert APP_NAME in about[0] and __version__ in about[0]
    assert 'GPL-3.0-or-later' in about[0]
    assert "href='mailto:victor@unirc.eu'" in about[0]
    assert "href='https://www.unirc.eu'" in about[0]
    window.actions['Exit'].trigger()
    assert not window.isVisible() and window.vault is None


def test_session_menu_real_pty_and_remote_shortcuts(qtbot, tmp_path, monkeypatch):
    from remote_manager.terminal import ssh
    # Ignore SSH multiplexing arguments while keeping a real interactive PTY.
    client = tmp_path / 'pty-client'
    client.write_text('#!/bin/sh\nexec cat\n')
    client.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(client)])
    window = make_window(qtbot, tmp_path)
    window.vault.save(PROFILE)
    profile = window.vault.profiles()[0]
    window.open_profile(profile)
    terminal = window.tabs.currentWidget()
    assert window.actions['Disconnect'].isEnabled()
    assert not window.actions['Reconnect'].isEnabled()
    terminal.send(b'MENU_PTY_RUNNING\r')
    qtbot.waitUntil(lambda: any('MENU_PTY_RUNNING' in row for row in terminal.screen.display))
    requested = []
    monkeypatch.setattr(window, 'new_profile', lambda: requested.append(True))
    terminal.setFocus()
    window.activateWindow()
    qtbot.waitUntil(terminal.hasFocus)
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    qtbot.keyClick(terminal, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert sent == [b'\x0e'] and not requested
    window.tree.setFocus()
    qtbot.waitUntil(window.tree.hasFocus)
    qtbot.keyClick(window.tree, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert requested == [True]
    window.actions['Disconnect'].trigger()
    assert terminal.process.poll() is not None
    assert window.tabs.count() == 1 and terminal.session_status.state == 'disconnected'
    assert terminal.session_status.exit_code is None  # No invented remote exit code.
    assert window.actions['Reconnect'].isEnabled()
    window.actions['Reconnect'].trigger()
    replacement = window.tabs.currentWidget()
    assert replacement is not terminal and replacement.is_running()
    monkeypatch.setattr(window, 'confirm_disconnect', lambda: False)
    window.actions['Exit'].trigger()
    assert window.isVisible() and replacement.is_running()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window.actions['Close tab'].trigger()
    assert window.tabs.count() == 0 and not replacement.is_running()
    monkeypatch.setattr(window, 'confirm_disconnect', lambda: True)
    window.close()


def test_file_new_database_creates_real_archive(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtWidgets import QInputDialog, QFileDialog, QApplication, QDialogButtonBox
    import remote_manager.ui.databases as databases
    from remote_manager.storage.archive import ArchiveVault
    window = make_window(qtbot, tmp_path)
    original = window.database_path
    window.vault.save(PROFILE)
    window.toolbar_mode_actions['small'].trigger()
    path = tmp_path / 'new.uni'
    monkeypatch.setattr(databases, 'QSettings', lambda: QSettings(str(tmp_path / 'recent.ini'), QSettings.Format.IniFormat))
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a: ('Menu database', True))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    def unlock():
        panel = QApplication.activeModalWidget().unlock_panel
        panel.password.setText('new-master')
        panel.confirmation.setText('new-master')
        panel.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
    QTimer.singleShot(50, unlock)
    window.actions['New database'].trigger()
    assert window.database_path == path
    assert window.toolbar_mode_actions['large'].isChecked()
    assert window.vault.metadata['description'] == 'Menu database'
    assert window.tree.topLevelItemCount() == 0
    window.close()
    vault = ArchiveVault(path, 'new-master')
    assert vault.metadata['description'] == 'Menu database'
    vault.close()
    vault = Vault(original, 'master')
    assert vault.profiles()[0]['name'] == PROFILE['name']
    assert vault.toolbar_mode() == 'small'
    vault.close()


def test_italian_menus_help_and_shortcut_modifiers(qtbot, tmp_path):
    from PyQt6.QtGui import QKeySequence
    from remote_manager.ui.language import set_language
    vault = Vault(tmp_path / 'italian-menu.db', 'master')
    vault.set_language('it')
    window = MainWindow(vault, tmp_path / 'italian-menu.db')
    qtbot.addWidget(window)
    try:
        window.show()
        assert [action.text() for action in window.menuBar().actions()] == ['File', 'Modifica', 'Sessione', 'Visualizza', 'Aiuto']
        assert [action.text() for action in window.toolbar_mode_actions.values()] == [
            'Grande (icone e testo)', 'Piccola (solo icone)', 'Disabilitato']
        assert window.actions['Quick Connect'].text() == 'Connessione rapida'
        shortcut = window.actions['New connection'].shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        assert shortcut == 'Ctrl+N'
        exit_shortcut = window.actions['Exit'].shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        assert 'Ctrl+' in exit_shortcut and exit_shortcut.endswith('+Q')
        help_dialog = HelpDialog(window)
        assert 'Telnet non è cifrato' in help_dialog.browser.toPlainText()
        assert help_dialog.windowTitle() == 'Aiuto'
    finally:
        window.close()
        set_language('en')
