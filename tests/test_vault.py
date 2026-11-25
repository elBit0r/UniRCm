import sqlite3
import stat

import pytest

from remote_manager.storage.vault import Vault, sqlcipher


@pytest.mark.parametrize('password', ['master', 'incorrect'])
def test_legacy_vault_preserves_shared_directory_permissions(tmp_path, password):
    directory = tmp_path / 'shared'
    directory.mkdir()
    path = directory / 'legacy.db'
    Vault(path, 'master').close()
    directory.chmod(0o755)

    if password == 'master':
        Vault(path, password).close()
    else:
        with pytest.raises(sqlcipher.DatabaseError):
            Vault(path, password)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_encrypted_profile_crud_and_unlock(tmp_path):
    path = tmp_path / 'private' / 'connections.db'
    password = "master ' secret"
    vault = Vault(path, password)
    profile = dict(name='private-profile-marker', host='secret-host.example', port=22,
                   username='private-user', password='remote-password-marker', identity_file='/private/key',
                   before_connect_command='echo before-command-marker',
                   ssh_startup_commands='echo remote-command-marker\npwd',
                   after_disconnect_command='echo after-command-marker')
    profile_id = vault.save(profile)
    vault.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    data = path.read_bytes()
    assert not data.startswith(b'SQLite format 3')
    for value in (password, profile['name'], profile['host'], profile['username'], profile['password'],
                  profile['before_connect_command'], profile['after_disconnect_command'], 'remote-command-marker'):
        assert value.encode() not in data
    with sqlite3.connect(path) as plaintext:
        with pytest.raises(sqlite3.DatabaseError):
            plaintext.execute('SELECT * FROM sqlite_master').fetchall()
    with pytest.raises(Exception):
        Vault(path, 'wrong password')
    vault = Vault(path, password)
    saved = vault.profiles()[0]
    assert vault.credential(saved['credential_id'])['password'] == profile['password']
    assert saved == dict(profile, rdp_options={}, rdp_domain='', ssh_advanced={}, connect_at_startup=0, ssh_reconnect_delay=0, key_passphrase='', telnet_options={}, credential_source='local', credential_id=saved['credential_id'], id=profile_id, folder_id=None, protocol='ssh', icon='terminal', tab_color='', terminal_options={}, connect_timeout=15)
    saved['host'] = 'edited.example'
    saved['after_disconnect_command'] = ''
    vault.save(saved)
    assert vault.profiles()[0]['host'] == 'edited.example'
    assert not vault.profiles()[0].get('after_disconnect_command')
    vault.delete(profile_id)
    assert vault.profiles() == []
    vault.close()


def test_no_plaintext_fallback(tmp_path):
    path = tmp_path / 'plain.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE plaintext (value TEXT)')
    with pytest.raises(Exception):
        Vault(path, 'password')


def test_v20_migration_keeps_command_for_disconnection(tmp_path):
    path = tmp_path / 'private' / 'commands.db'
    vault = Vault(path, 'master')
    profile_id = vault.save(dict(name='Commands', host='localhost', port=22, username='',
                                 identity_file='', after_disconnect_command='echo cleanup'))
    with vault.connection:
        vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_startup_commands')
        vault.connection.execute('ALTER TABLE profiles RENAME COLUMN after_disconnect_command TO after_connect_command')
        vault.connection.execute('PRAGMA user_version = 20')
    vault.close()

    vault = Vault(path, 'master')
    try:
        profile = vault.profiles(profile_id)[0]
        assert profile['after_disconnect_command'] == 'echo cleanup'
        assert not profile.get('ssh_startup_commands')
    finally:
        vault.close()
