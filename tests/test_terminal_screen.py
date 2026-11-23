import pyte
import pytest

from remote_manager.terminal.screen import TerminalScreen, TerminalStream


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


@pytest.mark.parametrize('alternate', [False, True])
def test_private_cursor_position_query_and_standard_device_status(alternate):
    responses = []
    screen = TerminalScreen(40, 12, responses.append)
    stream = pyte.ByteStream(screen)
    if alternate:
        stream.feed(b'\x1b[?1049h')
    stream.feed(b'\x1b[4;10r\x1b[?6h\x1b[3;5H\x1b[?6')
    stream.feed(b'n\x1b[6n\x1b[5n\x1b[?255nOK')
    assert responses == ['\x1b[?3;5R', '\x1b[3;5R', '\x1b[0n']
    assert screen.display[5][4:6] == 'OK'


def test_secondary_device_attributes_does_not_send_a_primary_reply():
    responses = []
    screen = TerminalScreen(40, 12, responses.append)
    stream = TerminalStream(screen)
    stream.feed(b'\x1b[c\x1b[>0')
    stream.feed(b'c\x1b[>c\x1b[?6nOK')
    assert responses == ['\x1b[?6c', '\x1b[?1;1R']
    assert screen.display[0].startswith('OK')


@pytest.mark.parametrize('alternate', [False, True])
def test_dec_line_drawing_in_utf8(alternate):
    screen = TerminalScreen(40, 12)
    stream = TerminalStream(screen)
    if alternate:
        stream.feed(b'\x1b[?1049h')
    stream.feed(b'\x1b(')
    stream.feed(b'0lqxk\x1b(B qx ')
    stream.feed(b'\x1b)0\x0emqxj\x0f ')
    stream.feed('caffè'.encode())
    assert screen.display[0].rstrip() == '┌─│┐ qx └─│┘ caffè'
    if alternate:
        stream.feed(b'\x1b[?1049lqx')
        assert screen.display[0].rstrip() == 'qx'


@pytest.mark.parametrize('alternate', [False, True])
@pytest.mark.parametrize('split', [False, True])
def test_weather_emoji_preserves_following_text_and_cell_positions(alternate, split):
    screen = TerminalScreen(40, 4)
    stream = pyte.ByteStream(screen)
    if alternate:
        stream.feed(b'\x1b[?1049h')
    weather = '🌤️ +7°C ║'
    data = weather.encode()
    if split:
        stream.feed(data[:5])
        stream.feed(data[5:])
    else:
        stream.feed(data)
    assert screen.display[0].rstrip() == weather
    assert screen.buffer[0][0].data == '🌤️'
    assert screen.buffer[0][1].data == ''
    assert screen.buffer[0][8].data == '║'
