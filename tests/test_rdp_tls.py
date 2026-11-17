"""Real loopback TLS certificate rejection, without a simulated RDP login."""
import shutil
import socket
import ssl
import subprocess
import threading

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
from remote_manager.protocols.rdp import RdpSession


def test_real_untrusted_tls_certificate_is_rejected(qtbot, tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('openssl required for the local TLS certificate test')
    key, cert = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=unircm-loopback-test', '-keyout', str(key), '-out', str(cert)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    port = listener.getsockname()[1]
    errors = []
    def serve():
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(5)
                # Read the client's TPKT negotiation before selecting TLS (not NLA).
                header = connection.recv(4)
                if len(header) != 4:
                    raise AssertionError('Missing RDP negotiation header')
                remaining = int.from_bytes(header[2:4], 'big') - 4
                while remaining:
                    part = connection.recv(remaining)
                    if not part:
                        raise AssertionError('Incomplete RDP negotiation')
                    remaining -= len(part)
                connection.sendall(bytes.fromhex('030000130ed000000000000200080001000000'))
                try:
                    with context.wrap_socket(connection, server_side=True) as tls:
                        tls.recv(1024)
                except (ssl.SSLError, ConnectionError):
                    pass  # Expected: client rejects the self-signed certificate.
        except Exception as error:
            errors.append(error)
        finally:
            listener.close()
    server = threading.Thread(target=serve, daemon=True)
    server.start()
    session = RdpSession(dict(host='127.0.0.1', port=port, username='test', password='test'))
    qtbot.addWidget(session)
    prompts = []
    timer = QTimer()
    def reject():
        box = getattr(session, 'cert_box', None)
        if isinstance(box, QMessageBox):
            prompts.append(box.informativeText())
            assert box.defaultButton().text() == 'Reject'
            box.defaultButton().click()
    timer.timeout.connect(reject)
    timer.start(10)
    try:
        with qtbot.waitSignal(session.exited, timeout=15000) as result:
            pass
        assert result.args[0] != 0
        assert len(prompts) == 1
        assert '127.0.0.1' in prompts[0]
        assert 'unircm-loopback-test' in prompts[0]
        assert not session.worker.accept_cert
        assert session.session_status.state == 'error'
    finally:
        timer.stop()
        session.stop()
        server.join(timeout=6)
        listener.close()
    assert not server.is_alive()
    assert not errors
