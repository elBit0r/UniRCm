"""Real loopback OpenSSH server, isolated keys/trust/config; no remote credentials."""
import getpass
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import time

import pytest
from PyQt6.QtCore import Qt

from remote_manager.terminal import ssh
from remote_manager.storage.vault import Vault
from remote_manager.ui.main_window import MainWindow


@pytest.fixture
def ssh_server(tmp_path, monkeypatch):
    sshd = shutil.which('sshd')
    if not sshd:
        pytest.skip('OpenSSH server required for real SSH test')
    for name in ('host', 'client'):
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(tmp_path / name)], check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = tmp_path / 'sshd_config'
    config.write_text(f'''ListenAddress 127.0.0.1
Port {port}
HostKey {tmp_path / 'host'}
PidFile {tmp_path / 'pid'}
AuthorizedKeysFile {tmp_path / 'client.pub'} {tmp_path / 'remote-home/.ssh/authorized_keys'}
PasswordAuthentication no
Subsystem sftp internal-sftp
KbdInteractiveAuthentication no
UsePAM no
# Ephemeral authorized_keys is under /tmp; production SSH defaults are unchanged.
StrictModes no
AllowUsers {getpass.getuser()}
''')
    trust = tmp_path / 'known_hosts'
    trust.write_text(f"[127.0.0.1]:{port} " + (tmp_path / 'host.pub').read_text())
    log = (tmp_path / 'server.log').open('w+')
    server = subprocess.Popen([sshd, '-D', '-e', '-f', str(config)], stdout=log, stderr=log)
    try:
        for _ in range(100):
            if server.poll() is not None:
                log.seek(0)
                pytest.fail(log.read())
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                time.sleep(.02)
        else:
            pytest.fail('Test SSH server did not start')
        original = ssh.ssh_command

        def isolated_command(profile):
            args = original(profile)
            index = args.index('--')
            return args[:index] + ['-o', f'UserKnownHostsFile={trust}', '-o', 'GlobalKnownHostsFile=/dev/null'] + args[index:]

        monkeypatch.setattr(ssh, 'ssh_command', isolated_command)
        yield dict(name='Loopback', host='127.0.0.1', username=getpass.getuser(),
                   port=port, identity_file=str(tmp_path / 'client'))
    finally:
        server.terminate()
        server.wait(timeout=5)
        log.close()


def test_two_real_ssh_tabs(qtbot, tmp_path, ssh_server):
    path = tmp_path / 'db' / 'connections.db'
    vault = Vault(path, 'master password')
    profile_id = vault.save(ssh_server)
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    window.refresh(profile_id)
    window.connect_profile()
    window.connect_profile()
    assert window.tabs.count() == 2
    for index in range(2):
        assert not window.tabs.tabIcon(index).isNull()
        assert window.tabs.tabToolTip(index).startswith('SSH — ')
    terminals = [window.tabs.widget(i) for i in range(2)]
    try:
        for index, terminal in enumerate(terminals):
            marker = f'REAL_SSH_TAB_{index}'
            terminal.send(f"printf '\\n%s\\n' '{marker}'; stty size\r".encode())
            qtbot.waitUntil(lambda t=terminal, m=marker: any(line.strip() == m for line in t.screen.display), timeout=15000)
            assert terminal.process.poll() is None
        window.tabs.setCurrentIndex(0)
        qtbot.waitUntil(lambda: terminals[0].isVisible())
        old_columns = terminals[0].screen.columns
        window.resize(window.width() + 200, window.height() + 100)
        qtbot.waitUntil(lambda: terminals[0].screen.columns != old_columns)
        rows, columns = terminals[0].screen.lines, terminals[0].screen.columns
        terminals[0].send(b'stty size\r')
        qtbot.waitUntil(lambda: any(line.strip() == f'{rows} {columns}' for line in terminals[0].screen.display))
        # Keyboard input, ANSI, resize, process exit and cleanup on the real PTY.
        terminals[0].setFocus()
        qtbot.keyClicks(terminals[0], "printf '\\033[31mCOLOR_OK\\033[0m\\n'")
        qtbot.keyClick(terminals[0], Qt.Key.Key_Return)
        qtbot.waitUntil(lambda: any(line.strip() == 'COLOR_OK' for line in terminals[0].screen.display))
        assert any(char.fg == 'red' for line in terminals[0].screen.buffer.values() for char in line.values())
        qtbot.keyClick(terminals[0], Qt.Key.Key_Up)
        qtbot.keyClick(terminals[0], Qt.Key.Key_C, modifier=Qt.KeyboardModifier.ControlModifier)
        qtbot.wait(150)  # Allow the remote TTY to process SIGINT before the next command.
        terminals[0].send(b'exit 7\r')
        qtbot.waitUntil(lambda: '[exit 7]' in window.tabs.tabText(0), timeout=5000)
        assert not window.tabs.tabIcon(0).isNull()
        assert window.tabs.tabToolTip(0) == 'SSH — process exited with code 7'
        window.close_tab(1, confirm=False)
        assert terminals[1].process.poll() is not None
        assert terminals[1].fd is None
    finally:
        for terminal in terminals:
            terminal.stop()
        window.close()


