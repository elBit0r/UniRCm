import pytest
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit
from sqlcipher3 import dbapi2 as sqlcipher

from remote_manager.storage.vault import Vault
from remote_manager.storage.archive import ArchiveVault
from remote_manager.ui.main_window import MainWindow
from remote_manager.ui.settings import ChangePasswordDialog, SettingsDialog


def open_vault(path, password, archive, create=False):
    return ArchiveVault(path, password, description='Test' if create else None) if archive else Vault(path, password)


@pytest.mark.parametrize('archive', [False, True])
def test_rekey_reopens_and_preserves_data(tmp_path, archive):
    path = tmp_path / ('vault.uni' if archive else 'vault.db')
    vault = open_vault(path, 'original', archive, True)
    vault.save(dict(name='private-profile', host='localhost', port=22, username='user', password='remote-secret', identity_file=''))
    vault.set_inactivity_minutes(5)
    with pytest.raises(ValueError):
        vault.change_password('incorrect', 'replacement')
    vault.change_password('original', "new ' master")
    assert vault.profiles()[0]['password'] == 'remote-secret'
    vault.set_inactivity_minutes(7)  # Archive connection wrapper still persists.
    vault.close()
    assert b'remote-secret' not in path.read_bytes()
    with pytest.raises(sqlcipher.DatabaseError):
        open_vault(path, 'original', archive)
    reopened = open_vault(path, "new ' master", archive)
    assert reopened.profiles()[0]['name'] == 'private-profile'
    assert reopened.inactivity_minutes() == 7
    reopened.close()
    assert not list(tmp_path.glob('.unircm-rekey-*'))


def test_rekey_archive_publish_failure_restores_original(tmp_path, monkeypatch):
    path = tmp_path / 'failure.uni'
    vault = ArchiveVault(path, 'original', description='Test')
    vault.set_inactivity_minutes(6)
    original = path.read_bytes()
    persist = vault._persist
    calls = []
    def fail_once():
        calls.append(True)
        if len(calls) == 1:
            raise OSError('Disk full')
        persist()
    monkeypatch.setattr(vault, '_persist', fail_once)
    with pytest.raises(OSError):
        vault.change_password('original', 'replacement')
    assert path.read_bytes() == original
    assert vault.inactivity_minutes() == 6
    monkeypatch.setattr(vault, '_persist', persist)
    vault.set_inactivity_minutes(8)
    vault.close()
    reopened = ArchiveVault(path, 'original')
    assert reopened.inactivity_minutes() == 8
    reopened.close()
    assert not list(tmp_path.glob('.unircm-rekey-*'))


def test_password_dialog_and_settings(qtbot, tmp_path):
    vault = Vault(tmp_path / 'ui.db', 'original')
    settings = SettingsDialog(vault)
    qtbot.addWidget(settings)
    assert settings.inactivity.value() == 0
    settings.inactivity.setValue(3)
    settings.save()
    assert vault.inactivity_minutes() == 3
    dialog = ChangePasswordDialog(vault)
    qtbot.addWidget(dialog)
    dialog.fields['current'].setText('original')
    dialog.fields['new'].setText('replacement')
    dialog.fields['confirmation'].setText('mismatch')
    dialog.save()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.fields['confirmation'].setText('replacement')
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert all(not field.text() for field in dialog.fields.values())
    vault.close()
    Vault(tmp_path / 'ui.db', 'replacement').close()


def test_activity_and_automatic_lock_closes_editors(qtbot, tmp_path, monkeypatch):
    import remote_manager.ui.main_window as module
    vault = Vault(tmp_path / 'idle.db', 'original')
    vault.set_inactivity_minutes(1)
    window = MainWindow(vault, tmp_path / 'idle.db')
    qtbot.addWidget(window)
    window.show()
    window.last_activity -= 59
    window.check_inactivity()
    assert not window._locking
    QApplication.sendEvent(window.search, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, 'a'))
    assert module.monotonic() - window.last_activity < 1
    editor = QDialog(window)
    field = QLineEdit(editor)
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setText('secret')
    editor.show()
    monkeypatch.setattr(window, 'confirm_disconnect', lambda: pytest.fail('Automatic lock must not wait for a confirmation'))
    window.last_activity -= 61
    window.check_inactivity()
    assert field.text() == '' and not editor.isVisible()
    qtbot.waitUntil(lambda: window.unlock_panel is not None)
    assert window.vault is None and window.tree.topLevelItemCount() == 0
    assert window.isVisible() and not window.unlock_panel.isWindow()
    assert not window.menuBar().isVisible()
    assert all(not action.isEnabled() for action in window.actions.values())
    window.unlock_panel.password.setText('wrong password')
    window.unlock_panel.submit()
    assert window.vault is None and window.unlock_panel.error.text()
    window.unlock_panel.password.setText('original')
    window.unlock_panel.submit()
    assert not window._locking and window.inactivity_limit == 60
    assert window.menuBar().isVisible()
    assert window.actions['Settings'].isEnabled()
    monkeypatch.setattr(window, 'confirm_disconnect', lambda: True)
    hidden = QDialog(window)
    hidden.profile = {'password': 'hidden-secret', 'key_passphrase': 'hidden-phrase'}
    revealed = QLineEdit(hidden)
    revealed.setText('revealed-secret')
    window.lock_vault()
    assert revealed.text() == '' and hidden.profile == {}
    window.close()


