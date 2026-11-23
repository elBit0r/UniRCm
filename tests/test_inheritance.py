from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import GroupDefaultsDialog, ProfileDialog
from remote_manager.terminal.ssh import ssh_command


def test_dynamic_encrypted_ssh_inheritance(tmp_path):
    path = tmp_path / 'vault.db'
    vault = Vault(path, 'master')
    root = vault.save_folder('Root')
    child = vault.save_folder('Child', root)
    vault.set_folder_defaults(root, dict(username='inherited-secret-marker', port=2222, identity_file='/keys/root'))
    vault.set_folder_defaults(child, dict(identity_file='', port=None))
    pid = vault.save(dict(name='Host', host='localhost', port=2200, username='local', identity_file='/local', folder_id=child,
                          ssh_modes=dict(port='inherit', username='inherit', identity_file='inherit')))
    profile = vault.profiles()[0]
    effective = vault.effective_profile(profile)
    assert (effective['port'], effective['username'], effective['identity_file']) == (22, 'inherited-secret-marker', '')
    assert '-i' not in ssh_command(effective)
    vault.set_folder_defaults(root, dict(username='changed', port=2223))
    assert vault.effective_profile(profile)['username'] == 'changed'
    vault.move_profile(pid, None)
    assert vault.effective_profile(vault.profiles()[0])['username'] == ''
    vault.move_profile(pid, child)
    profile['ssh_modes']['username'] = 'override'
    profile['ssh_modes']['port'] = 'default'
    assert vault.effective_profile(profile)['username'] == 'local'
    vault.save(profile)
    vault.move_profile(pid, root)
    assert vault.effective_profile(vault.profiles()[0])['port'] == 22
    vault.delete_folder(child)
    vault.close()
    assert b'inherited-secret-marker' not in path.read_bytes()
    vault = Vault(path, 'master')
    assert vault.profiles()[0]['ssh_modes']['username'] == 'override'
    assert vault.effective_profile(vault.profiles()[0])['username'] == 'local'
    vault.close()


def test_group_and_profile_inheritance_controls(qtbot, tmp_path):
    vault = Vault(tmp_path / 'vault.db', 'master')
    group = vault.save_folder('Servers')
    editor = GroupDefaultsDialog(vault.folders()[0])
    qtbot.addWidget(editor)
    mode, value = editor.fields['port']
    mode.setCurrentIndex(mode.findData('override'))
    value.setValue(2222)
    editor.save()
    vault.set_folder_defaults(group, editor.defaults)
    profile = ProfileDialog(folders=vault.folders(), folder_id=group)
    qtbot.addWidget(profile)
    profile.fields['name'].setText('Inherited')
    profile.fields['host'].setText('localhost')
    profile.save()
    assert profile.profile['ssh_modes']['port'] == 'inherit'
    vault.save(profile.profile)
    assert vault.effective_profile(vault.profiles()[0])['port'] == 2222
    # Switching to override enables the editable value, including an empty key.
    profile.ssh_modes['identity_file'].setCurrentIndex(0)
    assert profile.identity.isEnabled()
    vault.close()


