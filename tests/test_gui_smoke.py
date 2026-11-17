from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit

from remote_manager.storage.vault import Vault
from remote_manager.ui.dialogs import ProfileDialog, unlock_vault
from remote_manager.ui.main_window import MainWindow


def test_profile_dialog_and_window(qtbot, tmp_path):
    path = tmp_path / 'connections.db'
    vault = Vault(path, 'test master password')
    dialog = ProfileDialog()
    qtbot.addWidget(dialog)
    for key, value in dict(name='Test SSH', host='localhost', username='tester').items():
        dialog.fields[key].setText(value)
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    vault.save(dialog.profile)
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    assert window.tree.topLevelItem(0).text(0) == 'Test SSH'
    assert not window.tree.topLevelItem(0).icon(0).isNull()
    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    assert window.selected()['host'] == 'localhost'
    window.close()


def test_setup_and_unlock_dialog(qtbot, tmp_path):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    path = tmp_path / 'connections.db'

    def submit():
        dialog = QApplication.activeModalWidget()
        for field in dialog.findChildren(QLineEdit):
            field.setText('master password')
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(50, submit)
    vault = unlock_vault(path)
    assert vault is not None
    vault.close()
    QTimer.singleShot(50, submit)
    vault = unlock_vault(path)
    assert vault is not None
    vault.close()


def test_lock_clears_profiles_and_closes_database(qtbot, tmp_path):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    import pytest
    from sqlcipher3 import dbapi2 as sqlcipher

    path = tmp_path / 'connections.db'
    old_vault = Vault(path, 'master')
    old_vault.save(dict(name='Private', host='localhost', port=22, username='', identity_file=''))
    window = MainWindow(old_vault, path)
    qtbot.addWidget(window)
    window.show()

    window.lock_vault()
    assert window.vault is None
    assert window.tree.topLevelItemCount() == 0
    with pytest.raises(sqlcipher.ProgrammingError):
        old_vault.profiles()
    window.unlock_panel.password.setText('master')
    qtbot.keyClick(window.unlock_panel.password, Qt.Key.Key_Return)
    assert window.tree.topLevelItem(0).text(0) == 'Private'
    window.close()


def test_connection_appearance_roundtrip(qtbot, tmp_path):
    from remote_manager.ui.icons import CONNECTION_ICONS, connection_icon
    dialog = ProfileDialog()
    qtbot.addWidget(dialog)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ['General', 'SSH', 'SSH advanced', 'Telnet', 'RDP', 'Appearance', 'Terminal']
    dialog.fields['name'].setText('Router')
    dialog.fields['host'].setText('localhost')
    dialog.icon.set_icon('router')
    for mode in dialog.appearance_modes.values():
        mode.setCurrentIndex(mode.findData('override'))
    dialog.set_color('#e06030')
    dialog.terminal_options.size.setValue(18)
    dialog.terminal_options.colors['background'].setText('#123456')
    dialog.terminal_options.shape.setCurrentIndex(2)
    dialog.terminal_options.blink.setChecked(True)
    dialog.identity.setText('/home/test/.ssh/key')
    dialog.save()
    path = tmp_path / 'appearance.db'
    vault = Vault(path, 'master')
    vault.save(dialog.profile)
    vault.close()
    vault = Vault(path, 'master')
    saved = vault.profiles()[0]
    reopened = ProfileDialog(saved)
    qtbot.addWidget(reopened)
    assert reopened.icon.selected_icon() == 'router'
    assert reopened.tab_color == '#e06030'
    assert reopened.identity.text() == '/home/test/.ssh/key'
    assert reopened.terminal_options.options() == dialog.terminal_options.options()
    assert b'#123456' not in path.read_bytes()
    for name in CONNECTION_ICONS:
        assert not connection_icon(name, dialog.palette()).isNull()
    vault.close()
