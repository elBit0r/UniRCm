import pytest
from remote_manager.ui.dialogs import ProfileDialog


@pytest.mark.parametrize('protocol,login,user,password,phrase', [
    ('ssh', 'manual', True, True, True),
    ('rdp', 'manual', True, True, False),
    ('vnc', 'manual', True, False, False),
    ('telnet', 'manual', False, False, False),
    ('telnet', 'password', False, True, False),
    ('telnet', 'username_password', True, True, False),
])
def test_protocol_and_login_controls(qtbot, protocol, login, user, password, phrase):
    editor = ProfileDialog(dict(name='Server', host='localhost', port=22, username='user',
                                password='stored-password', key_passphrase='stored-phrase', identity_file=''))
    qtbot.addWidget(editor)
    editor.protocol.setCurrentIndex(editor.protocol.findData(protocol))
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData(login))
    assert editor.credentials.username.isEnabled() == user
    assert editor.credentials.password.isEnabled() == password
    assert editor.credentials.key_passphrase.isEnabled() == phrase
    assert editor.credentials.form.isRowVisible(editor.credentials.key_passphrase) == phrase
    terminal_index = editor.tabs.indexOf(editor.terminal_page)
    assert editor.tabs.isTabEnabled(terminal_index) == (protocol in ('ssh', 'telnet'))
    editor.folder.setCurrentIndex(0)
    editor.update_effective_values()
    assert editor.credentials.password.isEnabled() == password
    editor.protocol.setCurrentIndex(editor.protocol.findData('ssh'))
    assert editor.credentials.password.text() == 'stored-password'
    assert editor.credentials.key_passphrase.text() == 'stored-phrase'
    assert editor.credentials.key_passphrase.isEnabled()


def test_source_visibility_and_disabled_secrets(qtbot):
    editor = ProfileDialog()
    qtbot.addWidget(editor)
    selector = editor.credential_selector
    assert not selector.form.isRowVisible(selector.reference)
    assert not selector.form.labelForField(selector.reference).isVisible()
    for source in ('shared', 'inherit', 'none', 'local'):
        selector.source.setCurrentIndex(selector.source.findData(source))
        assert selector.form.isRowVisible(selector.reference) == (source == 'shared')
        assert editor.general_form.isRowVisible(editor.credentials) == (source in ('local', 'none'))
        assert editor.credentials.password.isEnabled() == (source == 'local')
        assert editor.credentials.key_passphrase.isEnabled() == (source == 'local')


def test_telnet_login_mode_and_credential_sources_in_general(qtbot, tmp_path):
    from remote_manager.storage.vault import Vault
    from remote_manager.ui.main_window import MainWindow
    vault = Vault(tmp_path / 'credentials.db', 'master')
    reference = vault.save_credential('Device', 'operator', 'device-password')
    group = vault.save_folder('Devices', defaults={'credential_id': reference})
    parent = MainWindow(vault, tmp_path / 'credentials.db')
    qtbot.addWidget(parent)
    editor = ProfileDialog(parent=parent, folders=vault.folders(), folder_id=group)
    editor.protocol.setCurrentIndex(editor.protocol.findData('telnet'))
    general = editor.tabs.widget(0)
    assert general.isAncestorOf(editor.telnet_login)
    assert not editor.telnet_page.isAncestorOf(editor.telnet_login)
    assert editor.general_form.isRowVisible(editor.telnet_login)
    assert not editor.credential_selector.isEnabled()
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData('password'))
    assert editor.credential_selector.isEnabled()
    assert not editor.username_row.isEnabled()
    for source in ('shared', 'inherit', 'none', 'local'):
        editor.credential_selector.source.setCurrentIndex(editor.credential_selector.source.findData(source))
        assert editor.general_form.isRowVisible(editor.credentials) == (source in ('local', 'none'))
        assert editor.credentials.password.isEnabled() == (source == 'local')
        assert not editor.credentials.key_passphrase.isEnabled()
    assert 'without encryption' in editor.credentials.password.toolTip()
    assert 'OpenSSH' not in editor.effective_labels['username'][0].text()
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData('username_password'))
    assert editor.username_row.isEnabled()
    editor.telnet_login.setCurrentIndex(editor.telnet_login.findData('manual'))
    assert not editor.credential_selector.isEnabled()
    editor.protocol.setCurrentIndex(editor.protocol.findData('ssh'))
    assert not editor.general_form.isRowVisible(editor.telnet_login)
    assert editor.credential_selector.isEnabled()
    parent.close()
