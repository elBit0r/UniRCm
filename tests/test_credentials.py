"""Credential encryption and the real ASKPASS helper IPC boundary."""
import os
from pathlib import Path
import subprocess
import pytest

from PyQt6.QtWidgets import QWidget, QLineEdit

from remote_manager.storage.vault import Vault
from remote_manager.terminal.askpass import AskpassBridge
from remote_manager.ui.dialogs import ProfileDialog


def test_common_credentials_encrypted_roundtrip(qtbot, tmp_path):
    vault = Vault(tmp_path / 'vault.db', 'master')
    dialog = ProfileDialog()
    qtbot.addWidget(dialog)
    dialog.fields['name'].setText('Password connection')
    dialog.fields['host'].setText('localhost')
    source = dialog.ssh_modes['username']
    source.setCurrentIndex(source.findData('default'))
    assert source.currentData() == 'default'
    assert not dialog.fields['username'].isEnabled()
    source.setCurrentIndex(source.findData('inherit'))
    assert source.currentData() == 'inherit'
    assert not dialog.fields['username'].isEnabled()
    source.setCurrentIndex(source.findData('override'))
    assert dialog.fields['username'].isEnabled()
    dialog.credentials.username.setText('tester')
    secret = '  remote-secret-with-spaces  '
    dialog.credentials.password.setText(secret)
    assert dialog.credentials.password.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.credentials.parentWidget() is not dialog.tabs.widget(1)
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted
    pid = vault.save(dialog.profile)
    stored = vault.profiles()[0]
    reference = stored['credential_id']
    assert vault.credential(reference)['username'] == 'tester'
    assert stored['password'] == secret
    reopened = ProfileDialog(stored)
    qtbot.addWidget(reopened)
    assert reopened.credentials.password.text() == secret
    stored['password'] = 'changed-password'
    vault.save(stored)
    assert vault.profiles()[0]['credential_id'] == reference
    vault.close()
    assert secret.encode() not in (tmp_path / 'vault.db').read_bytes()
    assert b'changed-password' not in (tmp_path / 'vault.db').read_bytes()
    vault = Vault(tmp_path / 'vault.db', 'master')
    assert vault.profiles()[0]['password'] == 'changed-password'
    original = vault.profiles()[0]
    copy_id = vault.save(dict(original, id=None, credential_id=None, name='Copy'))
    copy = next(p for p in vault.profiles() if p['id'] == copy_id)
    assert copy['credential_id'] != reference
    copy['password'] = 'independent-copy-password'
    vault.save(copy)
    assert vault.credential(reference)['password'] == 'changed-password'
    vault.delete(copy_id)
    vault.delete(pid)
    assert vault.credential(reference) is None
    vault.close()


def test_askpass_private_helper_and_host_confirmation(qtbot, monkeypatch):
    from remote_manager.terminal import askpass
    parent = QWidget()
    qtbot.addWidget(parent)
    secret = 'secret for IPC only'
    bridge = AskpassBridge(secret, parent)
    address, helper = bridge.address, bridge.helper
    prompts = []

    def answer(parent, title, prompt, echo):
        prompts.append(prompt)
        return ('yes' if 'yes/no' in prompt else 'manual-retry'), True

    monkeypatch.setattr(askpass.QInputDialog, 'getText', answer)
    environment = dict(os.environ, **bridge.environment())
    assert secret not in repr(environment)
    assert secret not in Path(helper).read_text()
    assert Path(helper).stat().st_mode & 0o777 == 0o700
    assert Path(helper).parent.stat().st_mode & 0o777 == 0o700

    def request(prompt):
        process = subprocess.Popen([helper, prompt], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=5000)
        output, errors = process.communicate()
        assert process.returncode == 0, errors.decode()
        return output

    try:
        fingerprint_prompt = 'Unknown host\nFingerprint SHA256:EXAMPLE\nContinue connecting (yes/no)?'
        assert request(fingerprint_prompt) == b'yes\n'
        assert prompts == [fingerprint_prompt]
        assert bridge.password == secret
        assert request("tester@localhost's password: ") == (secret + '\n').encode()
        assert bridge.password == ''
        assert request("tester@localhost's password: ") == b'manual-retry\n'
    finally:
        bridge.close()
    assert not Path(address).exists()
    assert not Path(helper).exists()


