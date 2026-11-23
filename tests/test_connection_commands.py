from PyQt6.QtCore import Qt

from remote_manager.terminal.ssh import Terminal


def start_terminal(command, tmp_path):
    return Terminal(dict(protocol='ssh', host='localhost', username='', port=22,
                         identity_file='', before_connect_command=command,
                         after_disconnect_command=f'touch "{tmp_path / "after"}"'))


def command_prompt(qtbot, terminal):
    qtbot.waitUntil(lambda: terminal.connection_commands.prompt is not None)
    prompt = terminal.connection_commands.prompt
    assert terminal.is_running()
    assert terminal.process is None
    assert 'exited with code 7' in prompt.text()
    assert all(not button.icon().isNull() and button.toolTip() for button in prompt.buttons())
    return prompt


def test_cancel_prevents_connection(qtbot, tmp_path):
    terminal = start_terminal('exit 7', tmp_path)
    qtbot.addWidget(terminal)
    try:
        prompt = command_prompt(qtbot, terminal)
        qtbot.keyClick(prompt, Qt.Key.Key_Escape)
        assert terminal.session_status.state == 'disconnected'
        assert terminal.process is None
        assert not terminal.is_running()
        assert not (tmp_path / 'after').exists()
    finally:
        terminal.stop()


def test_continue_starts_transport_despite_command_failure(qtbot, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(Terminal, 'start_transport', lambda *args: started.append(True))
    terminal = start_terminal('exit 7', tmp_path)
    qtbot.addWidget(terminal)
    try:
        prompt = command_prompt(qtbot, terminal)
        next(button for button in prompt.buttons() if button.text() == 'Continue').click()
        assert started == [True]
    finally:
        terminal.stop()


def test_retry_runs_command_again_before_starting_transport(qtbot, tmp_path, monkeypatch):
    attempts = tmp_path / 'attempts'
    started = []
    monkeypatch.setattr(Terminal, 'start_transport', lambda *args: started.append(attempts.read_text()))
    terminal = start_terminal(
        f'if test ! -e "{attempts}"; then printf 1 > "{attempts}"; exit 7; fi; printf 2 >> "{attempts}"',
        tmp_path,
    )
    qtbot.addWidget(terminal)
    try:
        prompt = command_prompt(qtbot, terminal)
        assert not started
        next(button for button in prompt.buttons() if button.text() == 'Retry').click()
        qtbot.waitUntil(lambda: started == ['12'])
    finally:
        terminal.stop()
