import socket
import struct
import threading

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QKeyEvent, QWheelEvent

from PyQt6.QtWidgets import QDialog

from remote_manager.protocols.vnc import VncSession, challenge_response
from remote_manager.storage.vault import Vault
from remote_manager.ui.credentials import ConnectionAuthenticationDialog
from remote_manager.ui.main_window import MainWindow


def test_vnc_des_vector():
    # Fixed standard DES VNC challenge vector, including the 8-byte password limit.
    assert challenge_response(bytes(range(16)), 'password').hex() == 'b866924125c8eebb9debc1db61c538e2'
    assert challenge_response(bytes(range(16)), 'passwordextra') == challenge_response(bytes(range(16)), 'password')


def test_rfb_frame_input_and_shutdown(qtbot, tmp_path, monkeypatch):
    """Wire-level fixture, not a real desktop server interoperability test."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    received = []
    errors = []

    def server():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(4)
                def read(n):
                    data = b''
                    while len(data) < n:
                        part = conn.recv(n-len(data))
                        if not part:
                            raise EOFError()
                        data += part
                    return data
                conn.sendall(b'RFB 003.008\n')
                assert read(12) == b'RFB 003.008\n'
                conn.sendall(b'\x01\x02')
                assert read(1) == b'\x02'
                conn.sendall(bytes(range(16)))
                assert read(16) == challenge_response(bytes(range(16)), 'password')
                conn.sendall(b'\0\0\0\0')
                assert read(1) == b'\x01'
                conn.sendall(struct.pack('!HH', 2, 1) + bytes(16) + struct.pack('!I', 4) + b'test')
                assert read(20)[0] == 0
                assert read(12) == struct.pack('!BBHii', 2, 0, 2, 0, -223)
                assert read(10)[0] == 3
                conn.sendall(b'\0\0\0\x01' + struct.pack('!HHHHi', 0, 0, 2, 1, 0) + b'\xff\0\0\0\0\xff\0\0')
                assert read(10)[1] == 1
                conn.sendall(b'\0\0\0\x01' + struct.pack('!HHHHi', 0, 0, 3, 2, -223))
                assert read(10) == struct.pack('!BBHHHH', 3, 0, 0, 0, 3, 2)
                while True:
                    kind = read(1)
                    sizes = {b'\x04': 7, b'\x05': 5}
                    received.append(kind + read(sizes[kind]))
        except EOFError:
            pass
        except Exception as error:
            errors.append(error)
        finally:
            listener.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    path = tmp_path / 'vnc.db'
    vault = Vault(path, 'master')
    hook_output = tmp_path / 'local-commands'
    profile_id = vault.save(dict(name='Desktop', protocol='vnc', host='127.0.0.1',
                                 port=listener.getsockname()[1], username='', identity_file='',
                                 authentication='prompt_password', password='saved-password',
                                 before_connect_command=f'printf before > "{hook_output}"',
                                 after_disconnect_command=f'sleep 0.1; printf after >> "{hook_output}"'))
    window = MainWindow(vault, path)
    qtbot.addWidget(window)

    def enter_password(dialog):
        def submit():
            assert tuple(dialog.inputs) == ('password',)
            dialog.inputs['password'].setText('password')
            dialog.connect_button.click()

        QTimer.singleShot(0, submit)
        return QDialog.exec(dialog)

    monkeypatch.setattr(ConnectionAuthenticationDialog, 'exec', enter_password)
    session = window.open_profile(vault.profiles(profile_id)[0])
    try:
        qtbot.waitUntil(lambda: session.canvas.image.width() == 3)
        assert session.session_status.state == 'connected'
        assert hook_output.read_text() == 'before'
        assert session.canvas.image.pixelColor(0, 0).red() == 255
        assert session.canvas.image.pixelColor(1, 0).green() == 255
        session.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, 'a'))
        session.canvas.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, 'a'))
        qtbot.waitUntil(lambda: len(received) >= 2)
        assert received[:2] == [struct.pack('!BBHI', 4, 1, 0, 97), struct.pack('!BBHI', 4, 0, 0, 97)]
        canvas = session.canvas
        position = QPointF(canvas.target().center())
        wheel = QWheelEvent(position, position, QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        canvas.wheelEvent(wheel)
        qtbot.waitUntil(lambda: len(received) == 4)
        assert received[2][:2] == bytes((5, 8))
        assert received[3] == bytes((5, 0)) + received[2][2:]
        session.set_view_only(True)
        assert not canvas.update_pointer(wheel)

        session.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, 'b'))
        assert not session.canvas.pressed
    finally:
        window.close_tab(0, confirm=False)
        thread.join(5)
    assert not errors
    assert window.tabs.count() == 0
    assert vault.profiles(profile_id)[0]['password'] == 'saved-password'
    qtbot.waitUntil(lambda: hook_output.read_text() == 'beforeafter')
    window.close()


def test_no_unauthenticated_fallback(qtbot):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    selected = []
    def server():
        conn, _ = listener.accept()
        with conn:
            conn.settimeout(4)
            conn.sendall(b'RFB 003.008\n')
            conn.recv(12)
            conn.sendall(b'\x01\x01')  # only None authentication
            selected.append(conn.recv(1))
        listener.close()
    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    session = VncSession(dict(protocol='vnc', host='127.0.0.1', port=listener.getsockname()[1], password='secret'))
    qtbot.addWidget(session)
    try:
        qtbot.waitUntil(lambda: session.session_status.state == 'error')
    finally:
        session.stop()
        thread.join(5)
    assert selected == [b'']
    assert 'secret' not in session.result.text()
