"""Telnet checks against an independent real TCP peer, without SSH subprocesses."""
import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtNetwork import QHostAddress, QTcpServer
from PyQt6.QtWidgets import QDialog, QMessageBox

from remote_manager.storage.vault import Vault
from remote_manager.ui.credentials import ConnectionAuthenticationDialog
from remote_manager.ui.dialogs import ProfileDialog
from remote_manager.ui.main_window import MainWindow
from remote_manager.terminal.ssh import Terminal
from remote_manager.terminal.telnet import PromptLogin


class Peer:
    def __init__(self, qtbot):
        self.server = QTcpServer()
        assert self.server.listen(QHostAddress.SpecialAddress.LocalHost, 0)
        self.port = self.server.serverPort()
        self.socket = None
        self.sockets = []
        self.received = bytearray()
        self.server.newConnection.connect(self.accept)

    def accept(self):
        self.socket = self.server.nextPendingConnection()
        socket = self.socket
        self.sockets.append(socket)
        socket.readyRead.connect(lambda: self.received.extend(bytes(socket.readAll())))
        # Negotiate NAWS, terminal type, remote echo, SGA and bidirectional binary.
        self.socket.write(b'\xff\xfd\x1f\xff\xfd\x18\xff\xfb\x01\xff\xfb\x03\xff\xfb\x00\xff\xfd\x00')
        self.socket.write(b'\xff\xfa\x18\x01\xff\xf0')

    def send(self, data):
        self.socket.write(data)
        self.socket.flush()

    def close(self):
        for socket in self.sockets:
            socket.abort()
        self.server.close()


@pytest.fixture
def peer(qtbot):
    server = Peer(qtbot)
    yield server
    server.close()


def telnet_profile(port, mode='manual'):
    return dict(name='Switch', host='127.0.0.1', port=port, username='operator',
                password='telnet-secret-marker', identity_file='', protocol='telnet',
                telnet_options=dict(login_mode=mode))


def test_prompt_recognition_one_shot_and_manual():
    manual = PromptLogin('manual', 'user', 'secret')
    assert manual.feed('login: Password:') is None
    password = PromptLogin('password', 'ignored', 'secret')
    assert password.feed('Username:') is None
    assert password.feed('\r\n\x1b[31mPass') is None
    assert password.feed('word:\x1b[0m') == 'secret'
    assert password.feed('\r\nPassword:') is None
    login = PromptLogin('username_password', 'user', 'secret')
    assert login.feed('User Name:') == 'user'
    assert login.feed('\r\nOTP:') is None
    assert login.feed('\r\nPassword:') == 'secret'
    assert login.feed('\r\nLogin:') is None
    assert login.username == login.password == ''


@pytest.mark.parametrize('mode', ['manual', 'password', 'username_password'])
def test_real_login_modes_and_terminal(qtbot, peer, mode, caplog, tmp_path):
    caplog.set_level(1)  # Library TRACE output must not expose wire data.
    output = tmp_path / 'local-commands'
    terminal = Terminal(dict(
        telnet_profile(peer.port, mode),
        before_connect_command=f'printf before > "{output}"',
        after_disconnect_command=f'printf after >> "{output}"',
    ))
    qtbot.addWidget(terminal)
    terminal.resize(850, 500)
    terminal.show()
    try:
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected', timeout=4000)
        assert output.read_text() == 'before'
        qtbot.waitUntil(lambda: b'\xff\xfb\x1f' in peer.received and b'xterm-256color' in peer.received)
        assert terminal.process is None and terminal.askpass is None
        assert terminal.session_status.protocol == 'TELNET'
        peer.send(b'Username:')
        if mode == 'username_password':
            qtbot.waitUntil(lambda: b'operator\r\n' in peer.received)
        else:
            qtbot.wait(100)
            assert b'operator' not in peer.received
        peer.send(b'\r\nPass')
        QTimer.singleShot(15, lambda: peer.send(b'word:'))
        if mode == 'manual':
            qtbot.wait(150)
            assert b'telnet-secret-marker' not in peer.received
            qtbot.keyClicks(terminal, 'manual-password')
            qtbot.keyClick(terminal, Qt.Key.Key_Return)
            qtbot.waitUntil(lambda: b'manual-password\r\n' in peer.received)
        else:
            qtbot.waitUntil(lambda: b'telnet-secret-marker\r\n' in peer.received)
            peer.send(b'\r\nPassword:')
            qtbot.wait(100)
            assert peer.received.count(b'telnet-secret-marker') == 1
        peer.send(b'\r\n\x1b[32mREADY\x1b[0m caf\xc3')
        QTimer.singleShot(10, lambda: peer.send(b'\xa9\xe7\x95\x8c\r\n'))
        qtbot.waitUntil(lambda: any('READY café界' in line for line in terminal.screen.display))
        assert not any('telnet-secret-marker' in line for line in terminal.screen.display)
        before = peer.received.count(b'\xff\xfa\x1f')
        terminal.resize(1040, 620)
        qtbot.waitUntil(lambda: peer.received.count(b'\xff\xfa\x1f') > before)
        terminal.send('check\r'.encode())
        qtbot.waitUntil(lambda: b'check\r\n' in peer.received)
        peer.socket.disconnectFromHost()
        qtbot.waitUntil(lambda: not terminal.is_running())
        qtbot.waitUntil(lambda: output.read_text() == 'beforeafter')
        assert terminal.session_status.state == 'disconnected'
        assert terminal.session_status.exit_code == 0
        assert not any('telnet-secret-marker' in record.getMessage() for record in caplog.records)
    finally:
        terminal.stop()
        assert not terminal.transport.isRunning()


