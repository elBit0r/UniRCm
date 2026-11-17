import pytest
from remote_manager.storage.vault import Vault, resolve_ssh
from remote_manager.terminal.ssh import ssh_command
from remote_manager.ui.dialogs import ProfileDialog, GroupDefaultsDialog
from remote_manager.ssh_options import validate_advanced

BASE = dict(name='Advanced', host='localhost', username='', identity_file='', port=22)
OPTIONS = dict(proxy_jump='user@bastion.example:2222,[::1]:22', alive_interval=45,
               alive_count=4, identities_only='yes', address_family='inet', compression='yes', extra_options='-o HostKeyAlgorithms=+ssh-rsa\n-oKexAlgorithms=+diffie-hellman-group14-sha1')


def test_encrypted_migration_and_group_inheritance(tmp_path):
    path = tmp_path / 'advanced.db'
    vault = Vault(path, 'master')
    pid = vault.save(BASE)
    # Reconstruct the previous schema to verify upgrade without losing profiles.
    with vault.connection:
        vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
        vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_domain')
        vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_advanced')
        vault.connection.execute('DROP TABLE ssh_private_keys')
        vault.connection.execute('PRAGMA user_version=13')
    vault.close()
    vault = Vault(path, 'master')
    assert vault.profiles(pid)[0]['ssh_advanced'] == {}
    root = vault.save_folder('Root')
    child = vault.save_folder('Child', root)
    vault.set_folder_defaults(root, {'ssh_advanced': OPTIONS})
    saved = vault.profiles(pid)[0]
    saved.update(folder_id=child, ssh_modes={'ssh_advanced': 'inherit'})
    vault.save(saved)
    assert vault.effective_profile(vault.profiles(pid)[0])['ssh_advanced'] == OPTIONS
    vault.set_folder_defaults(child, {'ssh_advanced': None})
    assert vault.effective_profile(vault.profiles(pid)[0])['ssh_advanced'] == {}
    saved.update(ssh_advanced=OPTIONS, ssh_modes={'ssh_advanced': 'override'})
    vault.save(saved)
    copy_id = vault.copy_profile(pid, None)
    vault.close()
    assert b'bastion.example' not in path.read_bytes()
    vault = Vault(path, 'master')
    assert vault.profiles(copy_id)[0]['ssh_advanced'] == OPTIONS
    vault.close()


def test_editor_roundtrip_and_command(qtbot):
    dialog = ProfileDialog(dict(BASE, ssh_advanced=OPTIONS))
    qtbot.addWidget(dialog)
    assert dialog.ssh_advanced.options() == OPTIONS
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted
    args = ssh_command(dialog.profile)
    for option in ('ProxyJump=user@bastion.example:2222,[::1]:22', 'ServerAliveInterval=45',
                   'ServerAliveCountMax=4', 'IdentitiesOnly=yes', 'AddressFamily=inet', 'Compression=yes',
                   'StrictHostKeyChecking=ask', 'ForwardAgent=no', 'HostKeyAlgorithms=+ssh-rsa', 'KexAlgorithms=+diffie-hellman-group14-sha1'):
        assert args.count(option) == 1
    assert 'ServerAliveInterval=30' not in args
    group = GroupDefaultsDialog(dict(name='Group', ssh_defaults={'ssh_advanced': OPTIONS}))
    qtbot.addWidget(group)
    group.save()
    assert group.defaults['ssh_advanced'] == OPTIONS
    mode, field = group.fields['ssh_advanced']
    mode.setCurrentIndex(mode.findData('inherit'))
    assert not field.isEnabled()
    mode.setCurrentIndex(mode.findData('override'))
    assert field.isEnabled()
    dialog.protocol.setCurrentIndex(dialog.protocol.findData('telnet'))
    assert not dialog.tabs.isTabEnabled(dialog.tabs.indexOf(dialog.advanced_page))
    assert dialog.tabs.isTabEnabled(dialog.tabs.indexOf(dialog.telnet_page))


@pytest.mark.parametrize('options', [dict(proxy_jump='host;touch /tmp/x'), dict(proxy_jump='-evil'),
    dict(proxy_jump='user:password@host'), dict(proxy_jump='host:65536'), dict(alive_interval=-1),
    dict(alive_count=True), dict(compression='invalid'), dict(extra_args='-F file')])
def test_reject_invalid_advanced_options(options):
    with pytest.raises(ValueError):
        validate_advanced(options)
    with pytest.raises(ValueError):
        ssh_command(dict(BASE, ssh_advanced=options))


from test_ssh import ssh_server


def test_real_ssh_advanced_via_jump_host(qtbot, tmp_path, ssh_server, monkeypatch):
    from remote_manager.terminal import ssh
    config = tmp_path / 'jump_config'
    config.write_text(f'''Host test-bastion
    HostName 127.0.0.1
    Port {ssh_server['port']}
    User {ssh_server['username']}
    IdentityFile "{ssh_server['identity_file']}"
    IdentitiesOnly yes
    UserKnownHostsFile "{tmp_path / 'known_hosts'}"
    GlobalKnownHostsFile /dev/null
    StrictHostKeyChecking yes
''')
    original = ssh.ssh_command
    def command(profile):
        args = original(profile)
        index = args.index('--')
        return args[:index] + ['-F', str(config)] + args[index:]
    monkeypatch.setattr(ssh, 'ssh_command', command)
    term = ssh.Terminal(dict(ssh_server, ssh_advanced=dict(OPTIONS, proxy_jump='test-bastion')))
    qtbot.addWidget(term)
    term.resize(900, 500)
    term.show()
    try:
        term.send(b"printf '\\nADVANCED_SSH_OK\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'ADVANCED_SSH_OK' for line in term.screen.display), timeout=15000)
        assert term.is_running()
    finally:
        term.stop()


@pytest.mark.parametrize('text', [
    '-o StrictHostKeyChecking=no', '-o UserKnownHostsFile=/dev/null',
    '-o ProxyCommand=bad', '-o LocalCommand=bad', '-F config',
    '-o ControlPath=/tmp/socket', '-o LogLevel=QUIET', '-o KbdInteractiveAuthentication=yes',
    '-o SetEnv=PASSWORD=secret', 'host command', '-o Ciphers=aes128-ctr;touch',
    '-o Ciphers=aes128-ctr -o ciphers=aes256-ctr', '-o "unterminated', '-o',
])
def test_extra_options_reject_unsafe_or_ambiguous_input(text):
    with pytest.raises(ValueError):
        ssh_command(dict(BASE, ssh_advanced={'extra_options': text}))


def test_extra_options_quoting_and_editor_error(qtbot):
    from remote_manager.ssh_options import extra_arguments
    assert extra_arguments('-o "RekeyLimit=1G 1h" -oMACs=+hmac-sha1') == [
        '-o', 'RekeyLimit=1G 1h', '-o', 'MACs=+hmac-sha1']
    editor = ProfileDialog(BASE)
    qtbot.addWidget(editor)
    field = editor.ssh_advanced.fields['extra_options']
    assert 'HostKeyAlgorithms=+ssh-rsa' in field.toolTip()
    field.setPlainText('-o ProxyCommand=bad')
    editor.save()
    assert editor.result() != editor.DialogCode.Accepted
    assert editor.error.text()
