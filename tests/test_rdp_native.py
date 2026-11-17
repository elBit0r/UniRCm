"""Native ABI failure/cleanup and Qt input/rendering regressions, not server acceptance tests."""
import ctypes as C
import threading

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

from remote_manager.protocols.rdp import RdpSession, RdpWorker, load_bridge


@pytest.fixture
def bridge():
    try:
        return load_bridge()
    except ValueError:
        pytest.skip('Build the native FreeRDP bridge first')


def test_native_connection_failure_and_cleanup(qtbot, bridge):
    import socket
    # Bound, non-listening socket makes connection refusal deterministic.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        session = RdpSession(dict(host='127.0.0.1', port=listener.getsockname()[1], username='test', password='not-logged'))
        qtbot.addWidget(session)
        try:
            with qtbot.waitSignal(session.exited, timeout=15000) as result:
                pass
            assert result.args[0] != 0
            qtbot.waitUntil(lambda: not session.is_running())
            assert session.session_status.state == 'error'
            assert 'not-logged' not in session.result.text()
        finally:
            session.stop()
        assert session.worker.handle is None
        assert session.worker.credentials is None


def test_frame_ownership_scaled_input_and_focus_release(qtbot, bridge):
    session = RdpSession(dict(host='127.0.0.1', port=1, username='test', password='not-logged'))
    qtbot.addWidget(session)
    session.stop()
    session.resize(800, 600)
    session.show()
    # Receive a transient native buffer, then overwrite it before Qt paints.
    data = C.create_string_buffer(bytes([10, 20, 30, 255]) * 4)
    session.worker.receive_frame(C.addressof(data), 2, 2, 8)
    C.memset(data, 0, 16)
    qtbot.waitUntil(lambda: not session.view.image.isNull())
    assert session.view.image.pixelColor(0, 0).getRgb()[:3] == (30, 20, 10)
    assert session.session_status.desktop_size == (2, 2)
    assert session.view.target().width() == session.view.target().height()
    sent = []
    session.view.send = lambda name, *args: sent.append((name, args))
    qtbot.keyPress(session.view, Qt.Key.Key_Control)
    qtbot.keyPress(session.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    from PyQt6.QtGui import QFocusEvent
    from PyQt6.QtCore import QEvent
    session.view.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert ('key', (0, 29, 0)) in sent
    assert ('key', (0, 46, 0)) in sent
    assert ('key', (0x8000, 29, 0)) in sent
    assert ('key', (0x8000, 46, 0)) in sent
    assert not session.view.pressed
    qtbot.keyClick(session.view, Qt.Key.Key_Tab)
    assert ('key', (0, 15, 0)) in sent
    assert ('key', (0x8000, 15, 0)) in sent


def test_certificate_rejected_on_cancel(qtbot, bridge):
    worker = RdpWorker(bridge, dict(host='localhost', port=3389), None)
    result = []
    thread = threading.Thread(target=lambda: result.append(worker.verify(b'localhost', b'untrusted', b'fingerprint', 1)))
    thread.start()
    worker.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result == [0]