def test_appearance_inheritance_live_terminal(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from remote_manager.terminal import ssh
    from remote_manager.ui.main_window import MainWindow

    # Real local PTY: verifies rendering updates and process continuity, not SSH login.
    client = tmp_path / 'pty-client'
    client.write_text('#!/bin/sh\nexec cat\n')
    client.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(client)])
    path = tmp_path / 'appearance.db'
    vault = Vault(path, 'master')
    root = vault.save_folder('Root')
    child = vault.save_folder('Child', root)
    options = dict(font_size=19, background='#123456', cursor_shape='bar', cursor_blink=True)
    vault.set_folder_defaults(root, dict(terminal_options=options, tab_color='#abcdef'))
    pid = vault.save(dict(name='Host', host='localhost', port=22, username='', identity_file='', folder_id=child,
                          terminal_options={'font_size': 12}, tab_color='#111111',
                          ssh_modes=dict(terminal_options='inherit', tab_color='inherit')))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    window.refresh(pid)
    window.connect_profile()
    terminal = window.tabs.widget(0)
    process = terminal.process
    assert terminal.options == options
    assert terminal.font().pointSize() == 19
    assert terminal.cursor_timer.isActive()
    assert window.tabs.tabBar().tabTextColor(0).name() == '#abcdef'

    def update_defaults():
        editor = QApplication.activeModalWidget()
        assert isinstance(editor, GroupDefaultsDialog)
        mode, field = editor.fields['terminal_options']
        assert mode.currentData() == 'override'
        field.size.setValue(23)
        editor.fields['tab_color'][1].setText('#fedcba')
        editor.save()

    window.refresh(selected_folder=root)
    QTimer.singleShot(0, update_defaults)
    window.edit_group_defaults()
    assert terminal.font().pointSize() == 23
    assert window.tabs.tabBar().tabTextColor(0).name() == '#fedcba'
    assert terminal.process is process and process.poll() is None

    # None stops inheritance at application defaults; empty overrides also stop it.
    vault.set_folder_defaults(child, dict(terminal_options=None, tab_color=''))
    window.refresh()
    assert terminal.options == {}
    assert terminal.cursor_timer.isActive()
    assert window.tabs.tabBar().tabTextColor(0) == window.palette().windowText().color()
    vault.move_profile(pid, root)
    window.refresh()
    assert terminal.font().pointSize() == 23
    profile = vault.profiles()[0]
    profile['ssh_modes'].update(terminal_options='override', tab_color='default')
    vault.save(profile)
    window.refresh()
    assert terminal.font().pointSize() == 12
    assert window.tabs.tabBar().tabTextColor(0) == window.palette().windowText().color()
    terminal.stop()
    window.close()
    assert b'#fedcba' not in path.read_bytes()
    vault = Vault(path, 'master')
    assert vault.effective_profile(vault.profiles()[0])['terminal_options'] == {'font_size': 12}
    assert next(f for f in vault.folders() if f['id'] == root)['ssh_defaults']['terminal_options']['font_size'] == 23
    vault.close()


def test_invalid_appearance_defaults_are_not_saved(tmp_path):
    import pytest
    vault = Vault(tmp_path / 'vault.db', 'master')
    folder = vault.save_folder('Root')
    for invalid in [dict(tab_color='invalid'), dict(terminal_options={'font_size': 0}),
                    dict(terminal_options={'cursor_blink': 'yes'}), dict(terminal_options={'unknown': 1})]:
        with pytest.raises(ValueError):
            vault.set_folder_defaults(folder, invalid)
    assert 'ssh_defaults' not in vault.folders()[0]
    vault.close()


