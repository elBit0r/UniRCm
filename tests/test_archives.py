import json
import signal
import subprocess
import sys
import zipfile
import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from remote_manager.storage.archive import ArchiveInUse, ArchiveVault, RecoveryConflict, metadata, restore_backup
from remote_manager.storage.kdf import KeyFileError, generate_key_file
from remote_manager.storage.vault import BackupError, Vault


def test_archive_encryption_isolation_and_lock(tmp_path):
    first = tmp_path / 'work.uni'
    second = tmp_path / 'home.uni'
    vault = ArchiveVault(first, 'test-master', 'Work')
    assert metadata(first)['format_version'] == 3
    assert not list(tmp_path.glob('*.backup-*'))
    with pytest.raises(sqlcipher.DatabaseError):
        Vault.verify_key(vault.path, 'test-master', kdf_iterations=512_000)
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
    assert metadata(second)['argon2_salt'] != metadata(first)['argon2_salt']
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


@pytest.mark.parametrize('published', [False, True])
@pytest.mark.parametrize('add_key_file', [False, True])
def test_rekey_recovers_using_the_password_for_the_published_archive(tmp_path, published, add_key_file):
    path = tmp_path / 'work.uni'
    vault = ArchiveVault(path, 'old password', 'Work')
    vault.set_inactivity_minutes(11)
    vault.close()
    key_file = tmp_path / 'vault.key'
    if add_key_file:
        generate_key_file(key_file)

    result = subprocess.run([sys.executable, '-', str(path), str(published)], input="""
import os
import signal
import sys
from pathlib import Path
from remote_manager.storage.archive import ArchiveVault

path = Path(sys.argv[1])
vault = ArchiveVault(path, 'old password')
replace = os.replace

def interrupt_publication(source, destination):
    if destination == path:
        if sys.argv[2] == 'True':
            replace(source, destination)
        os.kill(os.getpid(), signal.SIGKILL)
    return replace(source, destination)

os.replace = interrupt_publication
key_file = path.with_name('vault.key')
options = {'new_key_file': key_file} if key_file.exists() else {}
vault.change_password('old password', 'new password', **options)
""", text=True, capture_output=True, timeout=30)
    assert result.returncode == -signal.SIGKILL, result.stderr

    current, wrong = ('new password', 'old password') if published else ('old password', 'new password')
    original = path.read_bytes()
    assert bool(metadata(path).get('key_file_required')) == (published and add_key_file)
    if published and add_key_file:
        with pytest.raises(KeyFileError):
            ArchiveVault(path, current)
    with pytest.raises(sqlcipher.DatabaseError):
        ArchiveVault(path, wrong, key_file=key_file if add_key_file else None)
    assert path.read_bytes() == original
    recovered = ArchiveVault(path, current, key_file=key_file if published and add_key_file else None)
    assert recovered.inactivity_minutes() == 11
    recovered.close()


@pytest.mark.parametrize('iterations', [None, 512_000])
def test_key_file_creation_and_unlock(tmp_path, iterations):
    import hashlib

    key_file = tmp_path / 'vault.key'
    generate_key_file(key_file)
    key_data = key_file.read_bytes()
    assert len(key_data) == 32
    assert key_file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        generate_key_file(key_file)
    assert key_file.read_bytes() == key_data

    path = tmp_path / 'work.uni'
    vault = ArchiveVault(path, 'master', 'Work', kdf_iterations=iterations, key_file=key_file)
    vault.set_inactivity_minutes(12)
    vault.close()
    public = metadata(path)
    assert public['key_file_required'] is True
    assert set(public) == {'description', 'format_version', 'key_file_required', 'password_salt'} | (
        {'kdf_iterations'} if iterations is not None else set())
    archive_bytes = path.read_bytes()
    digest = hashlib.sha256(key_data)
    assert all(secret not in archive_bytes for secret in (key_data, digest.digest(), digest.hexdigest().encode()))
    with pytest.raises(KeyFileError):
        ArchiveVault(path, 'master')
    wrong_file = tmp_path / 'wrong.key'
    generate_key_file(wrong_file)
    with pytest.raises(sqlcipher.DatabaseError):
        ArchiveVault(path, 'master', key_file=wrong_file)
    with pytest.raises(sqlcipher.DatabaseError):
        ArchiveVault(path, 'wrong password', key_file=key_file)
    assert path.read_bytes() == archive_bytes
    renamed = key_file.rename(tmp_path / 'renamed.key')
    vault = ArchiveVault(path, 'master', key_file=renamed)
    assert vault.inactivity_minutes() == 12
    vault.close()


