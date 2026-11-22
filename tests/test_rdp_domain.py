import pytest
from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import ProfileDialog
from PyQt6.QtWidgets import QWidget
from remote_manager.protocols.rdp import RdpWorker


def test_domain_editor_encrypted_roundtrip_and_common_credentials(qtbot, tmp_path):
    path = tmp_path / 'domain.db'
    vault = Vault(path, 'master')
    reference = vault.save_credential('Windows', 'alice', 'secret-password')
    parent = QWidget()
    parent.vault = vault
    qtbot.addWidget(parent)
    editor = ProfileDialog(dict(name='Windows', host='localhost', port=3389, protocol='rdp',
                                username='alice', credential_source='shared', credential_id=reference), parent=parent, save_callback=vault.save)
    qtbot.addWidget(editor)
    assert editor.general_form.isRowVisible(editor.rdp_domain)
    editor.rdp_domain.setText('CORP-domain-marker')
    editor.protocol.setCurrentIndex(editor.protocol.findData('ssh'))
    assert not editor.general_form.isRowVisible(editor.rdp_domain)
    editor.protocol.setCurrentIndex(editor.protocol.findData('rdp'))
    editor.save()
    assert editor.result() == editor.DialogCode.Accepted, editor.error.text()
    profile_id = editor.profile['id']
    saved = vault.profiles(profile_id)[0]
    assert saved['credential_id'] == reference
    vault.close()
    assert b'CORP-domain-marker' not in path.read_bytes()
    vault = Vault(path, 'master')
    profile = vault.effective_profile(vault.profiles(profile_id)[0])
    assert profile['rdp_domain'] == 'CORP-domain-marker'
    assert profile['username'] == 'alice'
    assert profile['password'] == 'secret-password'
    reopened = ProfileDialog(profile)
    qtbot.addWidget(reopened)
    assert reopened.rdp_domain.text() == 'CORP-domain-marker'
    copy_id = vault.copy_profile(profile_id, None)
    assert vault.profiles(copy_id)[0]['rdp_domain'] == profile['rdp_domain']
    profile['rdp_domain'] = ''
    vault.save(profile)
    assert vault.profiles(profile_id)[0]['rdp_domain'] == ''
    vault.close()


@pytest.mark.parametrize('domain,expected', [('EXPLICIT', 'EXPLICIT'), ('', 'LEGACY')])
def test_domain_forwarded_to_native_api(domain, expected):
    class Bridge:
        def urdp_new(self, *args):
            self.args = args
            return None
    bridge = Bridge()
    worker = RdpWorker(bridge, dict(host='localhost', port=3389, username='LEGACY\\alice',
                                  password='test-secret', rdp_domain=domain), None)
    worker.run()
    assert bridge.args[2:5] == (b'alice', b'test-secret', expected.encode())
    assert worker.credentials is None


def test_existing_v14_database_migrates(tmp_path):
    path = tmp_path / 'old.db'
    vault = Vault(path, 'master')
    profile_id = vault.save(dict(name='Old', host='localhost', port=3389, username='alice',
                                 password='secret', identity_file='', protocol='rdp'))
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_domain')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_reconnect_delay')
    vault.connection.execute('DROP TABLE ssh_private_keys')
    vault.connection.execute('PRAGMA user_version=14')
    vault.connection.commit()
    vault.close()
    vault = Vault(path, 'master')
    assert vault.connection.execute('PRAGMA user_version').fetchone()[0] == 18
    profile = vault.profiles(profile_id)[0]
    assert profile['rdp_domain'] == ''
    assert profile['password'] == 'secret'
    vault.close()