def test_shared_key_passphrase_storage(qtbot, tmp_path):
    from remote_manager.ui.credentials import CredentialsEditor
    vault = Vault(tmp_path / 'keys.db', 'master')
    reference = vault.save_credential('Key', 'user', '', key_passphrase='key-secret-marker')
    group = vault.save_folder('Keys', defaults={'credential_id': reference})
    vault.save(dict(name='Key login', host='localhost', port=22, username='', identity_file='/tmp/key', folder_id=group, credential_source='inherit'))
    profile = vault.effective_profile(vault.profiles()[0])
    assert profile['key_passphrase'] == 'key-secret-marker'
    editor = CredentialsEditor(vault.credential(reference))
    qtbot.addWidget(editor)
    assert editor.key_passphrase.echoMode() == QLineEdit.EchoMode.Password
    assert editor.values()['key_passphrase'] == 'key-secret-marker'
    vault.close()
    assert b'key-secret-marker' not in (tmp_path / 'keys.db').read_bytes()


def test_archive_description_and_database_switch(qtbot, tmp_path, monkeypatch):
    from remote_manager.ui.databases import DatabaseChooser
    from remote_manager.terminal import ssh
    # Terminal injects OpenSSH control options after argv[0]. A launcher
    # accepts those arguments while keeping a real local PTY process alive.
    launcher = tmp_path / 'local-session'
    launcher.write_text('#!/bin/sh\nprintf "SESSION_READY\\n"\nexec cat\n')
    launcher.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(launcher)])
    first_path, second_path = tmp_path / 'first.uni', tmp_path / 'second.uni'
    first = ArchiveVault(first_path, 'first', description='First')
    second = ArchiveVault(second_path, 'second', description='Second')
    first.save(dict(name='First connection', host='localhost', port=22, username='', identity_file=''))
    second.save(dict(name='Second connection', host='localhost', port=22, username='', identity_file=''))
    second.set_inactivity_minutes(4)
    second.close()
    window = MainWindow(first, first_path)
    qtbot.addWidget(window)
    window.show()
    settings = SettingsDialog(first, window)
    settings.description.setPlainText('Updated description')
    settings.save()
    from remote_manager.storage.archive import metadata
    assert metadata(first_path)['description'] == 'Updated description'
    window.open_profile(first.profiles()[0])
    terminal = window.tabs.widget(0)
    qtbot.waitUntil(lambda: any(line.strip() == 'SESSION_READY' for line in terminal.screen.display))
    assert terminal.is_running()
    monkeypatch.setattr(window, 'confirm_disconnect', lambda: True)
    monkeypatch.setattr(DatabaseChooser, 'exec', lambda self: QDialog.DialogCode.Rejected)
    window.switch_database()
    assert window.vault is first and terminal.is_running()
    terminal.send(b'SESSION_STILL_ACTIVE\r')
    # One line is PTY echo; the other comes from the running cat process.
    qtbot.waitUntil(lambda: sum(line.strip() == 'SESSION_STILL_ACTIVE'
                               for line in terminal.screen.display) == 2)
    assert terminal.is_running()
    control_directory = terminal.control_directory.name

    def choose(dialog):
        assert dialog.excluded_path == first_path.resolve()
        dialog.vault = ArchiveVault(second_path, 'second')
        dialog.path = second_path
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DatabaseChooser, 'exec', choose)
    window.switch_database()
    assert terminal.process.poll() is not None
    assert terminal.fd is None
    from pathlib import Path
    assert not Path(control_directory).exists()
    assert window.tabs.count() == 0
    assert window.tree.topLevelItem(0).text(0) == 'Second connection'
    assert window.inactivity_limit == 240
    assert second_path.name in window.windowTitle()
    window.close()
    reopened = ArchiveVault(first_path, 'first')
    assert reopened.metadata['description'] == 'Updated description'
    reopened.close()


