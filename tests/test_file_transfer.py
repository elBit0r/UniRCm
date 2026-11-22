"""Real OpenSSH/SFTP roundtrip, exclusive writes, cancellation and Qt browser."""
import os
import threading

import pytest
from PyQt6.QtCore import QDateTime, QLocale, QMimeData, QUrl, QPointF, Qt
from PyQt6.QtGui import QDropEvent

from remote_manager.terminal.sftp import SFTPClient, SFTPError
from remote_manager.terminal.ssh import Terminal
from remote_manager.ui.file_transfer import FileTransferDialog
from test_ssh import ssh_server


@pytest.fixture
def terminal(qtbot, ssh_server):
    terminal = Terminal(ssh_server)
    qtbot.addWidget(terminal)
    try:
        qtbot.waitUntil(terminal.file_transfer_available, timeout=15000)
        yield terminal
    finally:
        terminal.stop()


def test_real_sftp_roundtrip_and_safe_overwrite(terminal, tmp_path):
    source = tmp_path / 'source ü;$(touch NEVER) .bin'
    source.write_bytes(bytes(range(256)) * 400)
    remote = str(tmp_path / 'remote ü;$(touch NEVER) .bin')
    destination = tmp_path / 'download.bin'
    client = SFTPClient(terminal.control_path, terminal.sftp_host)
    progress = []
    try:
        client.upload(str(source), remote, lambda done, total: progress.append((done, total)))
        assert progress[-1] == (source.stat().st_size, source.stat().st_size)
        entry, = (entry for entry in client.listing(str(tmp_path)) if entry.name == os.path.basename(remote))
        assert not entry.directory
        assert entry.size == source.stat().st_size
        client.download(remote, str(destination), lambda *args: None)
        assert destination.read_bytes() == source.read_bytes()
        with pytest.raises((SFTPError, FileExistsError)):
            client.upload(str(source), remote, lambda *args: None)
        with pytest.raises(FileExistsError):
            client.download(remote, str(destination), lambda *args: None)
        source.write_bytes(b'replaced')
        client.upload(str(source), remote, lambda *args: None, overwrite=True)
        client.download(remote, str(destination), lambda *args: None, overwrite=True)
        assert destination.read_bytes() == b'replaced'
        assert not list(tmp_path.glob('*.part'))
        assert not list(tmp_path.glob('.unircm-*'))
        assert terminal.is_running()
    finally:
        client.close()