def test_rekey_add_replace_remove_and_restore_key_file(tmp_path):
    first, second = (tmp_path / name for name in ('first.key', 'second.key'))
    generate_key_file(first)
    generate_key_file(second)
    path = tmp_path / 'work.uni'
    vault = ArchiveVault(path, 'master', 'Work')
    vault.set_inactivity_minutes(10)
    vault.change_password('master', 'master', new_key_file=first)
    assert vault.key_file_required
    with pytest.raises(ValueError):
        vault.change_password('master', 'master', key_file=first, new_key_file=first)
    vault.change_password('master', 'master', key_file=first, new_key_file=second)
    vault.change_password('master', 'master', key_file=second, new_key_file=None)
    assert not vault.key_file_required
    vault.close()

    password_only = ArchiveVault(path, 'master')
    assert password_only.inactivity_minutes() == 10
    password_only.close()
    added, replaced, removed = sorted(tmp_path.glob('*.backup-*-key-file.uni'))
    assert not metadata(added).get('key_file_required')
    for backup, key in [(replaced, first), (removed, second)]:
        restored_path = tmp_path / f'{key.stem}-restored.uni'
        with pytest.raises(KeyFileError):
            restore_backup(backup, restored_path, 'master', is_archive=True)
        assert not restored_path.exists()
        restore_backup(backup, restored_path, 'master', is_archive=True, key_file=key)
        restored = ArchiveVault(restored_path, 'master', key_file=key)
        assert restored.inactivity_minutes() == 10
        restored.close()


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


def test_legacy_archive_upgrades_to_512000_after_backup(tmp_path):
    path = tmp_path / 'legacy.uni'
    database = tmp_path / 'legacy.db'
    legacy = Vault(database, 'master')
    legacy.save(dict(name='Legacy secret', host='localhost', port=22, username='user',
                     password='remote-secret', identity_file=''))
    legacy.close()
    with zipfile.ZipFile(path, 'w') as archive:
        archive.write(database, 'database.db')
        archive.writestr('metadata.json', json.dumps(dict(format_version=1, description='Legacy')))

    original = path.read_bytes()
    with pytest.raises(sqlcipher.DatabaseError):
        ArchiveVault(path, 'wrong')
    assert not list(tmp_path.glob('*.backup-*'))
    assert path.read_bytes() == original

    vault = ArchiveVault(path, 'master')
    assert int(vault.connection.execute('PRAGMA kdf_iter').fetchone()[0]) == 512_000
    assert vault.profiles()[0]['password'] == 'remote-secret'
    vault.close()
    assert metadata(path)['format_version'] == 2
    backup, = tmp_path.glob('*.backup-*-kdf.uni')
    assert metadata(backup)['format_version'] == 1
    restored = tmp_path / 'legacy-copy.uni'
    restore_backup(backup, restored, 'master', is_archive=True)
    with zipfile.ZipFile(restored) as archive:
        assert archive.read('database.db') == database.read_bytes()
    ArchiveVault(path, 'master').close()
    assert list(tmp_path.glob('*.backup-*-kdf.uni')) == [backup]


def test_schema_backup_happens_before_migration(tmp_path, monkeypatch):
    import remote_manager.storage.archive as storage

    path = tmp_path / 'schema.uni'
    vault = ArchiveVault(path, 'master', 'Schema', kdf_iterations=512_000)
    vault.set_inactivity_minutes(7)
    with vault.connection as connection:
        connection.execute('ALTER TABLE profiles DROP COLUMN ssh_reconnect_delay')
        connection.execute('ALTER TABLE profiles DROP COLUMN authentication')
        connection.execute('ALTER TABLE profiles DROP COLUMN before_connect_command')
        connection.execute('ALTER TABLE profiles DROP COLUMN after_disconnect_command')
        connection.execute('PRAGMA user_version = 17')
    vault.close()
    before = path.read_bytes()

    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError('Disk full')
        patch.setattr(storage, 'publish_copy', fail)
        with pytest.raises(BackupError):
            ArchiveVault(path, 'master')
    assert path.read_bytes() == before

    vault = ArchiveVault(path, 'master')
    assert vault.connection.execute('PRAGMA user_version').fetchone()[0] == 22
    assert vault.inactivity_minutes() == 7
    vault.close()
    backup, = tmp_path.glob('*.backup-*-schema-17-schema.uni')
    with zipfile.ZipFile(backup) as saved, zipfile.ZipFile(path) as current:
        assert saved.read('database.db') != current.read('database.db')
    restored = tmp_path / 'restored.uni'
    restore_backup(backup, restored, 'master', is_archive=True)
    assert restored.read_bytes() == backup.read_bytes()
    database = tmp_path / 'verify.db'
    with zipfile.ZipFile(restored) as archive:
        database.write_bytes(archive.read('database.db'))
    assert Vault.verify_key(database, 'master', kdf_iterations=512_000) == 17


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


def test_chooser_reports_incompatible_schema_and_restores_backup(qtbot, tmp_path, monkeypatch):
    from remote_manager.ui.databases import DatabaseChooser

    path = tmp_path / 'newer.uni'
    restored = tmp_path / 'restored.uni'
    vault = ArchiveVault(path, 'old password', 'Newer test')
    vault.change_password('old password', 'correct password')
    backup, = tmp_path.glob('*.backup-*-password.uni')
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

    from remote_manager.ui.dialogs import QFileDialog
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args, **kw: (str(backup), ''))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kw: (str(restored), ''))
    panel.password.setText('old password')
    panel.restore_button.click()
    assert not panel.password.text()
    assert restored.read_bytes() == backup.read_bytes()
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
    assert panel.kdf.currentData() == 'argon2id'
    assert not panel.kdf_iterations.isEnabled()
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
    panel.kdf.setCurrentIndex(panel.kdf.findData('pbkdf2'))
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
