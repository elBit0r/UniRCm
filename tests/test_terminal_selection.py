"""Local Qt selection checks; these do not claim SSH authentication coverage."""
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication

from remote_manager.terminal import ssh


@pytest.fixture
def terminal(qtbot, monkeypatch, tmp_path):
    # A real idle PTY keeps terminal lifecycle intact; test only local UI behavior.
    launcher = tmp_path / 'local-terminal'
    launcher.write_text('#!/bin/sh\nexec cat\n')
    launcher.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(launcher)])
    widget = ssh.Terminal(dict(host='localhost', port=22, username='', identity_file=''))
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.show()
    widget.stream.feed('first alpha\r\nsecond café界\r\nthird'.encode())
    qtbot.waitUntil(widget.isVisible)
    yield widget
    widget.stop()


def drag(qtbot, terminal, start, end, modifier=Qt.KeyboardModifier.NoModifier):
    def point(cell):
        row, column = cell
        return QPoint(column * terminal.cell_w, row * terminal.cell_h + terminal.cell_h // 2)
    qtbot.mousePress(terminal, Qt.MouseButton.LeftButton, modifier=modifier, pos=point(start))
    qtbot.mouseMove(terminal, point(end))
    qtbot.mouseRelease(terminal, Qt.MouseButton.LeftButton, modifier=modifier, pos=point(end))


def test_selection_both_directions_and_unicode(qtbot, terminal):
    for start, end in [((0, 6), (1, 14)), ((1, 14), (0, 6))]:
        drag(qtbot, terminal, start, end)
        assert terminal.selected_text() == 'alpha\nsecond café界'
        qtbot.keyClick(terminal, Qt.Key.Key_C,
                       modifier=Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert QApplication.clipboard().text() == 'alpha\nsecond café界'
        terminal.repaint()  # Exercise selection highlighting and glyph rendering.
    drag(qtbot, terminal, (0, 2), (0, 2))
    assert terminal.selected_text() == ''
    QApplication.clipboard().setText('keep clipboard')
    terminal.copy_selection()
    assert QApplication.clipboard().text() == 'keep clipboard'


def test_shift_selects_locally_without_leaking_mouse_events(qtbot, terminal, monkeypatch):
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    terminal.stream.feed(b'\x1b[?1000h\x1b[?1006h')
    drag(qtbot, terminal, (0, 0), (0, 5), Qt.KeyboardModifier.ShiftModifier)
    assert terminal.selected_text() == 'first'
    assert sent == []
    qtbot.mouseClick(terminal, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert sent == [b'\x1b[<0;1;1M', b'\x1b[<0;1;1m']
    qtbot.keyClick(terminal, Qt.Key.Key_C, modifier=Qt.KeyboardModifier.ControlModifier)
    assert sent[-1] == b'\x03'  # Ctrl+C retains its remote interrupt meaning.
    assert terminal.selected_text() == ''


def test_selection_in_scrollback_and_clear_on_resize(qtbot, terminal):
    terminal.stream.feed(b'\r\nscrollback line' * 50)
    terminal.screen.prev_page()
    expected = terminal.screen.display[0].rstrip()
    drag(qtbot, terminal, (0, 0), (0, terminal.screen.columns))
    assert terminal.selected_text() == expected
    terminal.resize(900, 450)
    qtbot.waitUntil(lambda: terminal.selection_anchor is None)


def test_live_terminal_appearance(qtbot, terminal):
    original_columns = terminal.screen.columns
    for shape in ('outline', 'block', 'underline', 'bar'):
        terminal.apply_options(dict(font_size=24, background='#123456', foreground='#eeeeee',
                                    cursor_color='#ff0000', cursor_shape=shape, cursor_blink=True))
        terminal.setFocus()
        terminal.repaint()
        assert terminal.cursor_timer.isActive()
        assert terminal.font().pointSize() == 24
        assert terminal.screen.columns < original_columns
        assert terminal.grab().toImage().pixelColor(terminal.width()-1, terminal.height()-1).name() == '#123456'
    terminal.apply_options({})
    assert terminal.cursor_timer.isActive()
    assert terminal.grab().toImage().pixelColor(terminal.width()-1, terminal.height()-1).name() == '#000000'


def test_quick_appearance_preview_apply_cancel(qtbot, terminal):
    from remote_manager.ui.dialogs import TerminalAppearanceDialog
    original = dict(terminal.options)
    saved = []
    dialog = TerminalAppearanceDialog(terminal, saved.append)
    qtbot.addWidget(dialog)
    dialog.editor.size.setValue(20)
    assert terminal.font().pointSize() == 20
    dialog.reject()
    assert terminal.options == original
    dialog = TerminalAppearanceDialog(terminal, saved.append)
    qtbot.addWidget(dialog)
    dialog.editor.size.setValue(22)
    dialog.accept()
    assert terminal.font().pointSize() == 22
    assert saved == []
    dialog = TerminalAppearanceDialog(terminal, saved.append)
    qtbot.addWidget(dialog)
    dialog.editor.size.setValue(24)
    dialog.save()
    assert saved[0]['font_size'] == 24


def test_control_wheel_zoom_is_local(qtbot, terminal, monkeypatch):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    terminal.stream.feed(b'\x1b[?1000h')
    size = terminal.font().pointSize()
    event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    terminal.wheelEvent(event)
    assert terminal.font().pointSize() == size + 1
    assert sent == []


def test_quick_appearance_saves_connection_override(qtbot, terminal, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from remote_manager.storage.vault import Vault
    from remote_manager.ui.main_window import MainWindow
    from remote_manager.ui.dialogs import TerminalAppearanceDialog
    path = tmp_path / 'appearance.db'
    vault = Vault(path, 'test master')
    group = vault.save_folder('Servers')
    profile_id = vault.save(dict(name='Local', host='localhost', port=22, username='',
                                identity_file='', folder_id=group,
                                ssh_modes={'terminal_options': 'inherit'}))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)
    terminal.profile_id = profile_id
    window.tabs.addTab(terminal, 'Local')

    def execute(dialog):
        dialog.editor.size.setValue(21)
        dialog.save()
        return dialog.result()

    monkeypatch.setattr(TerminalAppearanceDialog, 'exec', execute)
    window.terminal_appearance(terminal)
    saved = vault.profiles()[0]
    assert saved['ssh_modes']['terminal_options'] == 'override'
    assert saved['terminal_options']['font_size'] == 21
    vault.close()
    window.vault = Vault(path, 'test master')
    assert window.vault.effective_profile(window.vault.profiles()[0])['terminal_options']['font_size'] == 21
    # Save failure keeps the editor open; Cancel still restores the prior appearance.
    def fail(options):
        raise RuntimeError('Database unavailable')
    dialog = TerminalAppearanceDialog(terminal, fail, window)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    dialog.show()
    dialog.editor.size.setValue(25)
    dialog.save()
    assert dialog.isVisible()
    dialog.reject()
    assert terminal.font().pointSize() == 21
    window.tabs.removeTab(0)
    window.close()


def test_default_appearance_and_font_fallback(qtbot, monkeypatch):
    from PyQt6.QtGui import QFontDatabase
    from remote_manager.terminal.appearance import DEFAULT_OPTIONS, default_font
    from remote_manager.ui.dialogs import TerminalOptions

    for families, expected in [(['Hack', 'Inconsolata'], 'Inconsolata'), (['Hack'], 'Hack')]:
        monkeypatch.setattr(QFontDatabase, 'families', lambda f=families: f)
        assert default_font().family() == expected
    monkeypatch.undo()
    editor = TerminalOptions({})
    qtbot.addWidget(editor)
    for key, value in DEFAULT_OPTIONS.items():
        assert editor.options()[key] == value
    editor.blink.setChecked(False)
    editor.shape.setCurrentIndex(0)
    editor.colors['foreground'].setText('#ffffff')
    editor.reset()
    for key, value in DEFAULT_OPTIONS.items():
        assert editor.options()[key] == value


def test_resize_with_same_cell_count_preserves_selection(qtbot, terminal):
    drag(qtbot, terminal, (0, 0), (0, 5))
    before = terminal.selected_text()
    size = (terminal.screen.lines, terminal.screen.columns)
    terminal.resize_terminal()
    assert terminal.selected_text() == before == 'first'
    # Splitter moves smaller than a cell do not invalidate the terminal grid.
    width = terminal.screen.columns * terminal.cell_w
    terminal.resize(width, terminal.height())
    qtbot.wait(20)
    terminal.resize(width + terminal.cell_w - 1, terminal.height())
    qtbot.wait(20)
    assert (terminal.screen.lines, terminal.screen.columns) == size
    assert terminal.selected_text() == before


def test_double_click_words_and_remote_mouse(qtbot, terminal, monkeypatch):
    def double(column, modifier=Qt.KeyboardModifier.NoModifier):
        pos = QPoint(column * terminal.cell_w + terminal.cell_w // 2, terminal.cell_h * 3 // 2)
        qtbot.mouseDClick(terminal, Qt.MouseButton.LeftButton, modifier=modifier, pos=pos)
        qtbot.mouseRelease(terminal, Qt.MouseButton.LeftButton, modifier=modifier, pos=pos)
    double(8)
    assert terminal.selected_text() == 'café界'
    double(12)  # Wide-character continuation cell.
    assert terminal.selected_text() == 'café界'
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    terminal.stream.feed(b'\x1b[?1000h\x1b[?1006h')
    double(8)
    assert sent and terminal.selected_text() == ''
    sent.clear()
    double(8, Qt.KeyboardModifier.ShiftModifier)
    assert terminal.selected_text() == 'café界'
    assert not sent


def test_selection_autoscroll_both_directions(qtbot, terminal):
    from PyQt6.QtCore import QPointF
    terminal.stream.feed(b'\r\n' + b'\r\n'.join(f'line{i:03}'.encode() for i in range(80)))
    offset = terminal.selection_offset()
    terminal.selection_anchor = (offset, 0)
    terminal.selection_end = (offset, 0)
    terminal.selecting = True
    terminal.selection_pointer = QPointF(0, -10)
    terminal.selection_timer.start()
    qtbot.waitUntil(lambda: terminal.selection_offset() < offset)
    terminal.selection_timer.stop()
    assert terminal.selected_text().startswith('line')
    assert '\n' in terminal.selected_text()
    # Reverse through the same history without losing the original anchor.
    terminal.selection_pointer = QPointF(terminal.cell_w * 7, terminal.height() + 10)
    terminal.selection_timer.start()
    qtbot.waitUntil(lambda: terminal.selection_offset() == offset)
    terminal.selection_timer.stop()
    assert terminal.selected_text().splitlines()[-1] == 'line079'
    qtbot.mouseRelease(terminal, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert not terminal.selection_timer.isActive()
    terminal.clear_selection()
    assert terminal.selected_text() == ''


@pytest.mark.parametrize('key,mods,expected', [
    (Qt.Key.Key_F1, Qt.KeyboardModifier.ControlModifier, b'\x1b[1;5P'),
    (Qt.Key.Key_F5, Qt.KeyboardModifier.ShiftModifier, b'\x1b[15;2~'),
    (Qt.Key.Key_F12, Qt.KeyboardModifier.AltModifier, b'\x1b[24;3~'),
    (Qt.Key.Key_Delete, Qt.KeyboardModifier.ControlModifier, b'\x1b[3;5~'),
    (Qt.Key.Key_PageDown, Qt.KeyboardModifier.AltModifier, b'\x1b[6;3~'),
    (Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, b'\x1b[1;6A'),
    (Qt.Key.Key_PageUp, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, b'\x1b[5;6~'),
    (Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier, b'\t'),
    (Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier, b'\x1b[Z'),
])
def test_fullscreen_keyboard(qtbot, terminal, monkeypatch, key, mods, expected):
    sent = []
    monkeypatch.setattr(terminal, 'send', sent.append)
    terminal.stream.feed(b'\x1b[?1049h\x1b[?1h')
    qtbot.keyClick(terminal, key, modifier=mods)
    assert sent == [expected]
    terminal.stream.feed(b'\x1b[?1049l')
    assert 'first alpha' in terminal.screen.display[0]


def test_word_drag_and_punctuation(qtbot, terminal):
    terminal.stream.feed(b'\x1b[Hfoo_bar:: next')
    pos = QPoint(2 * terminal.cell_w, terminal.cell_h // 2)
    qtbot.mouseDClick(terminal, Qt.MouseButton.LeftButton, pos=pos)
    assert terminal.selected_text() == 'foo_bar'
    end = QPoint(11 * terminal.cell_w, terminal.cell_h // 2)
    qtbot.mouseMove(terminal, end)
    qtbot.mouseRelease(terminal, Qt.MouseButton.LeftButton, pos=end)
    assert terminal.selected_text() == 'foo_bar:: next'
    pos = QPoint(8 * terminal.cell_w, terminal.cell_h // 2)
    qtbot.mouseDClick(terminal, Qt.MouseButton.LeftButton, pos=pos)
    qtbot.mouseRelease(terminal, Qt.MouseButton.LeftButton, pos=pos)
    assert terminal.selected_text() == '::'


def test_alternate_screen_does_not_autoscroll_shell(qtbot, terminal):
    from PyQt6.QtCore import QPointF
    terminal.stream.feed(b'\r\nold shell' * 60)
    history = list(terminal.screen.history.top)
    terminal.stream.feed(b'\x1b[?1049hfullscreen')
    terminal.selection_anchor = terminal.selection_end = (0, 0)
    terminal.selecting = True
    terminal.selection_pointer = QPointF(0, -20)
    terminal.selection_timer.start()
    terminal.scroll_selection()
    assert not terminal.selection_timer.isActive()
    assert list(terminal.screen.history.top) == history
    assert terminal.screen.display[0].startswith('fullscreen')
    terminal.clear_selection()


def test_ctrl_c_during_continuous_output(qtbot, monkeypatch, tmp_path):
    import sys
    import time

    producer = tmp_path / 'flood.py'
    producer.write_text(
        'import os, signal\n'
        'signal.signal(signal.SIGINT, lambda *_: os._exit(0))\n'
        'while True:\n'
        '    os.write(1, b"\\x1b[H\\x1b[31m" + b"X" * 2048)\n'
    )
    launcher = tmp_path / 'flood'
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{producer}"\n')
    launcher.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(launcher)])
    widget = ssh.Terminal(dict(host='localhost', port=22, username='', identity_file=''))
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.show()
    try:
        qtbot.waitUntil(lambda: 'X' in ''.join(widget.screen.display), timeout=2000)
        qtbot.wait(150)
        start = time.monotonic()
        qtbot.keyClick(widget, Qt.Key.Key_C, modifier=Qt.KeyboardModifier.ControlModifier)
        qtbot.waitUntil(lambda: widget.process.poll() is not None, timeout=1000)
        assert widget.process.returncode == 0
        assert time.monotonic() - start < 1
    finally:
        widget.stop()
