import pyte
import pytest

from remote_manager.terminal.screen import TerminalScreen


@pytest.mark.parametrize('mode', [47, 1047, 1049])
def test_alternate_buffer_preserves_shell_and_history(mode):
    screen = TerminalScreen(30, 8)
    stream = pyte.ByteStream(screen)
    stream.feed(b'normal shell\r\n' * 12)
    before = screen.display[:]
    cursor = (screen.cursor.x, screen.cursor.y)
    history = list(screen.history.top)
    stream.feed(f'\x1b[?{mode}h\x1b[2J\x1b[H'.encode() + b'editor\r\n' * 20 + b'\x1b[?6l\x1b[?25l')
    assert screen.is_alternate
    assert list(screen.history.top) == history
    assert any('editor' in line for line in screen.display)
    screen.prev_page()  # Full-screen contents must not be replaced by shell history.
    assert any('editor' in line for line in screen.display)
    stream.feed(f'\x1b[?{mode}l'.encode())
    assert not screen.is_alternate
    assert screen.display == before
    assert (screen.cursor.x, screen.cursor.y) == cursor
    assert list(screen.history.top) == history


def test_alternate_resize_and_terminal_responses():
    responses = []
    screen = TerminalScreen(40, 12, responses.append)
    stream = pyte.ByteStream(screen)
    stream.feed(b'shell\x1b[?1049h\x1b[?4m\x1b[3;5H\x1b[6n')
    assert responses == ['\x1b[3;5R']
    screen.resize(10, 32)
    stream.feed(b'\x1b[?1049l')
    assert (screen.lines, screen.columns) == (10, 32)
    assert any('shell' in line for line in screen.display)
    stream.feed(b'\x1b[?1049h')
    assert not any('shell' in line for line in screen.display)
    stream.feed(b'\x1bc')
    assert not screen.is_alternate


def test_private_mode_restore_does_not_change_scrolling_margins():
    screen = TerminalScreen(40, 12)
    stream = pyte.ByteStream(screen)
    stream.feed(b'\x1b[2;10r\x1b[4;5H')
    margins = screen.margins
    cursor = (screen.cursor.x, screen.cursor.y)
    stream.feed(b'\x1b[?1000r\x1b[?1006r')
    assert screen.margins == margins
    assert (screen.cursor.x, screen.cursor.y) == cursor
    stream.feed(b'\x1b[r')
    assert screen.margins is None
