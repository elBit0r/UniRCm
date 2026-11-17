import pytest
from remote_manager.protocols.validation import validate_profile
from remote_manager.storage.vault import Vault


@pytest.mark.parametrize('protocol,port', [('rdp', 3389), ('vnc', 5900)])
def test_credentials_stay_in_vault(tmp_path, protocol, port):
    vault = Vault(tmp_path / 'desktop.db', 'master')
    credential = vault.save_credential('Desktop', 'alice', 'desktop-secret-marker')
    profile = dict(name='Desktop', host='localhost', port=port, protocol=protocol,
                   username='', identity_file='', credential_source='shared', credential_id=credential,
                   ssh_modes={'port': 'override'})
    vault.save(profile)
    effective = vault.effective_profile(vault.profiles()[0])
    assert effective['username'] == 'alice'
    assert effective['password'] == 'desktop-secret-marker'
    assert b'desktop-secret-marker' not in (tmp_path / 'desktop.db').read_bytes()
    vault.close()


@pytest.mark.parametrize('values', [
    {'host': 'host /cert:ignore'}, {'host': '-host'},
    {'port': 0}, {'port': 65536}, {'port': '3389'},
    {'username': 'alice\nother'}, {'username': 'alice\x00other'},
])
def test_invalid_desktop_profile(values):
    with pytest.raises(ValueError):
        validate_profile(dict(dict(host='localhost', port=3389, username='alice'), **values))


@pytest.mark.parametrize('protocol,port', [('rdp', 3389), ('vnc', 5900)])
def test_editor_saves_desktop_profile(qtbot, protocol, port):
    from remote_manager.ui.dialogs import ProfileDialog
    dialog = ProfileDialog()
    qtbot.addWidget(dialog)
    dialog.fields['name'].setText('Desktop')
    dialog.fields['host'].setText('localhost')
    dialog.protocol.setCurrentIndex(dialog.protocol.findData(protocol))
    assert dialog.desktop_port.value() == port
    dialog.save()
    assert dialog.profile['protocol'] == protocol
    assert dialog.profile['port'] == port
    assert dialog.profile['ssh_modes']['port'] == 'override'
