import json
import signal
import subprocess
import sys
import zipfile
import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from remote_manager.storage.archive import ArchiveInUse, ArchiveVault, RecoveryConflict, metadata
from remote_manager.storage.vault import Vault


def test_archive_encryption_isolation_and_lock(tmp_path):
    first = tmp_path / 'work.uni'
    second = tmp_path / 'home.uni'
    vault = ArchiveVault(first, 'test-master', 'Work')
    assert metadata(first)['kdf_iterations'] == 512_000
    assert int(vault.connection.execute('PRAGMA kdf_iter').fetchone()[0]) == 512_000
    vault.save(dict(name='Private server', host='private.example', port=22,
                    username='admin', identity_file=''))
    before = first.read_bytes()
    with pytest.raises(ArchiveInUse):
        ArchiveVault(first, 'test-master')
    assert first.read_bytes() == before
    with zipfile.ZipFile(first) as archive:
        encrypted = archive.read('database.db')
        assert not encrypted.startswith(b'SQLite format 3')
        assert b'private.example' not in encrypted
        assert b'test-master' not in first.read_bytes()
    vault.close()
    with pytest.raises(Exception):
        ArchiveVault(first, 'wrong')
    vault = ArchiveVault(first, 'test-master')
    assert vault.profiles()[0]['host'] == 'private.example'
    assert metadata(first)['description'] == 'Work'
    other = ArchiveVault(second, 'other-master', 'Home')
    assert other.profiles() == []
    other.close()
    vault.close()


@pytest.mark.parametrize('published', [False, True])
def test_archive_recovers_after_process_is_killed(tmp_path, published):
    path = tmp_path / 'work.uni'
    original = ArchiveVault(path, 'test-master', 'Work')
    original.close()
    with zipfile.ZipFile(path) as archive:
        before = archive.read('database.db')

    result = subprocess.run([sys.executable, '-', str(path), str(published)], input="""
import os
import signal
import sys
from pathlib import Path
from remote_manager.storage.archive import ArchiveVault

path = Path(sys.argv[1])
vault = ArchiveVault(path, 'test-master')
replace = os.replace

def interrupt_publication(source, destination):
    if destination == path:
        if sys.argv[2] == 'True':
            replace(source, destination)
        os.kill(os.getpid(), signal.SIGKILL)
    return replace(source, destination)

os.replace = interrupt_publication
vault.save(dict(name='Recovered SSH', host='recovered.example', port=22,
                username='admin', identity_file=''))
""", text=True, capture_output=True, timeout=30)
    assert result.returncode == -signal.SIGKILL, result.stderr
    after_crash = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        assert (archive.read('database.db') != before) == published
    working = tmp_path / '.work.uni.working'
    database = working / 'database.db'
    assert working.stat().st_mode & 0o777 == 0o700
    assert database.stat().st_mode & 0o777 == 0o600
    encrypted = database.read_bytes()
    assert not encrypted.startswith(b'SQLite format 3')
    assert b'recovered.example' not in encrypted

    with pytest.raises(sqlcipher.DatabaseError):
        ArchiveVault(path, 'wrong password')
    assert database.read_bytes() == encrypted
    assert path.read_bytes() == after_crash

    other_path = tmp_path / 'other.uni'
    other = ArchiveVault(other_path, 'test-master', 'Other')
    other.close()
    other_path.replace(path)
    replacement = path.read_bytes()
    with pytest.raises(RecoveryConflict):
        ArchiveVault(path, 'test-master')
    assert path.read_bytes() == replacement
    assert database.read_bytes() == encrypted
    path.write_bytes(after_crash)

    recovered = ArchiveVault(path, 'test-master')
    assert recovered.profiles()[0]['host'] == 'recovered.example'
    with zipfile.ZipFile(path) as archive:
        assert archive.read('database.db') == database.read_bytes()
    recovered.close()
    assert not working.exists()


def test_invalid_archive_and_no_overwrite(tmp_path):
    path = tmp_path / 'bad.uni'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('../database.db', b'invalid')
        archive.writestr('metadata.json', '{}')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ArchiveVault(path, 'password')
    with pytest.raises(FileExistsError):
        ArchiveVault(path, 'password', 'replacement')
    assert path.read_bytes() == before


def test_legacy_archive_preserves_original_key_derivation(tmp_path):
    path = tmp_path / 'legacy.uni'
    database = tmp_path / 'legacy.db'
    Vault(database, 'master').close()
    with zipfile.ZipFile(path, 'w') as archive:
        archive.write(database, 'database.db')
        archive.writestr('metadata.json', json.dumps(dict(format_version=1, description='Legacy')))

    vault = ArchiveVault(path, 'master')
    assert int(vault.connection.execute('PRAGMA kdf_iter').fetchone()[0]) == 256_000
    vault.close()
    assert metadata(path)['format_version'] == 1


def test_archive_rejects_excessive_key_derivation_cost(tmp_path):
    path = tmp_path / 'invalid.uni'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('database.db', b'')
        archive.writestr('metadata.json', json.dumps(
            dict(format_version=2, description='Invalid', kdf_iterations=10**9)))
    with pytest.raises(ValueError, match='iteration count'):
        ArchiveVault(path, 'master')