@pytest.mark.parametrize('credential_source', ['local', 'shared', 'inherit'])
def test_real_ssh_password_login(qtbot, tmp_path, monkeypatch, credential_source):
    """OpenSSH client against a real loopback SSH password-auth server."""
    import hmac
    import socket
    import threading
    import pytest
    paramiko = pytest.importorskip('paramiko', reason='Optional loopback password SSH server')
    from remote_manager.terminal import ssh

    secret = '  real-ssh-password  '
    authenticated = threading.Event()
    shell = threading.Event()
    failures = []

    class Server(paramiko.ServerInterface):
        def get_allowed_auths(self, username):
            return 'password'

        def check_auth_password(self, username, password):
            if username == 'tester' and hmac.compare_digest(password, secret):
                authenticated.set()
                return paramiko.AUTH_SUCCESSFUL
            return paramiko.AUTH_FAILED

        def check_channel_request(self, kind, channel_id):
            return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_pty_request(self, *args):
            return True

        def check_channel_shell_request(self, channel):
            shell.set()
            return True

    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    port = listener.getsockname()[1]
    trust = tmp_path / 'known_hosts'
    trust.write_text(f'[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n')

    def serve():
        transport = None
        try:
            connection, _ = listener.accept()
            transport = paramiko.Transport(connection)
            transport.add_server_key(key)
            transport.start_server(server=Server())
            channel = transport.accept(10)
            if channel is None or not shell.wait(10):
                raise RuntimeError('SSH shell was not established')
            channel.sendall(b'PASSWORD_AUTHENTICATED\r\n')
            channel.settimeout(10)
            command = channel.recv(1024)
            if b'check-session' not in command:
                raise RuntimeError('SSH session did not receive terminal input')
            channel.sendall(b'SESSION_INPUT_RECEIVED\r\n')
            channel.send_exit_status(0)
            channel.close()
        except Exception as error:
            failures.append(error)
        finally:
            if transport:
                transport.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    original = ssh.ssh_command

    def command(profile):
        args = original(profile)
        index = args.index('--')
        return args[:index] + ['-F', '/dev/null', '-o', f'UserKnownHostsFile={trust}',
                              '-o', 'GlobalKnownHostsFile=/dev/null',
                              '-o', 'StrictHostKeyChecking=yes', '-o', 'PubkeyAuthentication=no',
                              '-o', 'PreferredAuthentications=password'] + args[index:]

    monkeypatch.setattr(ssh, 'ssh_command', command)
    vault = Vault(tmp_path / 'authentication.db', 'master')
    profile = dict(name='Real SSH', host='127.0.0.1', port=port, username='tester', password=secret, identity_file='', credential_source=credential_source)
    if credential_source != 'local':
        reference = vault.save_credential('SSH test', 'tester', secret)
        if credential_source == 'shared':
            profile['credential_id'] = reference
        else:
            profile['folder_id'] = vault.save_folder('SSH group', defaults={'credential_id': reference})
    vault.save(profile)
    terminal = ssh.Terminal(vault.effective_profile(vault.profiles()[0]))
    vault.close()
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(lambda: any('PASSWORD_AUTHENTICATED' in line for line in terminal.screen.display), timeout=10000)
        assert authenticated.is_set()
        assert terminal.session_status.state == 'connected'
        assert terminal.session_status.duration() is not None
        assert terminal.askpass.password == ''
        assert secret not in repr(terminal.process.args)
        terminal.send(b'check-session\r')
        qtbot.waitUntil(lambda: terminal.process.poll() is not None, timeout=10000)
        assert terminal.process.returncode == 0
        qtbot.waitUntil(lambda: terminal.session_status.state == 'disconnected')
        assert terminal.session_status.exit_code == 0
        assert not failures
    finally:
        terminal.stop()
        listener.close()
        thread.join(timeout=2)


def test_key_passphrase_askpass_is_bound_to_identity(qtbot, tmp_path, monkeypatch):
    from remote_manager.terminal import askpass
    parent = QWidget()
    qtbot.addWidget(parent)
    identity = tmp_path / 'private-key'
    phrase = 'key-passphrase-marker'
    bridge = AskpassBridge('', parent, phrase, str(identity))
    monkeypatch.setattr(askpass.QInputDialog, 'getText', lambda *a: ('manual', True))
    environment = dict(os.environ, **bridge.environment())
    assert phrase not in repr(environment) and phrase not in Path(bridge.helper).read_text()
    def request(prompt):
        process = subprocess.Popen([bridge.helper, prompt], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        qtbot.waitUntil(lambda: process.poll() is not None, timeout=5000)
        result, error = process.communicate()
        assert process.returncode == 0, error.decode()
        return result
    try:
        assert request("Enter passphrase for key '/other/key': ") == b'manual\n'
        assert bridge.key_passphrase == phrase
        assert request(f"Enter passphrase for key '{identity}': ") == (phrase + '\n').encode()
        assert bridge.key_passphrase == ''
        assert request(f"Enter passphrase for key '{identity}': ") == b'manual\n'
    finally:
        bridge.close()