@pytest.mark.parametrize('authentication', ['configured', 'prompt_password'])
def test_telnet_editor_shared_credentials_reconnect_and_close(qtbot, tmp_path, peer, monkeypatch, authentication):
    vault = Vault(tmp_path / 'config.db', 'master')
    reference = vault.save_credential('Switch password', '', 'password-only')
    group = vault.save_folder('Switches', defaults={'credential_id': reference, 'port': 2222})
    window = MainWindow(vault, tmp_path / 'config.db')
    qtbot.addWidget(window)
    editor = ProfileDialog(parent=window, folders=vault.folders(), folder_id=group, save_callback=vault.save)
    editor.fields['name'].setText('Telnet switch')
    editor.fields['host'].setText('127.0.0.1')
    editor.protocol.setCurrentIndex(editor.protocol.findData('telnet'))
    assert editor.port.value() == 23
    assert editor.telnet_login.currentData() == 'manual'
    assert not editor.tabs.isTabEnabled(1) and editor.tabs.isTabEnabled(editor.tabs.indexOf(editor.telnet_page))
    editor.port.setValue(peer.port)
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData('password'))
    editor.credential_selector.source.setCurrentIndex(editor.credential_selector.source.findData('inherit'))
    editor.authentication.setCurrentIndex(editor.authentication.findData(authentication))
    prompted = []

    def enter_password(dialog):
        def submit():
            prompted.append(tuple(dialog.inputs))
            dialog.inputs['password'].setText('one-time-password')
            dialog.connect_button.click()

        QTimer.singleShot(0, submit)
        return QDialog.exec(dialog)

    monkeypatch.setattr(ConnectionAuthenticationDialog, 'exec', enter_password)

    editor.save()
    assert editor.result() == QDialog.DialogCode.Accepted
    saved = vault.profiles()[0]
    assert saved['protocol'] == 'telnet' and saved['telnet_options']['login_mode'] == 'password'
    effective = vault.effective_profile(saved)
    assert effective['username'] == '' and effective['password'] == 'password-only'
    assert effective['port'] == peer.port  # SSH group port does not override Telnet.
    reopened = ProfileDialog(saved, window, vault.folders())
    assert reopened.protocol.currentData() == 'telnet'
    window.show()
    window.open_profile(saved)
    qtbot.waitUntil(lambda: window.tabs.widget(0).session_status.state == 'connected')
    terminal = window.tabs.widget(0)
    peer.send(b'Password:')
    expected = b'one-time-password' if authentication == 'prompt_password' else b'password-only'
    qtbot.waitUntil(lambda: expected + b'\r\n' in peer.received)
    assert b'operator' not in peer.received
    assert 'TELNET' in window.session_status_label.text()
    assert 'Unencrypted' in window.tabs.tabToolTip(0)
    peer.socket.disconnectFromHost()
    qtbot.waitUntil(lambda: not terminal.is_running())
    window.reconnect_terminal(terminal)
    qtbot.waitUntil(lambda: window.tabs.widget(0).session_status.state == 'connected')
    assert window.tabs.count() == 1
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    active = window.tabs.widget(0)
    window.close()
    assert not active.transport.isRunning()
    assert active.session_status.state == 'disconnected'
    assert b'password-only' not in (tmp_path / 'config.db').read_bytes()
    assert prompted == ([('password',), ('password',)] if authentication == 'prompt_password' else [])


