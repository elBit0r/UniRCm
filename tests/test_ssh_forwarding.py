"""Forwarding validation, encrypted persistence and real OpenSSH TCP traffic."""
import socket
import struct
import threading

import pytest

from remote_manager.ssh_options import forwarding_arguments, validate_advanced
from remote_manager.storage.vault import Vault
from remote_manager.ui.ssh_advanced import AdvancedSSHOptions
from remote_manager.terminal import ssh
from test_ssh import ssh_server


def rule(kind='L', port=18080, **kwargs):
    return dict(enabled=True, type=kind, bind='127.0.0.1', port=port,
                host='' if kind == 'D' else 'localhost', target_port=0 if kind == 'D' else 80, **kwargs)


def test_forwarding_editor_storage_and_arguments(qtbot, tmp_path):
    rules = [rule(), rule('R', 18081), rule('D', 18082)]
    rules[1].update(bind='::1', host='::1')
    editor = AdvancedSSHOptions({'forwards': rules})
    qtbot.addWidget(editor)
    assert editor.options()['forwards'] == rules
    editor.forwards.table.cellWidget(0, 0).setChecked(False)
    rules[0]['enabled'] = False
    assert editor.options()['forwards'] == rules
    args = forwarding_arguments(rules)
    assert args[:4] == ['-R', '[::1]:18081:[::1]:80', '-D', '127.0.0.1:18082']
    assert 'ExitOnForwardFailure=yes' in args
    assert '-L' not in args
    path = tmp_path / 'vault.db'
    with_vault = Vault(path, 'test master')
    profile = dict(name='Tunnels', host='localhost', username='', identity_file='', port=22,
                   ssh_advanced={'forwards': rules})
    pid = with_vault.save(profile)
    with_vault.close()
    assert b'forwards' not in path.read_bytes()
    reopened = Vault(path, 'test master')
    assert reopened.profiles(pid)[0]['ssh_advanced']['forwards'] == rules
    reopened.close()
    editor.forwards.table.setCurrentCell(1, 1)
    editor.forwards.remove_rule()
    assert len(editor.options()['forwards']) == 2


@pytest.mark.parametrize('change', [dict(port=0), dict(port=True), dict(target_port=65536),
    dict(bind=''), dict(bind='::bad::'), dict(host='host:80'), dict(host='host;command'),
    dict(type='X'), dict(enabled=1)])
def test_invalid_forwarding(change):
    item = rule()
    item.update(change)
    with pytest.raises(ValueError):
        validate_advanced({'forwards': [item]})


def test_duplicate_local_and_socks_listener():
    with pytest.raises(ValueError):
        forwarding_arguments([rule(), rule('D')])
    assert forwarding_arguments([dict(rule(), enabled=False)]) == []


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def receive(sock, size):
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        assert part
        data += part
    return data


def test_real_local_remote_dynamic_traffic_and_cleanup(qtbot, ssh_server):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(10)
    target = listener.getsockname()[1]
    errors = []
    def echo():
        try:
            for _ in range(3):
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(5)
                    conn.sendall(receive(conn, 12))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=echo, daemon=True)
    thread.start()
    ports = [free_port() for _ in range(3)]
    rules = [rule(kind, port) for kind, port in zip(('L', 'R', 'D'), ports)]
    for item in rules[:2]:
        item.update(host='127.0.0.1', target_port=target)
    term = ssh.Terminal(dict(ssh_server, ssh_advanced={'forwards': rules}))
    qtbot.addWidget(term)
    try:
        term.send(b"printf '\\nTUNNELS_READY\\n'\r")
        qtbot.waitUntil(lambda: any(line.strip() == 'TUNNELS_READY' for line in term.screen.display), timeout=15000)
        for kind, port in zip(('L', 'R', 'D'), ports):
            with socket.create_connection(('127.0.0.1', port), timeout=5) as conn:
                if kind == 'D':
                    conn.sendall(b'\x05\x01\x00')
                    assert receive(conn, 2) == b'\x05\x00'
                    conn.sendall(b'\x05\x01\x00\x01' + socket.inet_aton('127.0.0.1') + struct.pack('!H', target))
                    assert receive(conn, 10)[:2] == b'\x05\x00'
                conn.sendall(b'TUNNEL_PROBE')
                assert receive(conn, 12) == b'TUNNEL_PROBE'
        assert term.is_running()
    finally:
        term.stop()
        listener.close()
        thread.join(timeout=6)
    assert not errors
    for port in ports:
        with pytest.raises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=.5)


def test_real_occupied_listener_stops_session(qtbot, ssh_server):
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        term = ssh.Terminal(dict(ssh_server, ssh_advanced={'forwards': [rule(port=port)]}))
        qtbot.addWidget(term)
        try:
            qtbot.waitUntil(lambda: not term.is_running(), timeout=15000)
            assert term.process.returncode != 0
            assert 'forward' in '\n'.join(term.screen.display).lower()
        finally:
            term.stop()
