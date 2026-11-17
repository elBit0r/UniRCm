from remote_manager.storage.vault import Vault
from remote_manager.ui.main_window import MainWindow
from remote_manager.ui.dialogs import ProfileDialog


def test_startup_selection_and_encrypted_persistence(qtbot, tmp_path, monkeypatch):
    path = tmp_path / 'vault.db'
    vault = Vault(path, 'master')
    base = dict(host='localhost', username='user', port=22, identity_file='')
    auto_id = vault.save(dict(base, name='Automatic', connect_at_startup=True))
    vault.save(dict(base, name='Manual'))
    vault.close()
    vault = Vault(path, 'master')
    opened = []
    monkeypatch.setattr(MainWindow, 'open_profile', lambda self, profile: opened.append(profile['id']))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: opened == [auto_id])
    saved = vault.profiles(auto_id)[0]
    dialog = ProfileDialog(saved, window, vault.folders(), save_callback=vault.save)
    assert dialog.connect_at_startup.isChecked()
    dialog.connect_at_startup.setChecked(False)
    dialog.save()
    assert not vault.profiles(auto_id)[0]['connect_at_startup']