def test_connection_failure_and_cancel(qtbot, peer):
    # A closed local port yields a real refused connection, never success.
    peer.server.close()
    terminal = Terminal(telnet_profile(peer.port))
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: not terminal.is_running(), timeout=4000)
        assert terminal.session_status.state == 'error'
        assert terminal.session_status.connected_at is None
    finally:
        terminal.stop()
    pending = Terminal(telnet_profile(peer.port))
    qtbot.addWidget(pending)
    pending.stop()  # Close immediately, including before the worker starts.
    assert not pending.transport.isRunning()


def test_latin1_and_iac_escaping(qtbot, peer):
    profile = telnet_profile(peer.port)
    profile['telnet_options']['encoding'] = 'latin-1'
    terminal = Terminal(profile)
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected')
        peer.send(b'caf\xe9\xff\xff\r\n')
        qtbot.waitUntil(lambda: any('caféÿ' in line for line in terminal.screen.display))
        terminal.send('caféÿ\r'.encode('utf-8'))
        qtbot.waitUntil(lambda: b'caf\xe9\xff\xff\r\n' in peer.received)
    finally:
        terminal.stop()


def test_two_telnet_tabs_lock_disconnects_both(qtbot, tmp_path, peer, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox
    vault = Vault(tmp_path / 'lock.db', 'master')
    vault.save(telnet_profile(peer.port))
    window = MainWindow(vault, tmp_path / 'lock.db')
    qtbot.addWidget(window)
    window.show()
    saved = vault.profiles()[0]
    window.open_profile(saved)
    window.open_profile(saved)
    qtbot.waitUntil(lambda: all(window.tabs.widget(i).session_status.state == 'connected' for i in range(2)))
    terminals = [window.tabs.widget(i) for i in range(2)]
    terminals[0].send(b'first\r')
    terminals[1].send(b'second\r')
    qtbot.waitUntil(lambda: b'first\r\n' in peer.received and b'second\r\n' in peer.received)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)

    window.lock_vault()
    assert window.tabs.count() == 0 and window.vault is None
    assert all(not term.transport.isRunning() for term in terminals)
    window.unlock_panel.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert not window.isVisible()


def test_schema8_upgrade_keeps_shared_references(tmp_path):
    path = tmp_path / 'old.db'
    vault = Vault(path, 'master')
    reference = vault.save_credential('Router', 'admin', 'existing-secret')
    group = vault.save_folder('Routers', defaults={'credential_id': reference})
    original = telnet_profile(23)
    original.update(credential_source='inherit', folder_id=group)
    vault.save(original)
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN telnet_options')
    vault.connection.execute('ALTER TABLE credentials DROP COLUMN key_passphrase')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_reconnect_delay')
    vault.connection.execute('DROP TABLE ssh_private_keys')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_domain')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_advanced')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN connect_at_startup')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN authentication')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN before_connect_command')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN after_disconnect_command')
    vault.connection.execute('PRAGMA user_version = 8')
    vault.connection.commit()
    vault.close()
    vault = Vault(path, 'master')
    saved = vault.profiles()[0]
    assert saved['telnet_options'] == {}  # Manual login is the upgrade default.
    assert vault.effective_profile(saved)['password'] == 'existing-secret'
    assert vault.connection.execute('PRAGMA user_version').fetchone()[0] == 22
    vault.close()


