"""RDP feature boundaries and Qt ownership; no simulated server-login claims."""
import ctypes as C

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt, QEvent, QTimer
from PyQt6.QtGui import QImage, QWheelEvent, QFocusEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from remote_manager.protocols.rdp import RdpSession, CLIP_ORIGIN, CLIP_LIMIT


@pytest.fixture
def desktop(qtbot, monkeypatch):
    session = RdpSession(dict(host='localhost', port=1, password='test', rdp_options={'clipboard': True}))
    qtbot.addWidget(session)
    session.stop()
    monkeypatch.setattr(session.worker, 'start', lambda: None)
    session.worker.cancel.clear()
    session.resize(900, 700)
    session.show()
    session.view.image = QImage(800, 600, QImage.Format.Format_RGB32)
    session.view.image.fill(Qt.GlobalColor.white)
    qtbot.wait(10)
    yield session
    session.stop()


def test_fullscreen_roundtrip_and_shortcut(qtbot, desktop):
    worker, view = desktop.worker, desktop.view
    desktop.set_fullscreen(True)
    assert desktop.fullscreen and desktop.desktop_window.isFullScreen()
    assert desktop.desktop_window.exit_fullscreen.isVisible()
    assert view.parentWidget() is desktop.desktop_window
    qtbot.mouseClick(desktop.desktop_window.exit_fullscreen, Qt.MouseButton.LeftButton)
    assert not desktop.fullscreen and not desktop.detached
    assert view.parentWidget() is desktop
    desktop.detach_desktop()
    sent = []
    view.send = lambda name, *args: sent.append((name, args))
    qtbot.keyClick(view, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert desktop.fullscreen
    assert not any(name == 'key' and args[1] == 28 for name, args in sent)
    desktop.show_desktop()
    assert desktop.desktop_window.isFullScreen()
    desktop.set_fullscreen(False)
    assert desktop.detached and not desktop.desktop_window.isFullScreen()
    assert desktop.worker is worker and desktop.view is view
    desktop.desktop_window.showMaximized()
    desktop.set_fullscreen(True)
    desktop.set_fullscreen(False)
    assert desktop.desktop_window.isMaximized()
    desktop.set_fullscreen(True)
    desktop.stop()
    assert not desktop.desktop_window.isVisible()


def test_cursor_snapshot_hotspot_hidden_default(qtbot, desktop):
    worker, view = desktop.worker, desktop.view
    data = C.create_string_buffer(bytes([20, 30, 40, 255]) * 16)
    worker.receive_pointer(data, 4, 4, 2, 3)
    C.memset(data, 0, 64)
    qtbot.waitUntil(lambda: view.remote_pointer is not None)
    assert view.remote_pointer[0].pixelColor(0, 0).getRgb() == (20, 30, 40, 255)
    assert not view.cursor().pixmap().isNull()
    assert view.cursor().hotSpot().x() >= 0
    worker.receive_pointer(None, -1, 0, 0, 0)
    qtbot.waitUntil(lambda: view.cursor().shape() == Qt.CursorShape.BlankCursor)
    worker.receive_pointer(None, 0, 0, 0, 0)
    qtbot.waitUntil(lambda: view.cursor().shape() == Qt.CursorShape.ArrowCursor)


def test_mouse_coordinates_wheel_and_focus_cleanup(qtbot, desktop):
    view = desktop.view
    sent = []
    view.send = lambda name, *args: sent.append((name, args))
    point = view.target().center()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=point)
    assert sent[-1][1][0] == 0x9000
    _, x, y = sent[-1][1]
    assert abs(x - 400) <= 2 and abs(y - 300) <= 2
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=point)
    assert sent[-1][1][0] == 0x1000
    def wheel(x, y):
        view.wheelEvent(QWheelEvent(QPointF(point), QPointF(point), QPoint(), QPoint(x, y),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
    sent.clear()
    wheel(0, 60)
    assert not sent
    wheel(0, 180)
    assert [args[0] for _, args in sent] == [0x0200 | 120] * 2
    wheel(-120, -120)
    assert [args[0] for _, args in sent[-2:]] == [0x0400 | 392, 0x0200 | 392]
    qtbot.mousePress(view, Qt.MouseButton.RightButton, pos=point)
    view.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert sent[-1] == ('mouse', (0x2000, x, y))
    assert not view.mouse_buttons


def test_clipboard_focus_limits_unicode_and_no_echo(qtbot, desktop, monkeypatch):
    worker, view = desktop.worker, desktop.view
    monkeypatch.setattr(view, 'hasFocus', lambda: True)
    QApplication.clipboard().setText('local café\n界')
    desktop.sync_local_clipboard()
    assert worker.local_clipboard == 'local café\r\n界\x00'.encode('utf-16-le')
    worker.local_clipboard = None
    view.send = lambda *args: None
    qtbot.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert worker.local_clipboard == 'local café\r\n界\x00'.encode('utf-16-le')
    worker.local_clipboard = None
    raw = 'remote café\r\n界\x00'.encode('utf-16-le')
    data = C.create_string_buffer(raw)
    worker.receive_clipboard(data, len(raw))
    qtbot.waitUntil(lambda: QApplication.clipboard().text() == 'remote café\n界')
    assert bytes(QApplication.clipboard().mimeData().data(CLIP_ORIGIN)) == desktop.clipboard_origin
    desktop.sync_local_clipboard()
    assert worker.local_clipboard is None
    worker.receive_clipboard(None, -1)
    qtbot.waitUntil(lambda: worker.clipboard_requested)
    worker.clipboard_requested = False
    monkeypatch.setattr(view, 'hasFocus', lambda: False)
    worker.receive_clipboard(data, len(raw))
    qtbot.wait(10)
    desktop.sync_local_clipboard()
    assert worker.local_clipboard is None
    # A malformed or oversized remote payload must not replace local clipboard text.
    QApplication.clipboard().setText('keep')
    monkeypatch.setattr(view, 'hasFocus', lambda: True)
    worker.receive_clipboard(C.create_string_buffer(b'xx'), 2)
    worker.receive_clipboard(data, CLIP_LIMIT + 2)
    qtbot.wait(10)
    assert QApplication.clipboard().text() == 'keep'
    worker.offer_clipboard('\ud800')
    assert worker.local_clipboard is None
    worker.offer_clipboard('x' * CLIP_LIMIT)
    assert worker.local_clipboard is None
    worker.options['clipboard'] = False
    worker.receive_clipboard(data, len(raw))
    assert worker.latest_clipboard is None


@pytest.mark.parametrize('changed,accept', [(False, False), (True, False), (True, True)])
def test_certificate_default_reject_session_only(qtbot, desktop, changed, accept):
    def answer():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        assert box.defaultButton().text() == 'Reject'
        assert box.textFormat() == Qt.TextFormat.PlainText
        assert ('changed' in box.text()) == changed
        assert '<b>not markup</b>' in box.informativeText()
        button = next(b for b in box.buttons() if b.text() == ('Accept for this session' if accept else 'Reject'))
        button.click()
    QTimer.singleShot(0, answer)
    desktop.verify_certificate('localhost', '<b>not markup</b>', 'SHA256:local-test', changed)
    assert desktop.worker.cert_answer.is_set()
    assert desktop.worker.accept_cert == accept


def test_native_channel_handlers(tmp_path):
    import os
    from pathlib import Path
    import shlex
    import shutil
    import subprocess
    if not shutil.which('pkg-config') or not shutil.which('cc'):
        pytest.skip('FreeRDP development tools required for native handler checks')
    flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'freerdp-client3', 'freerdp3', 'winpr3'],
                           text=True, capture_output=True)
    if flags.returncode:
        pytest.skip('FreeRDP development headers required for native handler checks')
    executable = tmp_path / 'rdp-native-handlers'
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-pthread', '-O2',
                    str(Path(__file__).with_name('rdp_native_harness.c')), '-o', str(executable),
                    *shlex.split(flags.stdout)], check=True, capture_output=True)
    subprocess.run([str(executable)], check=True, timeout=10, capture_output=True)
