import pytest
from remote_manager.ui.dialogs import ProfileDialog


@pytest.mark.parametrize('protocol,login,user,password,phrase', [
    ('ssh', 'manual', True, True, True),
    ('rdp', 'manual', True, True, False),
    ('vnc', 'manual', False, True, False),
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
    assert not selector.form.isRowVisible(selector.reference_row)
    assert not selector.form.labelForField(selector.reference_row).isVisible()
    for source in ('shared', 'inherit', 'none', 'local'):
        selector.source.setCurrentIndex(selector.source.findData(source))
        assert selector.form.isRowVisible(selector.reference_row) == (source == 'shared')
        assert editor.general_form.isRowVisible(editor.credentials)
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
        assert editor.general_form.isRowVisible(editor.credentials) == (source == 'local')
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


@pytest.mark.parametrize(('protocol', 'mode', 'username', 'password', 'login', 'fields'), [
    ('ssh', 'configured', '', '', None, ('username',)),
    ('ssh', 'prompt_password', 'user', 'saved', None, ()),
    ('ssh', 'prompt_both', 'user', 'saved', None, ('username',)),
    ('telnet', 'prompt_both', '', '', 'manual', ()),
    ('telnet', 'configured', 'user', '', 'password', ('password',)),
    ('telnet', 'prompt_password', '', 'saved', 'username_password', ('username', 'password')),
    ('vnc', 'configured', '', '', None, ('password',)),
    ('vnc', 'prompt_both', 'ignored', 'saved', None, ('password',)),
])
def test_shared_authentication_prompt(qtbot, monkeypatch, protocol, mode, username, password, login, fields):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog, QWidget
    from remote_manager.ui.credentials import ConnectionAuthenticationDialog, prepare_connection_credentials

    parent = QWidget()
    qtbot.addWidget(parent)
    opened = []
    cancel = False

    def interact(dialog):
        def fill():
            opened.append(tuple(dialog.inputs))
            for key, field in dialog.inputs.items():
                assert not field.text()
                field.setText('entered-' + key)
            if cancel:
                dialog.reject()
            else:
                dialog.connect_button.click()

        QTimer.singleShot(0, fill)
        return QDialog.exec(dialog)

    monkeypatch.setattr(ConnectionAuthenticationDialog, 'exec', interact)
    profile = dict(host='localhost', port=22, protocol=protocol, authentication=mode,
                   username=username, password=password, telnet_options={'login_mode': login})
    result = prepare_connection_credentials(profile, parent)
    assert opened == ([fields] if fields else [])
    assert result['username'] == ('entered-username' if 'username' in fields else username)
    expected_password = '' if protocol == 'ssh' and mode.startswith('prompt_') else password
    assert result['password'] == ('entered-password' if 'password' in fields else expected_password)
    assert (profile['username'], profile['password']) == (username, password)
    if fields:
        cancel = True
        assert prepare_connection_credentials(profile, parent) is None


def test_shared_username_preview_and_override(qtbot, tmp_path):
    from PyQt6.QtWidgets import QWidget
    from remote_manager.storage.vault import Vault

    with_vault = QWidget()
    qtbot.addWidget(with_vault)
    vault = Vault(tmp_path / 'auth.db', 'master')
    with_vault.vault = vault
    try:
        reference = vault.save_credential('Team', 'shared-user', 'shared-password')
        pid = vault.save(dict(name='Server', host='localhost', port=22, username='old-user', identity_file='',
                             credential_source='shared', credential_id=reference))
        editor = ProfileDialog(vault.profiles(pid)[0], with_vault, save_callback=vault.save)
        assert editor.effective_labels['username'][0].text() == 'shared-user'
        username_mode = editor.ssh_modes['username']
        username_mode.setCurrentIndex(username_mode.findData('override'))
        editor.credentials.username.setText('connection-user')
        editor.authentication.setCurrentIndex(editor.authentication.findData('prompt_password'))
        assert not editor.credentials.form.isRowVisible(editor.credentials.password)
        editor.save()
        assert editor.result() == editor.DialogCode.Accepted
        saved = vault.profiles(pid)[0]
        assert saved['authentication'] == 'prompt_password'
        assert saved['credential_id'] == reference
        assert vault.effective_profile(saved)['username'] == 'connection-user'
        assert vault.credential(reference)['username'] == 'shared-user'
    finally:
        vault.close()