def test_italian_interface_preserves_profile_names(qtbot, tmp_path):
    from remote_manager.ui.language import set_language
    from remote_manager.ui.dialogs import ProfileDialog
    vault = Vault(tmp_path / 'italian.db', 'master')
    vault.set_language('it')
    vault.save(dict(name='Settings', host='localhost', port=22, username='', identity_file=''))
    window = MainWindow(vault, tmp_path / 'italian.db')
    qtbot.addWidget(window)
    try:
        window.show()
        assert window.actions['New connection'].text() == 'Nuova connessione'
        assert window.actions['Settings'].text() == 'Impostazioni'
        assert window.local_tree.headerItem().text(0) == 'Locale'
        assert window.tree.headerItem().text(0) == 'Remoto'
        assert window.tree.topLevelItem(0).text(0) == 'Settings'  # User text.
        profile = ProfileDialog(parent=window)
        assert profile.tabs.tabText(0) == 'Generale'
        assert profile.credential_selector.source_options['local'].text() == 'Credenziali della connessione'
        settings = SettingsDialog(vault, window)
        settings.show()
        assert settings.windowTitle() == 'Impostazioni database'
        assert settings.language.currentData() == 'it'
        vault.set_language('en')
        set_language('en')
        assert window.actions['New connection'].text() == 'New connection'
        vault.close()
        window.vault = None
        reopened = Vault(tmp_path / 'italian.db', 'master')
        assert reopened.language() == 'en'
        reopened.close()
    finally:
        window.close()
        set_language('en')


def test_idle_lock_unwinds_nested_credential_editor(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QPushButton
    from remote_manager.ui.credentials import CredentialManager, CredentialsEditor
    import remote_manager.ui.main_window as module
    vault = Vault(tmp_path / 'nested.db', 'master')
    vault.set_inactivity_minutes(1)
    window = MainWindow(vault, tmp_path / 'nested.db')
    qtbot.addWidget(window)
    window.show()
    def expire():
        editor = QApplication.activeModalWidget()
        fields = editor.findChild(CredentialsEditor)
        fields.password.setText('secret')
        fields.key_passphrase.setText('phrase')
        window.last_activity -= 61
        window.check_inactivity()
    def open_editor():
        dialog = QApplication.activeModalWidget()
        QTimer.singleShot(20, expire)
        next(b for b in dialog.findChildren(QPushButton) if b.text() == 'New credential').click()
    QTimer.singleShot(20, open_editor)
    CredentialManager.open(vault, window)
    qtbot.waitUntil(lambda: window.unlock_panel is not None)
    assert window._locking and window.vault is None
    window.unlock_panel.password.setText('master')
    window.unlock_panel.submit()
    assert not window._locking
    window.close()


def test_inline_lock_stops_pty_and_restores_hidden_chrome(qtbot, tmp_path, monkeypatch):
    from remote_manager.terminal import ssh
    from remote_manager.ui.language import set_language
    client = tmp_path / 'pty-client'
    client.write_text('#!/bin/sh\nexec cat\n')
    client.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(client)])
    path = tmp_path / 'inline-lock.db'
    vault = Vault(path, 'master')
    pid = vault.save(dict(name='PTY', host='localhost', port=22, username='', identity_file=''))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    window.toolbar.hide()
    window.statusBar().hide()
    window.open_profile(vault.profiles(pid)[0])
    terminal = window.tabs.currentWidget()
    terminal.send(b'INLINE_LOCK_READY\r')
    qtbot.waitUntil(lambda: any('INLINE_LOCK_READY' in row for row in terminal.screen.display))
    monkeypatch.setattr(window, 'confirm_disconnect', lambda: True)
    window.lock_vault()
    assert not terminal.is_running()
    assert window.tabs.count() == 0 and window.vault is None
    panel = window.unlock_panel
    try:
        set_language('it')
        QApplication.processEvents()
        assert panel.buttons.button(QDialogButtonBox.StandardButton.Ok).text() == 'Sblocca database'
        assert panel.buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == 'Esci'
        panel.password.setText('master')
        qtbot.keyClick(panel.password, Qt.Key.Key_Return)
        assert window.vault is not None and window.unlock_panel is None
        assert not panel.password.text()
        assert window.menuBar().isVisible()
        assert not window.toolbar.isVisible() and not window.statusBar().isVisible()
        window.lock_vault()
        panel = window.unlock_panel
        panel.password.setText('discard-on-close')
        panel.show_password.setChecked(True)
        window.close()
        assert not panel.password.text() and not panel.show_password.isChecked()
    finally:
        set_language('en')
        window.close()