def test_browser_upload_download_and_drop(qtbot, terminal, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog, QMenu, QToolBar
    source = tmp_path / 'upload.txt'
    source.write_bytes(b'x' * 2048)
    remote_dir = tmp_path / 'remote'
    remote_dir.mkdir()
    local_dir = tmp_path / 'download'
    local_dir.mkdir()
    terminal.sftp_directory = str(remote_dir)
    dialog = FileTransferDialog(terminal)
    terminal.transfer_dialogs.append(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == str(remote_dir)
    prefix = f'{terminal.session_status.username}@{terminal.sftp_host}:'
    assert dialog.path.text() == prefix + str(remote_dir)
    assert not dialog.download_action.isEnabled()
    subdir = remote_dir / 'subdir'
    subdir.mkdir()
    dialog.reload.trigger()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    folder_item = dialog.tree.topLevelItem(0)
    folder_item.setSelected(True)
    assert not dialog.download_action.isEnabled()
    dialog.open_item(folder_item, 0)
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == str(subdir)
    dialog.up.trigger()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == str(remote_dir)
    assert not dialog.forward.isEnabled()
    dialog.back.trigger()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == str(subdir)
    assert dialog.forward.isEnabled()
    dialog.forward.trigger()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == str(remote_dir)
    dialog.root.click()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == '/'
    assert not dialog.up.isEnabled()
    dialog.back.trigger()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.remote_path == str(remote_dir)
    monkeypatch.setattr(dialog, 'confirm', lambda text: True)
    dialog.upload([str(source)])
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert (remote_dir / source.name).read_bytes() == source.read_bytes()
    remote_file = remote_dir / source.name
    remote_file.chmod(0o640)
    mtime = 1_700_000_000
    os.utime(remote_file, (mtime, mtime))
    dialog.path.setText(str(remote_dir))
    qtbot.keyClick(dialog.path, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.path.text() == prefix + str(remote_dir)
    item = dialog.tree.topLevelItem(1)
    locale = QLocale()
    assert item.text(2) == locale.formattedDataSize(2048, 1)
    assert item.text(3) == locale.toString(QDateTime.fromSecsSinceEpoch(mtime), QLocale.FormatType.ShortFormat)
    assert item.text(4) == 'rw-r-----'
    item.setSelected(True)
    assert dialog.download_action.isEnabled()
    toolbar = dialog.findChild(QToolBar)
    assert dialog.download_action in toolbar.actions()
    assert toolbar.widgetForAction(dialog.download_action).toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    menus = []
    monkeypatch.setattr(QMenu, 'exec', lambda menu, position: menus.append(menu.actions()))
    dialog.show_file_menu(dialog.tree.visualItemRect(item).center())
    assert dialog.download_action in menus[0]
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: str(local_dir))
    dialog.download_action.trigger()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert (local_dir / source.name).read_bytes() == source.read_bytes()
    assert dialog.gauge.value() == 100
    called = []
    monkeypatch.setattr(terminal, 'open_file_transfer', lambda **kwargs: called.append(kwargs))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    terminal.dropEvent(event)
    assert event.isAccepted()
    assert called == [{'files': [str(source)]}]
    terminal.stop()
    assert not os.path.exists(terminal.control_path)


def test_cancelled_download_preserves_existing_file(terminal, tmp_path):
    source = tmp_path / 'remote.bin'
    source.write_bytes(b'a' * 100000)
    destination = tmp_path / 'existing.bin'
    destination.write_bytes(b'original')
    cancelled = threading.Event()
    client = SFTPClient(terminal.control_path, terminal.sftp_host, cancelled)
    try:
        with pytest.raises(InterruptedError):
            client.download(str(source), str(destination), lambda *args: cancelled.set(), overwrite=True)
        assert destination.read_bytes() == b'original'
        assert not list(tmp_path.glob('.unircm-*'))
    finally:
        client.close()


def test_file_manager_edits_remote_directory(qtbot, terminal, tmp_path, monkeypatch):
    terminal.sftp_directory = str(tmp_path)
    source = tmp_path / 'original.txt'
    source.write_text('original')
    existing = tmp_path / 'existing.txt'
    existing.write_text('keep')
    dialog = FileTransferDialog(terminal)
    terminal.transfer_dialogs.append(dialog)
    dialog.show()

    def wait_for_job():
        qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)

    def select(name):
        item, = dialog.tree.findItems(name, Qt.MatchFlag.MatchExactly)
        assert not item.icon(0).isNull()
        dialog.tree.setCurrentItem(item)

    names = iter(('remote folder', existing.name, 'renamed.txt'))
    monkeypatch.setattr(dialog, 'ask_name', lambda *args: next(names))
    wait_for_job()
    dialog.new_folder_action.trigger()
    wait_for_job()
    folder = tmp_path / 'remote folder'
    assert folder.is_dir()

    select(source.name)
    dialog.rename_action.trigger()
    wait_for_job()
    assert source.read_text() == 'original'
    assert existing.read_text() == 'keep'
    dialog.rename_action.trigger()
    wait_for_job()
    renamed = tmp_path / 'renamed.txt'
    assert not source.exists()
    assert renamed.read_text() == 'original'

    select(renamed.name)
    monkeypatch.setattr(dialog, 'confirm', lambda text: False)
    dialog.delete_action.trigger()
    assert renamed.exists()
    monkeypatch.setattr(dialog, 'confirm', lambda text: True)
    dialog.delete_action.trigger()
    wait_for_job()
    assert not renamed.exists()

    child = folder / 'child'
    child.touch()
    select(folder.name)
    dialog.delete_action.trigger()
    wait_for_job()
    assert child.exists()
    child.unlink()
    dialog.delete_action.trigger()
    wait_for_job()
    assert not folder.exists()


def test_missing_control_socket_cannot_reauthenticate(tmp_path):
    with pytest.raises(OSError, match='SFTP channel closed'):
        SFTPClient(str(tmp_path / 'absent'), '127.0.0.1')


def test_terminal_context_menu_offers_file_manager_and_upload(qtbot, terminal, monkeypatch):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    called = []
    monkeypatch.setattr(terminal, 'open_file_transfer', lambda upload=False: called.append(upload))
    def inspect_menu(menu, position):
        actions = {action.text(): action for action in menu.actions()}
        assert 'Download file' not in actions
        for name in ('Upload file', 'File manager'):
            assert actions[name].isEnabled()
            assert not actions[name].icon().isNull()
            actions[name].trigger()
    monkeypatch.setattr(QMenu, 'exec', inspect_menu)
    terminal.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1)))
    assert called == [True, False]


@pytest.mark.parametrize('stage', ['before_data', 'after_data', 'open_response', 'write_response'])
def test_cancelled_upload_removes_own_part(terminal, tmp_path, monkeypatch, stage):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'x' * 100000)
    remote = tmp_path / 'existing.bin'
    remote.write_bytes(b'original')
    unrelated = tmp_path / 'another-upload.part'
    unrelated.write_bytes(b'leave alone')
    cancelled = threading.Event()
    client = SFTPClient(terminal.control_path, terminal.sftp_host, cancelled)
    receive = client.receive
    def interrupt_response():
        if (stage == 'open_response' and client.sequence == 1 or
                stage == 'write_response' and client.sequence == 2):
            cancelled.set()
        return receive()
    monkeypatch.setattr(client, 'receive', interrupt_response)
    def progress(done, total):
        if stage == 'before_data' or stage == 'after_data' and done > 0:
            cancelled.set()
    try:
        with pytest.raises(InterruptedError, match='Transfer cancelled'):
            client.upload(str(source), str(remote), progress, overwrite=True)
        assert remote.read_bytes() == b'original'
        assert not list(tmp_path.glob('*.unircm-*.part'))
        assert unrelated.read_bytes() == b'leave alone'
        assert terminal.is_running()
    finally:
        client.close()


def test_failed_upload_cleanup_reports_exact_path(terminal, tmp_path, monkeypatch):
    from remote_manager.terminal.sftp import UploadCleanupError
    source = tmp_path / 'source.bin'
    source.write_bytes(b'x' * 100000)
    remote = tmp_path / 'existing.bin'
    remote.write_bytes(b'original')
    cancelled = threading.Event()
    client = SFTPClient(terminal.control_path, terminal.sftp_host, cancelled)
    remove = client.remove_temporary_upload
    def refuse(path):
        raise PermissionError('cleanup denied')
    monkeypatch.setattr(client, 'remove_temporary_upload', refuse)
    try:
        with pytest.raises(UploadCleanupError) as raised:
            client.upload(str(source), str(remote), lambda *args: cancelled.set(), overwrite=True)
        path = raised.value.path
        assert str(remote) + '.unircm-' in path
        assert os.path.isfile(path)
        assert path in str(raised.value)
        assert remote.read_bytes() == b'original'
        remove(path)
        assert not os.path.exists(path)
    finally:
        client.close()
