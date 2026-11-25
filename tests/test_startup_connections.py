from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from remote_manager.storage.archive import ArchiveVault
from remote_manager.storage.vault import Vault
from remote_manager.ui import databases
from remote_manager.ui.main_window import MainWindow
from remote_manager.ui.dialogs import ProfileDialog


def test_startup_selection_and_encrypted_persistence(qtbot, tmp_path, monkeypatch):
    settings_path = str(tmp_path / 'preferences.ini')
    monkeypatch.setattr(databases, 'QSettings',
                        lambda: QSettings(settings_path, QSettings.Format.IniFormat))
    path = tmp_path / 'vault.uni'
    vault = ArchiveVault(path, 'master', 'Received vault')
    base = dict(host='localhost', username='user', port=22, identity_file='')
    auto_id = vault.save(dict(base, name='Automatic', connect_at_startup=True,
                              before_connect_command='true'))
    vault.save(dict(base, name='Manual'))
    vault.close()
    opened = []
    warnings = []
    monkeypatch.setattr(MainWindow, 'open_profile', lambda self, profile: opened.append(profile['id']))

    def acknowledge():
        warning = QApplication.activeModalWidget()
        if isinstance(warning, QMessageBox):
            warnings.append(warning.text())
            warning.button(QMessageBox.StandardButton.Ok).click()

    def open_window(*, first_open):
        chooser = databases.DatabaseChooser(tmp_path / 'unused.db')
        qtbot.addWidget(chooser)
        chooser.open_path(path)
        chooser.unlock_panel.password.setText('master')
        if first_open:
            QTimer.singleShot(0, acknowledge)
        chooser.unlock_panel.submit()
        assert chooser.allow_startup_connections is not first_open
        window = MainWindow(chooser.vault, chooser.path,
                            allow_startup_connections=chooser.allow_startup_connections)
        qtbot.addWidget(window)
        return window

    window = open_window(first_open=True)
    assert len(warnings) == 1 and 'Commands tab' in warnings[0]
    QApplication.processEvents()
    assert opened == []
    assert window.vault.profiles(auto_id)[0]['before_connect_command'] == 'true'
    window.close()

    window = open_window(first_open=False)
    vault = window.vault
    qtbot.waitUntil(lambda: opened == [auto_id])
    saved = vault.profiles(auto_id)[0]
    dialog = ProfileDialog(saved, window, vault.folders(), save_callback=vault.save)
    assert dialog.connect_at_startup.isChecked()
    dialog.connect_at_startup.setChecked(False)
    dialog.save()
    assert not vault.profiles(auto_id)[0]['connect_at_startup']
    window.close()

    path.unlink()
    ArchiveVault(path, 'master', 'Different vault').close()
    window = open_window(first_open=True)
    assert len(warnings) == 2
    window.close()


def test_ssh_reconnect_preferences_and_password_visibility(qtbot, tmp_path):
    from PyQt6.QtWidgets import QLineEdit

    path = tmp_path / 'vault.db'
    vault = Vault(path, 'master')
    profile_id = vault.save(dict(name='SSH', host='localhost', username='user', port=22,
                                 identity_file='', password='test-secret'))
    dialog = ProfileDialog(vault.profiles(profile_id)[0], save_callback=vault.save)
    qtbot.addWidget(dialog)
    assert not dialog.auto_reconnect.isChecked()
    assert not dialog.reconnect_delay.isEnabled()
    assert dialog.credentials.password.echoMode() == QLineEdit.EchoMode.Password
    dialog.credentials.show_secrets.setChecked(True)
    assert dialog.credentials.password.echoMode() == QLineEdit.EchoMode.Normal
    assert dialog.credentials.key_passphrase.echoMode() == QLineEdit.EchoMode.Password
    dialog.credential_selector.source.setCurrentIndex(dialog.credential_selector.source.findData('none'))
    assert dialog.credentials.password.echoMode() == QLineEdit.EchoMode.Password
    dialog.credential_selector.source.setCurrentIndex(dialog.credential_selector.source.findData('local'))
    dialog.auto_reconnect.setChecked(True)
    dialog.reconnect_delay.setValue(12)
    dialog.save()
    vault.close()

    reopened = Vault(path, 'master')
    try:
        profile = reopened.profiles(profile_id)[0]
        assert profile['ssh_reconnect_delay'] == 12
        assert profile['password'] == 'test-secret'
    finally:
        reopened.close()


def test_ssh_reconnect_timer_replaces_lost_session(qtbot, tmp_path, local_pty_client):
    path = tmp_path / 'vault.db'
    vault = Vault(path, 'master')
    profile_id = vault.save(dict(name='SSH', host='localhost', username='user', port=22,
                                 identity_file='', ssh_reconnect_delay=1))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    terminal = window.open_profile(vault.profiles(profile_id)[0])
    try:
        # Inject the status of a lost authenticated transport. The replacement
        # runs through the normal terminal process and tab lifecycle.
        terminal.session_status.set_state('connected')
        terminal.stop()
        terminal.exited.emit(255)
        assert window.reconnect_pending(terminal)
        assert terminal._reconnect_timer.interval() == 1000
        assert window.tabs.currentWidget() is terminal
        qtbot.waitUntil(lambda: window.tabs.currentWidget() is not terminal, timeout=3000)
        replacement = window.tabs.currentWidget()
        assert window.tabs.count() == 1
        assert replacement.profile_id == profile_id
        assert replacement.is_running()

        replacement.session_status.set_state('connected')
        replacement.stop()
        replacement.exited.emit(255)
        window.disconnect_current_session()
        assert not window.reconnect_pending(replacement)
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()
