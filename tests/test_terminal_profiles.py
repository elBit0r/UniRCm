import pytest
from PyQt6.QtWidgets import QApplication
from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import ProfileDialog
from remote_manager.ui.terminal_profiles import TerminalProfilesDialog


@pytest.mark.parametrize('protocol', ['ssh', 'telnet'])
def test_profiles_persist_resolve_and_replace(tmp_path, protocol):
    path = tmp_path / 'vault.db'
    vault = Vault(path, 'master')
    themes = vault.terminal_profiles()
    assert len(themes) >= 10
    profile = dict(protocol=protocol, name='SSH', host='localhost', port=22, username='user', identity_file='', terminal_options={'profile_id': themes[0]['id']})
    profile['id'] = vault.save(profile)
    assert vault.effective_profile(vault.profiles()[0])['terminal_options'] == themes[0]['options']
    themes[0]['options']['font_size'] = 17
    vault.save_terminal_profiles(themes)
    assert vault.effective_profile(vault.profiles()[0])['terminal_options']['font_size'] == 17
    vault.replace_terminal_profile(themes[0]['id'], themes[1]['id'])
    assert vault.effective_profile(vault.profiles()[0])['terminal_options'] == themes[1]['options']
    vault.close()
    assert b'profile_id' not in path.read_bytes()
    vault = Vault(path, 'master')
    assert len(vault.terminal_profiles()) == len(themes) - 1
    assert vault.profiles()[0]['terminal_options']['profile_id'] == themes[1]['id']
    vault.close()


def test_profile_selection_ui(tmp_path):
    app = QApplication.instance() or QApplication([])
    vault = Vault(tmp_path / 'vault.db', 'master')
    manager = TerminalProfilesDialog(vault)
    dialog = ProfileDialog(parent=manager)
    editor = dialog.terminal_options
    editor.profile_choice.setCurrentIndex(2)
    assert editor.options() == {'profile_id': vault.terminal_profiles()[1]['id']}
    assert not editor.family.isEnabled()
    editor.reset()
    assert 'profile_id' not in editor.options()
    dialog.close()
    manager.close()
    vault.close()