def test_timeout_inheritance_editor_and_openssh(qtbot, tmp_path):
    import pytest

    path = tmp_path / 'timeout.db'
    vault = Vault(path, 'master')
    # Exercise the v5 -> v6 migration with an existing profile.
    pid = vault.save(dict(name='Host', host='localhost', port=22, username='', identity_file=''))
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN rdp_domain')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_advanced')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN connect_at_startup')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN telnet_options')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN credential_source')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN credential_id')
    vault.connection.execute('DROP TABLE credentials')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN connect_timeout')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN ssh_reconnect_delay')
    vault.connection.execute('DROP TABLE ssh_private_keys')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN authentication')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN before_connect_command')
    vault.connection.execute('ALTER TABLE profiles DROP COLUMN after_disconnect_command')
    vault.connection.execute('PRAGMA user_version = 5')
    vault.connection.commit()
    vault.close()
    vault = Vault(path, 'master')
    assert vault.profiles()[0]['connect_timeout'] == 15
    root = vault.save_folder('Root')
    child = vault.save_folder('Child', root)
    editor = GroupDefaultsDialog(dict(id=root, name='Root', ssh_defaults={}))
    qtbot.addWidget(editor)
    mode, field = editor.fields['connect_timeout']
    mode.setCurrentIndex(mode.findData('override'))
    field.setValue(37)
    editor.save()
    vault.set_folder_defaults(root, editor.defaults)
    profile = vault.profiles()[0]
    profile['folder_id'] = child
    dialog = ProfileDialog(profile, folders=vault.folders())
    qtbot.addWidget(dialog)
    mode = dialog.ssh_modes['connect_timeout']
    assert mode.currentData() == 'override'  # migration preserves prior behavior
    assert dialog.connect_timeout.value() == 15
    mode.setCurrentIndex(mode.findData('inherit'))
    assert not dialog.connect_timeout.isEnabled()
    dialog.save()
    vault.save(dialog.profile)
    profile = vault.profiles()[0]
    assert 'ConnectTimeout=37' in ssh_command(vault.effective_profile(profile))
    assert 'StrictHostKeyChecking=ask' in ssh_command(vault.effective_profile(profile))
    vault.set_folder_defaults(child, {'connect_timeout': None})
    assert vault.effective_profile(profile)['connect_timeout'] == 15
    vault.set_folder_defaults(child, {'connect_timeout': 9})
    assert 'ConnectTimeout=9' in ssh_command(vault.effective_profile(profile))
    profile['ssh_modes']['connect_timeout'] = 'override'
    profile['connect_timeout'] = 22
    vault.save(profile)
    assert 'ConnectTimeout=22' in ssh_command(vault.effective_profile(profile))
    profile['ssh_modes']['connect_timeout'] = 'default'
    assert 'ConnectTimeout=15' in ssh_command(vault.effective_profile(profile))
    for invalid in (0, -1, 601, True, '15', None):
        with pytest.raises(ValueError):
            ssh_command(dict(profile, connect_timeout=invalid))
        with pytest.raises(ValueError):
            vault.save(dict(profile, connect_timeout=invalid))
        if invalid is not None:  # None is a valid application-default marker on groups.
            with pytest.raises(ValueError):
                vault.set_folder_defaults(root, {'connect_timeout': invalid})
    vault.close()
    vault = Vault(path, 'master')
    assert vault.profiles()[0]['id'] == pid
    assert vault.profiles()[0]['connect_timeout'] == 22
    assert vault.profiles()[0]['ssh_modes']['connect_timeout'] == 'override'
    assert not vault.connection.execute('PRAGMA foreign_key_check').fetchall()
    vault.close()


def test_individual_terminal_properties_and_editor(qtbot, tmp_path):
    from remote_manager.ui.dialogs import ProfileDialog, GroupDefaultsDialog
    vault = Vault(tmp_path / 'individual.db', 'master')
    root = vault.save_folder('Root', defaults={'terminal_options': {'font_size': 20, 'background': '#123456', 'cursor_blink': False}})
    child = vault.save_folder('Child', root, defaults={'terminal_options': {'font_size': None, 'background': '#654321', 'cursor_blink': {'source': 'default'}}})
    pid = vault.save(dict(name='Individual', host='localhost', port=22, username='', identity_file='', folder_id=child,
                          terminal_options={'font_size': None, 'background': None, 'foreground': '#ffffff', 'cursor_blink': None}))
    profile = vault.profiles()[0]
    effective = vault.effective_profile(profile)['terminal_options']
    assert effective == {'font_size': 20, 'background': '#654321', 'foreground': '#ffffff'}
    editor = ProfileDialog(profile, folders=vault.folders(), save_callback=vault.save)
    qtbot.addWidget(editor)
    assert editor.terminal_options.property_modes['font_size'].currentData() == 'inherit'
    assert '20' in editor.terminal_options.property_notes['font_size'][0].text()
    mode = editor.terminal_options.property_modes['font_size']
    mode.setCurrentIndex(mode.findData('default'))
    editor.save()
    assert editor.result() == editor.DialogCode.Accepted
    assert 'font_size' not in vault.effective_profile(vault.profiles()[0])['terminal_options']
    vault.set_folder_defaults(root, {'terminal_options': {'font_size': 25, 'background': '#111111'}})
    profile['terminal_options']['font_size'] = None
    profile['ssh_modes'] = {'terminal_options': 'inherit'}
    assert vault.effective_profile(profile)['terminal_options']['font_size'] == 25
    vault.close()
    vault = Vault(tmp_path / 'individual.db', 'master')
    assert vault.profiles()[0]['terminal_options']['font_size'] == {'source': 'default'}
    vault.close()
