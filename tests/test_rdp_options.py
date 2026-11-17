"""RDP configuration, encrypted migration and live-widget ownership."""
import pytest
from PyQt6.QtWidgets import QWidget
from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import ProfileDialog
from remote_manager.rdp_options import effective_options, native_flags, desktop_size
from remote_manager.protocols.rdp import RdpSession


def test_editor_roundtrip_encrypted_options(qtbot, tmp_path):
    path = tmp_path / 'rdp.db'
    vault = Vault(path, 'master')
    editor = ProfileDialog(dict(name='Desktop', host='localhost', port=3389, username='alice', protocol='rdp'), save_callback=vault.save)
    qtbot.addWidget(editor)
    controls = editor.rdp_options.controls
    assert editor.tabs.isTabEnabled(editor.tabs.indexOf(editor.rdp_options))
    assert not controls['width'].isEnabled()
    controls['resolution'].setCurrentIndex(controls['resolution'].findData('fixed'))
    assert controls['width'].isEnabled()
    controls['width'].setValue(1600)
    controls['height'].setValue(900)
    controls['color_depth'].setCurrentIndex(controls['color_depth'].findData(16))
    controls['connection_speed'].setCurrentIndex(controls['connection_speed'].findData(2))
    controls['display'].setCurrentIndex(controls['display'].findData('detached'))
    controls['compression'].setChecked(False)
    controls['admin_session'].setChecked(True)
    controls['clipboard'].setChecked(True)
    controls['timeout'].setValue(27)
    editor.protocol.setCurrentIndex(editor.protocol.findData('ssh'))
    assert not editor.tabs.isTabEnabled(editor.tabs.indexOf(editor.rdp_options))
    editor.protocol.setCurrentIndex(editor.protocol.findData('rdp'))
    editor.save()
    assert editor.result() == editor.DialogCode.Accepted, editor.error.text()
    pid = editor.profile['id']
    expected = editor.rdp_options.options()
    vault.close()
    assert b'admin_session' not in path.read_bytes()
    vault = Vault(path, 'master')
    saved = vault.profiles(pid)[0]
    assert saved['rdp_options'] == expected
    assert vault.effective_profile(saved)['rdp_options'] == expected
    assert vault.profiles(vault.copy_profile(pid, None))[0]['rdp_options'] == expected
    reopened = ProfileDialog(saved)
    qtbot.addWidget(reopened)
    assert reopened.rdp_options.options() == expected
    vault.close()
    assert desktop_size(expected, 800, 600) == (1600, 900)
    assert native_flags(expected) & 128
    assert native_flags(expected) & 64
    assert not native_flags(expected) & 1
    assert desktop_size(effective_options({}), 1351, 850) == (1350, 850)


def test_v15_options_migration_preserves_domain_and_credentials(tmp_path):
    path = tmp_path / 'old.db'
    vault = Vault(path, 'master')
    pid = vault.save(dict(name='Desktop', host='localhost', port=3389, username='alice',
                         identity_file='', password='secret', protocol='rdp', rdp_domain='CORP'))
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
    vault.connection.execute('DROP TABLE ssh_private_keys')
    vault.connection.execute('PRAGMA user_version=15')
    vault.connection.commit()
    vault.close()
    vault = Vault(path, 'master')
    profile = vault.profiles(pid)[0]
    assert profile['rdp_options'] == {}
    assert profile['rdp_domain'] == 'CORP'
    assert profile['password'] == 'secret'
    vault.close()


@pytest.mark.parametrize('options', [{'timeout': 0}, {'width': 9000}, {'height': True},
    {'color_depth': 8}, {'connection_speed': 0}, {'display': 'external'},
    {'compression': 'yes'}, {'ignore_certificate': True}])
def test_invalid_options_rejected(options):
    with pytest.raises(ValueError):
        effective_options(options)


def test_live_view_detach_attach_and_close_cleanup(qtbot):
    # Cancel the deferred connect; exercise real Qt ownership without remote side effects.
    session = RdpSession(dict(host='localhost', port=3389, password='test'))
    qtbot.addWidget(session)
    session.stop()
    worker, view = session.worker, session.view
    session.show()
    session.detach_desktop()
    assert session.detached
    assert session.desktop_window.isWindow()
    assert session.desktop_window.isVisible()
    assert view.parentWidget() is session.desktop_window
    session.attach_desktop()
    assert not session.detached
    assert view.parentWidget() is session
    assert not session.desktop_window.isVisible()
    assert session.view is view and session.worker is worker
    session.detach_desktop()
    session.desktop_window.close()
    assert not session.desktop_window.isVisible()
    assert worker.cancel.is_set()
    assert not session.is_running()
    assert not session.findChildren(QWidget, 'Disconnect')


def test_database_lock_closes_detached_desktop(qtbot, tmp_path, monkeypatch):
    from remote_manager.ui.main_window import MainWindow
    path = tmp_path / 'locked.db'
    vault = Vault(path, 'master')
    pid = vault.save(dict(name='Desktop', host='localhost', port=3389, username='test',
                         password='test', identity_file='', protocol='rdp'))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    session = window.open_profile(vault.profiles(pid)[0])
    # Cancel before connecting: this test checks lock ownership, not the server.
    session.stop()
    session.detach_desktop()
    desktop = session.desktop_window
    worker = session.worker
    assert desktop.isVisible()
    window.lock_vault(automatic=True)
    assert window.tabs.count() == 0
    assert not desktop.isVisible()
    assert worker.cancel.is_set()
    assert not worker.isRunning()
    assert window.vault is None
    qtbot.wait(30)  # Process deferred destruction of closed session shortcuts.
    window.unlock_panel.password.setText('master')
    window.unlock_panel.submit()
    assert window.vault is not None and window.vault is not vault
    window.close()
