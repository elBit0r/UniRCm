import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QLineEdit

from remote_manager.storage.vault import Vault
from remote_manager.ui.main_window import MainWindow
from remote_manager.ui.credentials import ConnectionAuthenticationDialog


@pytest.mark.parametrize(('options', 'username', 'password', 'fields'), [
    ({}, 'saved-user', 'saved-password', ()),
    ({}, '', '', ('username', 'password')),
    ({}, '', 'saved-password', ('username',)),
    ({}, 'saved-user', '', ('password',)),
    ({'authentication': 'prompt_password'}, 'saved-user', 'saved-password', ('password',)),
    ({'authentication': 'prompt_password'}, '', 'saved-password', ('username', 'password')),
    ({'authentication': 'prompt_both'}, 'saved-user', 'saved-password', ('username', 'password')),
])
def test_rdp_authentication_modes(qtbot, tmp_path, monkeypatch, options, username, password, fields):
    path = tmp_path / 'rdp.db'
    vault = Vault(path, 'master')
    profile_id = vault.save(dict(name='Desktop', host='localhost', port=3389, protocol='rdp',
                                 identity_file='', username=username, password=password,
                                 rdp_options=options))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    opened = []
    entered = dict(username=r'CORP\entered-user', password=' entered-password ')
    cancel = False

    def interact(dialog):
        def fill_or_cancel():
            opened.append(tuple(dialog.inputs))
            assert not dialog.connect_button.isEnabled()
            for key, field in dialog.inputs.items():
                assert field.text() == ''
                if key == 'password':
                    assert field.echoMode() == QLineEdit.EchoMode.Password
                field.setText(entered[key])
            assert dialog.connect_button.isEnabled()
            if cancel:
                dialog.reject()
            else:
                dialog.connect_button.click()

        QTimer.singleShot(0, fill_or_cancel)
        return QDialog.exec(dialog)

    monkeypatch.setattr(ConnectionAuthenticationDialog, 'exec', interact)
    try:
        profile = vault.profiles(profile_id)[0]
        terminal = window.open_profile(profile)
        assert terminal.worker.credentials[2:4] == (
            entered['username'] if 'username' in fields else username,
            entered['password'] if 'password' in fields else password,
        )
        terminal.stop()
        assert terminal.worker.credentials is None
        assert opened == ([fields] if fields else [])
        if fields:
            cancel = True
            window.reconnect_terminal(terminal)
            assert opened == [fields, fields]
            assert window.tabs.count() == 1
            assert window.tabs.currentWidget() is terminal
        saved = vault.profiles(profile_id)[0]
        assert (saved['username'], saved['password']) == (username, password)
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()
