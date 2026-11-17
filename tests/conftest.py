"""Test configuration. Keep protocol integration tests separate from GUI smoke tests."""

import pytest


@pytest.fixture
def local_pty_client(tmp_path, monkeypatch):
    from remote_manager.terminal import ssh

    # The launcher ignores OpenSSH options and runs a real child on the PTY.
    launcher = tmp_path / 'pty-client'
    launcher.write_text('#!/bin/sh\nexec cat\n')
    launcher.chmod(0o700)
    monkeypatch.setattr(ssh, 'ssh_command', lambda profile: [str(launcher)])
