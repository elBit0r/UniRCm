from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QComboBox, QDialogButtonBox
from remote_manager.ui.icon_picker import IconDialog, IconPicker
from remote_manager.ui.icons import CONNECTION_ICONS, connection_icon
from remote_manager.storage.vault import Vault


def test_visual_selection_search_cancel_and_accept(qtbot):
    picker = IconPicker('router')
    qtbot.addWidget(picker)
    assert not isinstance(picker, QComboBox)

    def choose(accept):
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, IconDialog)
        dialog.search.setText('no-matching-icon')
        assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.search.setText('cloud')
        assert dialog.selected_icon() == 'cloud'
        if accept:
            dialog.accept()
        else:
            dialog.reject()

    QTimer.singleShot(0, lambda: choose(False))
    picker.click()
    assert picker.selected_icon() == 'router'
    QTimer.singleShot(0, lambda: choose(True))
    picker.click()
    assert picker.selected_icon() == 'cloud'
    assert picker.text() and not picker.icon().isNull()


def test_library_renders_and_expanded_group_icon_persists(qtbot, tmp_path):
    picker = IconPicker()
    qtbot.addWidget(picker)
    assert len(CONNECTION_ICONS) >= 60
    for name in CONNECTION_ICONS:
        assert not connection_icon(name, picker.palette()).pixmap(32, 32).isNull()
    path = tmp_path / 'icons.db'
    vault = Vault(path, 'test-master')
    folder = vault.save_folder('Cloud', appearance={'icon': 'cloud', 'color': ''})
    vault.close()
    vault = Vault(path, 'test-master')
    assert next(f for f in vault.folders() if f['id'] == folder)['appearance']['icon'] == 'cloud'
    vault.close()
