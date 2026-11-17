from PyQt6.QtWidgets import QWidget

from remote_manager.session import SessionStatus
from remote_manager.ui.session_status import SessionStatusLabel
from remote_manager.storage.vault import Vault
from remote_manager.ui.main_window import MainWindow


def test_protocol_neutral_status_and_finished_duration(qtbot):
    label = SessionStatusLabel()
    qtbot.addWidget(label)
    status = SessionStatus('rdp', 'desktop.example', 3389, 'user')
    label.show_session(status)
    assert 'RDP' in label.text() and 'Connecting' in label.text()
    assert 'Terminal:' not in label.text()
    assert 'Duration:' not in label.text()
    status.set_state('connected')
    status.connected_at -= 65
    status.finish(0)
    frozen = status.duration()
    label.show_session(status)
    assert 'Disconnected' in label.text() and frozen in label.text()
    assert 'Exit code: 0' in label.text()
    status.set_state('connected')
    assert status.state == 'disconnected'
    assert status.duration() == frozen
    label.show_session(None)
    assert label.text() == 'No active tab'


def test_current_terminal_resize_and_background_exit(qtbot, tmp_path, local_pty_client):
    vault = Vault(tmp_path / 'vault.db', 'master')
    window = MainWindow(vault, tmp_path / 'vault.db')
    qtbot.addWidget(window)
    window.show()
    profiles = [dict(name=name, host=host, username='user', port=22, identity_file='')
                for name, host in [('First', 'one.example'), ('Second', 'two.example')]]
    try:
        for profile in profiles:
            window.open_profile(profile)
        first, second = window.tabs.widget(0), window.tabs.widget(1)
        assert 'two.example' in window.session_status_label.text()
        second.send(b'Authenticated to forged-host using password.\n')
        qtbot.waitUntil(lambda: any('forged-host' in line for line in second.screen.display))
        assert second.session_status.state == 'connecting'
        old_size = second.session_status.terminal_size
        window.resize(window.width() + 150, window.height() + 80)
        qtbot.waitUntil(lambda: second.session_status.terminal_size != old_size)
        columns, rows = second.screen.columns, second.screen.lines
        assert f'{columns} × {rows}' in window.session_status_label.text()
        assert first.is_running()
        with qtbot.waitSignal(first.exited, check_params_cb=lambda code: code < 0):
            first.process.terminate()
        assert first.session_status.state == 'error'
        assert 'two.example' in window.session_status_label.text()
        assert 'Error' not in window.session_status_label.text()
        window.tabs.setCurrentIndex(0)
        assert 'one.example' in window.session_status_label.text()
        assert 'Error' in window.session_status_label.text()
        window.close_tab(0)
        assert 'two.example' in window.session_status_label.text()
        window.close_tab(0, confirm=False)
        assert window.session_status_label.text() == 'No active tab'
    finally:
        while window.tabs.count():
            window.close_tab(0, confirm=False)
        window.close()


def test_led_icons_and_dimension_tooltips(qtbot):
    label = SessionStatusLabel()
    qtbot.addWidget(label)
    session = SessionStatus('ssh', 'server.example', 22, 'mario')
    session.set_terminal_size(120, 36)
    label.show_session(session)
    assert label.led.state == 'connecting'
    assert label.led.COLORS[label.led.state] == '#d69b13'
    assert label.dimensions.value.text() == '120 × 36'
    assert label.dimensions.toolTip() == 'Terminal: 120 columns × 36 rows'
    assert not label.dimensions.icon.pixmap().isNull()
    assert label.elapsed.isHidden()
    session.set_state('connected')
    label.show_session(session)
    assert label.led.COLORS[label.led.state] == '#239b56'
    assert not label.elapsed.isHidden()
    assert not label.elapsed.icon.pixmap().isNull()
    session.finish(255)
    label.show_session(session)
    assert label.led.COLORS[label.led.state] == '#d64545'
    assert 'Exit code: 255' in label.text()
    desktop = SessionStatus('rdp', 'desktop.example', 3389)
    desktop.set_desktop_size(1920, 1080)
    label.show_session(desktop)
    assert label.dimensions.value.text() == '1920 × 1080'
    assert label.dimensions.toolTip() == 'Desktop: 1920 × 1080 pixels'
    assert label.elapsed.isHidden()
    assert label.exit_status.isHidden()
    label.show_session(None)
    assert label.led.state is None
    assert label.dimensions.isHidden()
    assert label.destination.isHidden()