def test_chooser_lists_locations_and_forgets_without_deleting(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings
    from remote_manager.ui import databases
    settings = QSettings(str(tmp_path / 'recent.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr(databases, 'QSettings', lambda: settings)
    path = tmp_path / 'work.uni'
    vault = ArchiveVault(path, 'password', 'Work')
    vault.close()
    settings.setValue('databases/recent', [str(path)])
    chooser = databases.DatabaseChooser(tmp_path / 'missing.db')
    qtbot.addWidget(chooser)
    assert chooser.tree.topLevelItem(0).text(0) == 'Work'
    assert chooser.tree.topLevelItem(0).text(1) == str(path)
    chooser.forget()
    assert chooser.tree.topLevelItemCount() == 0
    assert path.exists()


def test_chooser_inline_unlock_and_back(qtbot, tmp_path):
    from PyQt6.QtWidgets import QDialog
    from remote_manager.ui.databases import DatabaseChooser
    path = tmp_path / 'inline.uni'
    vault = ArchiveVault(path, 'correct password', 'Inline test')
    chooser = DatabaseChooser(tmp_path / 'missing.db')
    qtbot.addWidget(chooser)
    chooser.show()
    chooser.open_path(path)
    panel = chooser.unlock_panel
    assert chooser.pages.currentWidget() is panel
    assert not hasattr(panel, 'password_strength')
    assert not hasattr(panel, 'kdf_iterations')
    assert not panel.isWindow()
    assert not chooser.findChildren(QDialog)
    panel.password.setText('correct password')
    panel.submit()
    assert panel.error.text() == panel.tr('This database is already open. Close it before trying again.')
    assert chooser.vault is None
    vault.close()
    panel.password.setText('wrong password')
    panel.submit()
    assert panel.error.text()
    assert chooser.vault is None
    chooser.reject()  # Escape returns to the list without retaining secrets.
    assert not panel.password.text()
    assert chooser.pages.currentWidget() is chooser.list_page
    chooser.open_path(path)
    panel = chooser.unlock_panel
    panel.password.setText('correct password')
    panel.submit()
    assert chooser.result() == QDialog.DialogCode.Accepted
    assert chooser.path == path
    assert not panel.password.text()
    chooser.vault.close()


def test_chooser_reports_incompatible_schema(qtbot, tmp_path):
    from remote_manager.ui.databases import DatabaseChooser

    path = tmp_path / 'newer.uni'
    vault = ArchiveVault(path, 'correct password', 'Newer test')
    with vault.connection as connection:
        connection.execute('PRAGMA user_version = 999')
    vault.close()
    before = path.read_bytes()

    chooser = DatabaseChooser(tmp_path / 'missing.db')
    qtbot.addWidget(chooser)
    chooser.open_path(path)
    panel = chooser.unlock_panel
    panel.password.setText('correct password')
    panel.submit()
    assert panel.error.text() == panel.tr(
        'This database requires a compatible version of UniRCm. '
        'Open it with the version that last saved it or a newer version.'
    )
    assert chooser.vault is None
    assert path.read_bytes() == before


def test_chooser_inline_setup_and_close(qtbot, tmp_path):
    from remote_manager.ui.databases import DatabaseChooser
    path = tmp_path / 'new.uni'
    chooser = DatabaseChooser(tmp_path / 'missing.db')
    qtbot.addWidget(chooser)
    chooser.show()
    chooser.open_path(path, 'New test')
    panel = chooser.unlock_panel
    assert panel.password_strength.value() == 0
    assert panel.kdf_iterations.value() == 512_000
    for password, level, label in (
        ('abc', 1, 'Weak'),
        ('orbit maple', 2, 'Medium'),
        ('tide-Mosaic7#glass', 3, 'Strong'),
    ):
        panel.password.setText(password)
        assert panel.password_strength.value() == level
        assert panel.strength_label.text() == panel.tr(label)
    panel.password.setText('new password')
    panel.confirmation.setText('different password')
    panel.submit()
    assert not path.exists()
    assert panel.error.text()
    chooser.close()
    assert not panel.password.text()
    assert panel.password_strength.value() == 0
    assert not panel.confirmation.text()
    assert not chooser.isVisible()
    chooser.open_path(path, 'New test')
    panel = chooser.unlock_panel
    panel.kdf_iterations.setValue(1_024_000)
    panel.password.setText('new password')
    panel.confirmation.setText('new password')
    panel.submit()
    assert path.exists()
    assert metadata(path)['kdf_iterations'] == 1_024_000
    chooser.vault.close()
    vault = ArchiveVault(path, 'new password')
    assert int(vault.connection.execute('PRAGMA kdf_iter').fetchone()[0]) == 1_024_000
    with pytest.raises(sqlcipher.DatabaseError):
        Vault.verify_key(vault.path, 'new password', kdf_iterations=512_000)
    vault.close()