def test_imported_key_real_ssh(qtbot, tmp_path, ssh_server, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog
    from remote_manager.storage.archive import ArchiveVault
    from remote_manager.ui.dialogs import ProfileDialog

    client_key = Path(ssh_server['identity_file'])
    passphrase = 'synthetic imported key passphrase'
    subprocess.run(['ssh-keygen', '-p', '-f', str(client_key)],
                   input=f'{passphrase}\n{passphrase}\n', text=True, start_new_session=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    key_data = client_key.read_bytes()
    path = tmp_path / 'connections.uni'
    vault = ArchiveVault(path, 'master password', description='')
    profile_id = vault.save(dict(ssh_server, key_passphrase=passphrase))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(client_key), ''))
    dialog = ProfileDialog(vault.profiles(profile_id)[0], save_callback=vault.save)
    qtbot.addWidget(dialog)
    dialog.import_key()
    assert dialog.imported_key_name == client_key.name, dialog.error.text()
    dialog.save()
    assert dialog.profile['identity_file'] == ''
    assert 'imported_key' not in dialog.profile
    client_key.unlink()
    vault.close()
    assert key_data.splitlines()[1] not in path.read_bytes()

    vault = ArchiveVault(path, 'master password')
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.refresh(profile_id)
    window.connect_profile()
    terminal = window.tabs.widget(0)
    try:
        assert terminal is not None
        memory_path = Path(terminal.process.args[terminal.process.args.index('-i') + 1])
        assert memory_path.is_file()
        assert passphrase not in repr(terminal.process.args)
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected', timeout=15000)
        assert terminal.key_fd is None
        assert not memory_path.exists()
        terminal.send(b"printf '\\n%s\\n' 'IMPORTED_KEY_OK'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'IMPORTED_KEY_OK' for line in terminal.screen.display))
        profile = vault.profiles(profile_id)[0]
        copy_id = vault.copy_profile(profile_id, None)
        assert vault.ssh_private_key(vault.profiles(copy_id)[0]) == key_data
        edit_dialog = ProfileDialog(profile, save_callback=vault.save)
        qtbot.addWidget(edit_dialog)
        edit_dialog.remove_key()
        edit_dialog.save()
        assert vault.ssh_private_key(profile) is None
        vault.delete(copy_id)
        assert vault.connection.execute('SELECT count(*) FROM ssh_private_keys').fetchone()[0] == 0
    finally:
        window.close_tab(0, confirm=False)
        window.close()


def test_installs_vault_public_key_for_future_ssh_logins(qtbot, tmp_path, ssh_server, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from remote_manager.storage.archive import ArchiveVault
    from remote_manager.terminal.private_key import read_imported_key

    home = tmp_path / 'remote-home'
    authorized = home / '.ssh' / 'authorized_keys'
    authorized.parent.mkdir(parents=True, mode=0o700)
    original = b'# Existing remote authorization file'
    authorized.write_bytes(original)
    install_arguments = ssh.install_arguments

    def test_home(socket_path, host):
        args = install_arguments(socket_path, host)
        args[-1] = f'HOME={shlex.quote(str(home))} ' + args[-1]
        return args

    monkeypatch.setattr(ssh, 'install_arguments', test_home)
    path = tmp_path / 'portable.uni'
    vault = ArchiveVault(path, 'master password', description='')
    profile_id = vault.save(ssh_server)
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.show()
    terminal = window.open_profile(vault.profiles(profile_id)[0])
    try:
        qtbot.waitUntil(terminal.can_install_public_key, timeout=15000)
        key_path = tmp_path / 'portable-key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key_path)], check=True)
        passphrase = 'synthetic portable key passphrase'
        subprocess.run(['ssh-keygen', '-p', '-f', str(key_path)], input=f'{passphrase}\n{passphrase}\n',
                       text=True, start_new_session=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        expected_key = b' '.join(key_path.with_suffix('.pub').read_bytes().split()[:2])
        fingerprint = subprocess.check_output(['ssh-keygen', '-l', '-f', str(key_path.with_suffix('.pub'))],
                                              text=True).split()[1]
        profile = vault.profiles(profile_id)[0]
        vault.save(dict(profile, identity_file='', imported_key=read_imported_key(key_path),
                        key_passphrase=passphrase))
        key_path.unlink()
        key_path.with_suffix('.pub').unlink()

        def confirm(box):
            assert box.informativeText() == fingerprint
            assert ssh_server['host'] in box.text()
            next(button for button in box.buttons() if box.buttonRole(button) == box.ButtonRole.AcceptRole).click()

        monkeypatch.setattr(QMessageBox, 'exec', confirm)
        with qtbot.waitSignal(terminal.public_key_install_finished, timeout=10000) as result:
            window.install_vault_public_key(terminal)
        assert result.args == ['installed']
        assert authorized.read_bytes() == original + b'\n' + expected_key + b'\n'
        assert authorized.stat().st_mode & 0o777 == 0o600

        restricted = original + b'\nrestrict,command="echo one two" ' + expected_key + b'\n'
        authorized.write_bytes(restricted)
        with qtbot.waitSignal(terminal.public_key_install_finished, timeout=10000) as result:
            window.install_vault_public_key(terminal)
        assert result.args == ['exists']
        assert authorized.read_bytes() == restricted

        authorized.write_bytes(original + b'\n' + expected_key + b'\n')
        window.close_tab(0, confirm=False)
        Path(ssh_server['identity_file']).unlink()
        Path(ssh_server['identity_file']).with_suffix('.pub').unlink()
        new_terminal = window.open_profile(vault.profiles(profile_id)[0])
        qtbot.waitUntil(lambda: new_terminal.session_status.state == 'connected', timeout=15000)
        new_terminal.send(b"printf '\\n%s\\n' KEY_LOGIN_OK\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'KEY_LOGIN_OK' for line in new_terminal.screen.display))
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()


def test_ssh_arguments_keep_authentication_safe():
    profile = dict(host='host.example', port=22, username='user', identity_file='')
    args = ssh.ssh_command(profile)
    assert 'StrictHostKeyChecking=ask' in args
    assert 'ForwardAgent=no' in args
    assert args[-2:] == ['--', 'host.example']
    for host in ('-oProxyCommand=bad', 'host\noption'):
        with pytest.raises(ValueError):
            ssh.ssh_command(dict(profile, host=host))


def test_real_ssh_fullscreen_editor_and_mouse(qtbot, tmp_path, ssh_server):
    from PyQt6.QtCore import QPoint

    if not shutil.which('vi'):
        pytest.skip('vi required for full-screen SSH test')
    terminal = ssh.Terminal(ssh_server)
    qtbot.addWidget(terminal)
    terminal.resize(900, 600)
    terminal.show()
    try:
        terminal.send(b"printf '\\nSHELL_BEFORE_EDITOR\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'SHELL_BEFORE_EDITOR' for line in terminal.screen.display), timeout=15000)
        filename = tmp_path / 'ssh-editor.txt'
        terminal.send(f'vi -Nu NONE -n -i NONE {shlex.quote(str(filename))}\r'.encode())
        qtbot.waitUntil(lambda: terminal.screen.is_alternate, timeout=5000)
        terminal.send(b'iSaved through real SSH')
        qtbot.keyClick(terminal, Qt.Key.Key_Escape)
        terminal.send(b':wq\r')
        qtbot.waitUntil(lambda: not terminal.screen.is_alternate, timeout=5000)
        assert filename.read_text() == 'Saved through real SSH\n'
        assert any(line.strip() == 'SHELL_BEFORE_EDITOR' for line in terminal.screen.display)

        # Ask a real remote process for SGR mouse events; verify bytes received.
        script = '''import os,termios,tty
old=termios.tcgetattr(0)
try:
 tty.setraw(0)
 os.write(1,b'\\x1b[?1000h\\x1b[?1006h')
 data=b''
 while not data.endswith(b'm'):
  data+=os.read(0,128)
finally:
 os.write(1,b'\\x1b[?1000l\\x1b[?1006l')
 termios.tcsetattr(0,termios.TCSADRAIN,old)
print('\\nREMOTE_MOUSE_HEX='+data.hex(),flush=True)
'''
        terminal.send(('python3 -c ' + shlex.quote(script) + '\r').encode())
        qtbot.waitUntil(terminal.mouse_reporting, timeout=5000)
        pos = QPoint(terminal.cell_w * 2, terminal.cell_h * 3)
        qtbot.mouseClick(terminal, Qt.MouseButton.LeftButton, pos=pos)
        expected = (b'\x1b[<0;3;4M\x1b[<0;3;4m').hex()
        qtbot.waitUntil(lambda: any('REMOTE_MOUSE_HEX=' + expected in line for line in terminal.screen.display), timeout=5000)
        assert not terminal.mouse_reporting()
    finally:
        terminal.stop()


def test_real_mc_f10_returns_to_shell(qtbot, ssh_server):
    if not shutil.which('mc'):
        pytest.skip('mc required for F10 regression test')
    terminal = ssh.Terminal(ssh_server)
    qtbot.addWidget(terminal)
    terminal.resize(900, 600)
    terminal.show()
    try:
        terminal.send(b"mc -u; printf '\\nMC_EXIT_%s\\n' \"$?\"\r")
        qtbot.waitUntil(lambda: terminal.screen.is_alternate, timeout=15000)
        qtbot.keyClick(terminal, Qt.Key.Key_F10)
        qtbot.waitUntil(lambda: any(line.strip() == 'MC_EXIT_0' for line in terminal.screen.display), timeout=10000)
        assert not terminal.screen.is_alternate
        assert terminal.process.poll() is None
    finally:
        terminal.stop()


def test_real_encrypted_private_key(qtbot, tmp_path, ssh_server):
    paramiko = pytest.importorskip('paramiko')
    key_path = Path(ssh_server['identity_file'])
    # Generate an encrypted key in-process; never put its passphrase in argv/env.
    key = paramiko.RSAKey.generate(2048)
    phrase = 'private-key-passphrase-marker'
    key.write_private_key_file(str(key_path), password=phrase)
    key_path.with_suffix('.pub').write_text(f'{key.get_name()} {key.get_base64()}\n')
    terminal = ssh.Terminal(dict(ssh_server, key_passphrase=phrase))
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected', timeout=10000)
        assert terminal.askpass.key_passphrase == ''
        assert phrase not in repr(terminal.process.args)
        terminal.send(b"printf 'ENCRYPTED_KEY_OK\\n'\r")
        qtbot.waitUntil(lambda: any('ENCRYPTED_KEY_OK' in row for row in terminal.screen.display))
    finally:
        terminal.stop()


def test_saved_key_passphrase_cannot_answer_remote_keyboard_challenges():
    profile = dict(host='localhost', username='user', port=22, identity_file='/private/key', key_passphrase='secret')
    args = ssh.ssh_command(profile)
    assert 'KbdInteractiveAuthentication=no' in args
    assert 'secret' not in args
    assert 'KbdInteractiveAuthentication=no' not in ssh.ssh_command(dict(profile, key_passphrase=''))


def test_real_ssh_modified_fullscreen_keys(qtbot, ssh_server):
    import shlex
    terminal = ssh.Terminal(ssh_server)
    qtbot.addWidget(terminal)
    terminal.resize(900, 600)
    terminal.show()
    expected = b'\x1b[1;5P\x1b[15;2~\x1b[24;3~\x1b[3;5~'
    script = f'''import os,termios,tty
old=termios.tcgetattr(0)
try:
 tty.setraw(0)
 os.write(1,b'\\x1b[?1049h\\x1b[?1h')
 data=b''
 while len(data)<{len(expected)}:
  data+=os.read(0,128)
finally:
 os.write(1,b'\\x1b[?1049l\\x1b[?1l')
 termios.tcsetattr(0,termios.TCSADRAIN,old)
print('\\nKEY_HEX='+data.hex(),flush=True)
'''
    try:
        terminal.send(('python3 -c ' + shlex.quote(script) + '\r').encode())
        qtbot.waitUntil(lambda: terminal.screen.is_alternate, timeout=15000)
        for key, modifier in ((Qt.Key.Key_F1, Qt.KeyboardModifier.ControlModifier),
                              (Qt.Key.Key_F5, Qt.KeyboardModifier.ShiftModifier),
                              (Qt.Key.Key_F12, Qt.KeyboardModifier.AltModifier),
                              (Qt.Key.Key_Delete, Qt.KeyboardModifier.ControlModifier)):
            qtbot.keyClick(terminal, key, modifier=modifier)
        qtbot.waitUntil(lambda: any('KEY_HEX=' + expected.hex() in line for line in terminal.screen.display), timeout=5000)
        assert not terminal.screen.is_alternate
    finally:
        terminal.stop()


@pytest.mark.parametrize('quick_connect', [False, True], ids=['saved-profile', 'quick-connect'])
def test_requested_ssh_username_with_key_authentication(qtbot, tmp_path, ssh_server, monkeypatch, quick_connect):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog
    from remote_manager.ui.credentials import ConnectionAuthenticationDialog

    path = tmp_path / 'prompt.db'
    vault = Vault(path, 'master')
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    opened = []

    def enter_username(dialog):
        def submit():
            opened.append(tuple(dialog.inputs))
            dialog.inputs['username'].setText(ssh_server['username'])
            dialog.connect_button.click()

        QTimer.singleShot(0, submit)
        return QDialog.exec(dialog)

    monkeypatch.setattr(ConnectionAuthenticationDialog, 'exec', enter_username)
    if quick_connect:
        # Supply the test identity through OpenSSH, as with a user's SSH configuration.
        isolated_command = ssh.ssh_command
        monkeypatch.setattr(ssh, 'ssh_command', lambda profile: isolated_command(
            dict(profile, identity_file=ssh_server['identity_file'])))
        window.quick_host.setText(ssh_server['host'])
        window.quick_port.setValue(ssh_server['port'])
        window.quick_connect_action.trigger()
        terminal = window.tabs.currentWidget()
    else:
        profile_id = vault.save(dict(ssh_server, username='saved-user', password='saved-password',
                                     authentication='prompt_both'))
        terminal = window.open_profile(vault.profiles(profile_id)[0])
    try:
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected', timeout=10000)
        assert opened == [('username',)]
        assert terminal.askpass is None
        if quick_connect:
            assert terminal.profile_id is None
            assert not vault.profiles()
        else:
            assert vault.profiles(profile_id)[0]['username'] == 'saved-user'
    finally:
        window.close_tab(0, confirm=False)
        window.close()


def test_local_commands_run_before_ssh_and_after_disconnection(qtbot, tmp_path, ssh_server):
    from shlex import quote

    output = tmp_path / 'local commands'
    target = quote(str(output))
    terminal = ssh.Terminal(dict(
        ssh_server,
        before_connect_command=f'printf before > {target}',
        after_disconnect_command=f'printf after >> {target}; exit 8',
    ))
    qtbot.addWidget(terminal)
    try:
        assert terminal.process is None
        qtbot.waitUntil(lambda: terminal.file_transfer_available(), timeout=10000)
        qtbot.waitUntil(lambda: terminal.session_status.state == 'connected')
        assert output.read_text() == 'before'
        terminal.send(b'exit\r')
        qtbot.waitUntil(lambda: not terminal.is_running())
        qtbot.waitUntil(lambda: output.read_text() == 'beforeafter')
        qtbot.waitUntil(lambda: any('exited with code 8' in line for line in terminal.screen.display))
    finally:
        terminal.stop()


def test_startup_commands_run_in_authenticated_shell(qtbot, tmp_path, ssh_server):
    vault = Vault(tmp_path / 'private' / 'connections.db', 'master')
    commands = "startup_value=UNICODE_è\nprintf '%s\\n' \"$startup_value\""
    profile_id = vault.save(dict(ssh_server, ssh_startup_commands=commands))
    profile = vault.profiles(profile_id)[0]
    vault.close()
    assert profile['ssh_startup_commands'] == commands
    terminal = ssh.Terminal(profile)
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: any(line.strip() == 'UNICODE_è' for line in terminal.screen.display),
                        timeout=10000)
        assert terminal.session_status.state == 'connected'
        terminal.send(b'printf "interactive_%s\\n" "$startup_value"\r')
        qtbot.waitUntil(lambda: any(line.strip() == 'interactive_UNICODE_è' for line in terminal.screen.display))
    finally:
        terminal.stop()


def test_startup_commands_are_not_sent_if_authentication_fails(qtbot, ssh_server, monkeypatch):
    isolated_command = ssh.ssh_command
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [
        'ssh', '-o', 'BatchMode=yes', *isolated_command(profile)[1:],
    ])
    sent = []
    monkeypatch.setattr(ssh.Terminal, 'send', lambda terminal, data: sent.append(data))
    terminal = ssh.Terminal(dict(ssh_server, username=ssh_server['username'] + '-invalid',
                                 ssh_startup_commands='echo hello'))
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: terminal.session_status.ended_at is not None, timeout=10000)
        assert terminal.session_status.connected_at is None
        assert not sent
    finally:
        terminal.stop()
