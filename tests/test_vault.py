import sqlite3
import stat

import pytest

from remote_manager.storage.vault import Vault


def test_encrypted_profile_crud_and_unlock(tmp_path):
    path = tmp_path / 'private' / 'connections.db'
    password = "master ' secret"
    vault = Vault(path, password)
    profile = dict(name='private-profile-marker', host='secret-host.example', port=22,
                   username='private-user', password='remote-password-marker', identity_file='/private/key')
    profile_id = vault.save(profile)
    vault.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    data = path.read_bytes()
    assert not data.startswith(b'SQLite format 3')
    for value in (password, profile['name'], profile['host'], profile['username'], profile['password']):
        assert value.encode() not in data
    with sqlite3.connect(path) as plaintext:
        with pytest.raises(sqlite3.DatabaseError):
            plaintext.execute('SELECT * FROM sqlite_master').fetchall()
    with pytest.raises(Exception):
        Vault(path, 'wrong password')
    vault = Vault(path, password)
    saved = vault.profiles()[0]
    assert vault.credential(saved['credential_id'])['password'] == profile['password']
    assert saved == dict(profile, rdp_options={}, rdp_domain='', ssh_advanced={}, connect_at_startup=0, key_passphrase='', telnet_options={}, credential_source='local', credential_id=saved['credential_id'], id=profile_id, folder_id=None, protocol='ssh', icon='terminal', tab_color='', terminal_options={}, connect_timeout=15)
    saved['host'] = 'edited.example'
    vault.save(saved)
    assert vault.profiles()[0]['host'] == 'edited.example'
    vault.delete(profile_id)
    assert vault.profiles() == []
    vault.close()


def test_no_plaintext_fallback(tmp_path):
    path = tmp_path / 'plain.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE plaintext (value TEXT)')
    with pytest.raises(Exception):
        Vault(path, 'password')
