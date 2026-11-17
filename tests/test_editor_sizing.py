import pytest
from PyQt6.QtWidgets import QDialogButtonBox, QScrollArea, QTabWidget

from remote_manager.ui.dialogs import GroupDefaultsDialog, ProfileDialog


@pytest.mark.parametrize('group', [False, True])
def test_editors_scroll_advanced_fields_without_hiding_save(qtbot, group):
    editor = (GroupDefaultsDialog(dict(name='Group', parent_id=None))
              if group else ProfileDialog())
    qtbot.addWidget(editor)
    mode = editor.fields['ssh_advanced'][0] if group else editor.ssh_modes['ssh_advanced']
    mode.setCurrentIndex(mode.findData('override'))
    tabs = editor.findChild(QTabWidget)
    tabs.setCurrentIndex(2)
    editor.resize(560, 390)
    editor.show()
    qtbot.waitUntil(lambda: editor.isVisible())
    scroll = tabs.currentWidget().findChild(QScrollArea)
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().maximum() > 0)
    assert editor.size().width() == 560
    assert editor.size().height() == 390
    table = editor.ssh_advanced.forwards.table
    assert table.minimumWidth() < 740
    scroll.ensureWidgetVisible(table)
    assert scroll.verticalScrollBar().value() > 0
    buttons = editor.findChild(QDialogButtonBox)
    assert buttons.isVisible()
    assert editor.rect().contains(buttons.geometry())


@pytest.mark.parametrize('group', [False, True])
def test_required_field_returns_to_general_without_saving(qtbot, group):
    saved = []
    editor = (GroupDefaultsDialog(dict(name='', parent_id=None), save_callback=lambda *args: saved.append(args))
              if group else ProfileDialog(save_callback=lambda profile: saved.append(profile)))
    qtbot.addWidget(editor)
    editor.show()
    if not group:
        editor.fields['host'].setText('preserve.example.org')
    editor.tabs.setCurrentIndex(2)
    editor.save()
    assert not saved
    assert editor.tabs.currentIndex() == 0
    field = editor.name if group else editor.fields['name']
    qtbot.waitUntil(field.hasFocus)
    assert editor._field_errors[field].isVisible()
    field.setText('Corrected name')
    assert not editor._field_errors[field].isVisible()
    if not group:
        assert editor.fields['host'].text() == 'preserve.example.org'
    editor.close()