def test_automatic_password_never_replaces_unencodable_characters(qtbot, peer):
    profile = telnet_profile(peer.port, 'password')
    profile['password'] = 'café-password'
    profile['telnet_options']['encoding'] = 'ascii'
    terminal = Terminal(profile)
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected')
        peer.send(b'Password:')
        qtbot.waitUntil(lambda: any('cannot be encoded' in line for line in terminal.screen.display))
        assert b'caf' not in peer.received
        assert terminal.is_running()  # User can continue manually.
        terminal.send(b'manual\r')
        qtbot.waitUntil(lambda: b'manual\r\n' in peer.received)
    finally:
        terminal.stop()


def test_custom_prompts_are_literal_fragmented_and_one_shot():
    login = PromptLogin('username_password', 'user', 'secret', 'Account[1]>', 'passwod:')
    assert login.feed('Login:') is None  # Custom prompt replaces automatic detection.
    assert login.feed('\r\nDevice \x1b[32mAcc') is None
    assert login.feed('ount[1]>\x1b[0m') == 'user'
    assert login.feed('\r\nPassword:') is None
    assert login.feed('\r\nPASS') is None
    assert login.feed('WOD: ') == 'secret'
    assert login.feed('\r\npasswod:') is None
    literal = PromptLogin('password', password='secret', password_prompt='[p.*]:')
    assert literal.feed('pxxx:') is None
    assert literal.feed('\r\n[p.*]:') == 'secret'
    manual = PromptLogin('manual', 'user', 'secret', 'login:', 'passwod:')
    assert manual.feed('login:') is None
    assert manual.feed('\r\npasswod:') is None


def test_custom_prompt_editor_encrypted_roundtrip(qtbot, tmp_path):
    from remote_manager.terminal.telnet import validate_options
    vault = Vault(tmp_path / 'prompts.db', 'master')
    editor = ProfileDialog(telnet_profile(23), save_callback=vault.save)
    qtbot.addWidget(editor)
    assert not editor.telnet_username_prompt.isEnabled()
    assert not editor.telnet_password_prompt.isEnabled()
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData('password'))
    assert not editor.telnet_username_prompt.isEnabled()
    assert editor.telnet_password_prompt.isEnabled()
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData('username_password'))
    editor.telnet_username_prompt.setText('private-login-marker:')
    editor.telnet_password_prompt.setText('private-password-prompt-marker:')
    editor.save()
    assert editor.result() == QDialog.DialogCode.Accepted
    vault.close()
    assert b'private-login-marker:' not in (tmp_path / 'prompts.db').read_bytes()
    assert b'private-password-prompt-marker:' not in (tmp_path / 'prompts.db').read_bytes()
    vault = Vault(tmp_path / 'prompts.db', 'master')
    reopened = ProfileDialog(vault.profiles()[0])
    qtbot.addWidget(reopened)
    assert reopened.telnet_username_prompt.text() == 'private-login-marker:'
    assert reopened.telnet_password_prompt.text() == 'private-password-prompt-marker:'
    for invalid in (None, 'x' * 257, 'prompt\n:', '\x1b[31mPassword:'):
        with pytest.raises(ValueError):
            validate_options({'password_prompt': invalid})
    vault.close()


@pytest.mark.parametrize('mode', ['password', 'username_password'])
def test_real_custom_prompts(qtbot, peer, mode):
    profile = telnet_profile(peer.port, mode)
    profile['telnet_options'].update(username_prompt='Account>', password_prompt='passwod:')
    terminal = Terminal(profile)
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected')
        peer.send(b'Username:\r\nPassword:')
        qtbot.wait(100)
        assert b'operator' not in peer.received and b'telnet-secret-marker' not in peer.received
        if mode == 'username_password':
            peer.send(b'\r\nAcc')
            QTimer.singleShot(15, lambda: peer.send(b'ount>'))
            qtbot.waitUntil(lambda: b'operator\r\n' in peer.received)
        peer.send(b'\r\npass')
        QTimer.singleShot(15, lambda: peer.send(b'wod:'))
        qtbot.waitUntil(lambda: b'telnet-secret-marker\r\n' in peer.received)
        if mode == 'password':
            assert b'operator' not in peer.received
        peer.send(b'\r\npasswod:')
        qtbot.wait(100)
        assert peer.received.count(b'telnet-secret-marker') == 1
    finally:
        terminal.stop()
