from remote_manager.storage.vault import Vault
from remote_manager.terminal.ssh import ssh_command
from remote_manager.ui.dialogs import ProfileDialog


def test_general_port_edits_ssh_and_persists(qtbot, tmp_path):
    vault = Vault(tmp_path / 'ports.db', 'master')
    group = vault.save_folder('SSH', defaults={'port': 2222})
    dialog = ProfileDialog(folders=vault.folders(), folder_id=group, save_callback=vault.save)
    qtbot.addWidget(dialog)
    assert dialog.desktop_port.isEnabled() and dialog.desktop_port.value() == 2222
    assert dialog.ssh_modes['port'].currentData() == 'inherit'
    general, ssh = dialog.tabs.widget(0), dialog.tabs.widget(1)
    assert general.isAncestorOf(dialog.port)
    assert general.isAncestorOf(dialog.ssh_modes['port'])
    assert not ssh.isAncestorOf(dialog.port)
    assert not ssh.isAncestorOf(dialog.ssh_modes['port'])
    dialog.fields['name'].setText('Server')
    dialog.fields['host'].setText('localhost')
    dialog.desktop_port.setValue(2200)
    assert dialog.port.value() == 2200
    assert dialog.ssh_modes['port'].currentData() == 'override'
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted
    saved = vault.profiles()[0]
    assert vault.effective_profile(saved)['port'] == 2200
    args = ssh_command(vault.effective_profile(saved))
    assert args[args.index('-p') + 1] == '2200'
    reopened = ProfileDialog(saved, folders=vault.folders())
    qtbot.addWidget(reopened)
    assert reopened.desktop_port.isEnabled() and reopened.desktop_port.value() == 2200
    mode = reopened.ssh_modes['port']
    mode.setCurrentIndex(mode.findData('inherit'))
    assert reopened.port.value() == 2222 and reopened.port.isEnabled()
    mode.setCurrentIndex(mode.findData('override'))
    assert reopened.port.value() == 2200
    vault.close()


def test_protocol_switch_keeps_ssh_port(qtbot):
    dialog = ProfileDialog()
    qtbot.addWidget(dialog)
    assert dialog.desktop_port.value() == 22 and dialog.desktop_port.isEnabled()
    dialog.desktop_port.setValue(2200)
    for protocol, port in [('rdp', 3389), ('vnc', 5900), ('ssh', 2200)]:
        dialog.protocol.setCurrentIndex(dialog.protocol.findData(protocol))
        assert dialog.desktop_port.isEnabled()
        assert dialog.desktop_port.value() == port



def test_telnet_port_in_general_save_reopen(qtbot, tmp_path):
    from PyQt6.QtWidgets import QSpinBox
    vault = Vault(tmp_path / 'telnet.db', 'master')
    dialog = ProfileDialog(save_callback=vault.save)
    qtbot.addWidget(dialog)
    dialog.fields['name'].setText('Telnet')
    dialog.fields['host'].setText('localhost')
    dialog.protocol.setCurrentIndex(dialog.protocol.findData('telnet'))
    assert dialog.port.isEnabled() and dialog.port.value() == 23
    assert dialog.tabs.widget(0).isAncestorOf(dialog.port)
    assert not dialog.telnet_page.isAncestorOf(dialog.port)
    assert not hasattr(dialog, 'telnet_port')
    assert dialog.telnet_page.findChildren(QSpinBox) == [dialog.telnet_timeout]
    dialog.port.setValue(2323)
    dialog.protocol.setCurrentIndex(dialog.protocol.findData('ssh'))
    assert dialog.port.value() == 22
    dialog.protocol.setCurrentIndex(dialog.protocol.findData('telnet'))
    assert dialog.port.value() == 2323
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted
    saved = vault.profiles()[0]
    assert saved['port'] == 2323 and saved['ssh_modes']['port'] == 'override'
    reopened = ProfileDialog(saved)
    qtbot.addWidget(reopened)
    assert reopened.port.value() == 2323 and reopened.port.isEnabled()
    vault.close()
