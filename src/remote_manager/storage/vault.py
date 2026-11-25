"""SQLCipher-only profile persistence. Passwords are never persisted separately."""
from remote_manager.ssh_options import validate_advanced
from remote_manager.rdp_options import validate_options as validate_rdp_options

from datetime import datetime, timezone
import json
import os
import stat
import uuid
import shutil
import tempfile
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlcipher
from remote_manager.icon_catalog import CONNECTION_ICONS


LEGACY_KDF_ITERATIONS = 256_000
DEFAULT_KDF_ITERATIONS = 512_000
MAX_KDF_ITERATIONS = 4_096_000


def validate_kdf_iterations(iterations, *, minimum=LEGACY_KDF_ITERATIONS):
    if type(iterations) is not int or not minimum <= iterations <= MAX_KDF_ITERATIONS:
        raise ValueError('Invalid key derivation iteration count.')


SCHEMA_VERSION = 22
MAX_SSH_RECONNECT_DELAY = 600


class UnsupportedSchemaVersion(RuntimeError):
    """The vault schema is incompatible with this version of UniRCm."""


class BackupError(RuntimeError):
    """An encrypted backup could not be created or verified."""


def check_encrypted_header(source):
    header = source.read(16)
    if len(header) != 16 or header == b'SQLite format 3\x00':
        raise ValueError('Expected an encrypted SQLCipher database.')
    source.seek(0)


def publish_copy(source, destination, verify, *, raw_database=False):
    """Publish a private, complete copy without replacing an existing file."""
    destination = Path(destination)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        staging = Path(output.name)
        try:
            with Path(source).open('rb') as original:
                if raw_database:
                    check_encrypted_header(original)
                shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
            verify(staging)
            os.link(staging, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            staging.unlink(missing_ok=True)


def backup_path(source, reason, schema):
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    return source.with_name(f'{source.name}.backup-{timestamp}-schema-{schema}-{reason}{source.suffix}')


def _configure_encryption(connection, password, iterations):
    validate_kdf_iterations(iterations)
    if not password or '\x00' in password:
        raise ValueError('Enter nonempty master passwords without NUL characters.')
    version = connection.execute('PRAGMA cipher_version').fetchone()
    if not version or not version[0].startswith('4.'):
        raise RuntimeError('SQLCipher 4 is required.')
    connection.set_key(password)
    connection.execute('PRAGMA cipher_compatibility = 4')
    connection.execute(f'PRAGMA kdf_iter = {iterations}')
    connection.execute('PRAGMA cipher_memory_security = ON')
    connection.execute('PRAGMA temp_store = MEMORY')


class Vault:
    def __init__(self, path: Path, password: str, *, kdf_iterations=LEGACY_KDF_ITERATIONS,
                 create=None):
        if not password or '\x00' in password:
            raise ValueError('Enter nonempty master passwords without NUL characters.')
        validate_kdf_iterations(kdf_iterations)
        self.kdf_iterations = kdf_iterations
        path = Path(path)
        self.path = path
        if create is not True:
            try:
                original = path.lstat()
            except FileNotFoundError:
                if create is False:
                    raise
                create = True
            else:
                if not stat.S_ISREG(original.st_mode) or original.st_uid != os.geteuid():
                    raise PermissionError('Expected a regular database file owned by the current user.')
                if original.st_size == 0:
                    raise ValueError('Expected an encrypted SQLCipher database.')
        if create:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                original = os.fstat(fd)
                if stat.S_IMODE(original.st_mode) != 0o600:
                    os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        if not os.path.samestat(original, path.lstat()):
            raise PermissionError('Database file changed while opening.')
        uri = path.absolute().as_uri() + '?mode=rw'
        connection = sqlcipher.connect(uri, uri=True)
        try:
            _configure_encryption(connection, password, self.kdf_iterations)
            connection.execute('SELECT count(*) FROM sqlite_master').fetchone()
            if connection.execute('PRAGMA user_version').fetchone()[0] not in range(SCHEMA_VERSION + 1):
                raise UnsupportedSchemaVersion('Unsupported database schema version.')
            if not os.path.samestat(original, path.lstat()):
                raise PermissionError('Database file changed while opening.')
            if not create and stat.S_IMODE(original.st_mode) != 0o600:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not os.path.samestat(original, os.fstat(fd)):
                        raise PermissionError('Database file changed while opening.')
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)
            if not create and not original.st_mode & stat.S_IWUSR:
                # SQLCipher may have opened the file read-only before fchmod.
                connection.close()
                connection = sqlcipher.connect(uri, uri=True)
                _configure_encryption(connection, password, self.kdf_iterations)
                connection.execute('SELECT count(*) FROM sqlite_master').fetchone()
                if not os.path.samestat(original, path.lstat()):
                    raise PermissionError('Database file changed while opening.')
            self.connection = connection
            self.connection.execute('PRAGMA journal_mode = DELETE')
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.connection.execute('PRAGMA secure_delete = ON')
            with self.connection:
                self.connection.execute('BEGIN IMMEDIATE')
                schema = self.connection.execute('PRAGMA user_version').fetchone()[0]
                if schema < SCHEMA_VERSION and path.stat().st_size:
                    self._backup(password, 'schema', schema)
                self.connection.execute('''CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL,
                    port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
                    username TEXT NOT NULL, identity_file TEXT NOT NULL DEFAULT '')''')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 2:
                    self.connection.execute('''CREATE TABLE folders (
                        id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                        parent_id INTEGER REFERENCES folders(id) ON DELETE RESTRICT)''')
                    self.connection.execute('ALTER TABLE profiles ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE RESTRICT')
                    self.connection.execute('CREATE INDEX profiles_folder ON profiles(folder_id)')
                    self.connection.execute('CREATE INDEX folders_parent ON folders(parent_id)')
                    self.connection.execute('PRAGMA user_version = 2')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 3:
                    for column, default in (('protocol', 'ssh'), ('icon', 'terminal'), ('tab_color', '')):
                        self.connection.execute(f"ALTER TABLE profiles ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
                    self.connection.execute('PRAGMA user_version = 3')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 4:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN terminal_options TEXT NOT NULL DEFAULT '{}'")
                    self.connection.execute('PRAGMA user_version = 4')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 5:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN ssh_modes TEXT NOT NULL DEFAULT '{}'")
                    self.connection.execute("ALTER TABLE folders ADD COLUMN ssh_defaults TEXT NOT NULL DEFAULT '{}'")
                    self.connection.execute('PRAGMA user_version = 5')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 6:
                    self.connection.execute('ALTER TABLE profiles ADD COLUMN connect_timeout INTEGER NOT NULL DEFAULT 15 CHECK(connect_timeout BETWEEN 1 AND 600)')
                    self.connection.execute('PRAGMA user_version = 6')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 7:
                    self.connection.execute('CREATE TABLE credentials (id TEXT PRIMARY KEY, username TEXT NOT NULL, password TEXT NOT NULL)')
                    self.connection.execute('ALTER TABLE profiles ADD COLUMN credential_id TEXT REFERENCES credentials(id)')
                    self.connection.execute('PRAGMA user_version = 7')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 8:
                    self.connection.execute("ALTER TABLE credentials ADD COLUMN name TEXT NOT NULL DEFAULT ''")
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN credential_source TEXT NOT NULL DEFAULT 'local'")
                    self.connection.execute('PRAGMA user_version = 8')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 9:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN telnet_options TEXT NOT NULL DEFAULT '{}'")
                    self.connection.execute('PRAGMA user_version = 9')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 10:
                    self.connection.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                    self.connection.execute('PRAGMA user_version = 10')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 11:
                    self.connection.execute("ALTER TABLE credentials ADD COLUMN key_passphrase TEXT NOT NULL DEFAULT ''")
                    self.connection.execute('PRAGMA user_version = 11')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 12:
                    self.connection.execute("CREATE TABLE IF NOT EXISTS tree_order (kind TEXT NOT NULL CHECK(kind IN ('folder','profile')), item_id INTEGER NOT NULL, position INTEGER NOT NULL, PRIMARY KEY(kind,item_id))")
                    self.connection.execute("CREATE TABLE IF NOT EXISTS folder_appearance (folder_id INTEGER PRIMARY KEY REFERENCES folders(id) ON DELETE CASCADE, value TEXT NOT NULL)")
                    self.connection.execute('PRAGMA user_version = 12')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 13:
                    self.connection.execute('ALTER TABLE profiles ADD COLUMN connect_at_startup INTEGER NOT NULL DEFAULT 0 CHECK(connect_at_startup IN (0,1))')
                    self.connection.execute('PRAGMA user_version = 13')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 14:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN ssh_advanced TEXT NOT NULL DEFAULT '{}'")
                    self.connection.execute('PRAGMA user_version = 14')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 15:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN rdp_domain TEXT NOT NULL DEFAULT ''")
                    self.connection.execute('PRAGMA user_version = 15')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 16:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN rdp_options TEXT NOT NULL DEFAULT '{}'")
                    self.connection.execute('PRAGMA user_version = 16')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 17:
                    self.connection.execute('''CREATE TABLE ssh_private_keys (
                        profile_id INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
                        name TEXT NOT NULL, key_data BLOB NOT NULL)''')
                    self.connection.execute('PRAGMA user_version = 17')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 18:
                    self.connection.execute(
                        'ALTER TABLE profiles ADD COLUMN ssh_reconnect_delay INTEGER NOT NULL DEFAULT 0 '
                        f'CHECK(ssh_reconnect_delay BETWEEN 0 AND {MAX_SSH_RECONNECT_DELAY})'
                    )
                    self.connection.execute('PRAGMA user_version = 18')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 19:
                    self.connection.execute('ALTER TABLE profiles ADD COLUMN authentication TEXT')
                    self.connection.execute('PRAGMA user_version = 19')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 20:
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN before_connect_command TEXT NOT NULL DEFAULT ''")
                    self.connection.execute("ALTER TABLE profiles ADD COLUMN after_connect_command TEXT NOT NULL DEFAULT ''")
                    self.connection.execute('PRAGMA user_version = 20')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 21:
                    self.connection.execute("ALTER TABLE profiles RENAME COLUMN after_connect_command TO after_disconnect_command")
                    self.connection.execute('PRAGMA user_version = 21')
                if self.connection.execute('PRAGMA user_version').fetchone()[0] < 22:
                    columns = {row[1] for row in self.connection.execute('PRAGMA table_info(profiles)')}
                    if 'ssh_startup_commands' not in columns:
                        self.connection.execute("ALTER TABLE profiles ADD COLUMN ssh_startup_commands TEXT NOT NULL DEFAULT ''")
                    self.connection.execute('PRAGMA user_version = 22')
        except Exception:
            connection.close()
            raise

    def local_terminal_profiles(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='local_terminal_profiles'").fetchone()
        return json.loads(row[0]) if row else []

    def save_local_terminal_profile(self, name, directory, commands, profile_id=None):
        name, directory = name.strip(), directory.strip()
        if not name or any(char in name + directory for char in '\r\n\x00') or '\x00' in commands:
            raise ValueError('Enter a profile name and valid directory and commands.')
        with self.connection:
            profiles = self.local_terminal_profiles()
            if any(p['id'] != profile_id and p['name'].casefold() == name.casefold() for p in profiles):
                raise ValueError('A local terminal profile already uses this name.')
            profile = dict(id=profile_id or uuid.uuid4().hex, name=name, directory=directory, commands=commands)
            self._write_local_terminal_profiles([p for p in profiles if p['id'] != profile_id] + [profile])
        return profile['id']

    def delete_local_terminal_profile(self, profile_id):
        with self.connection:
            self._write_local_terminal_profiles([p for p in self.local_terminal_profiles() if p['id'] != profile_id])

    def _write_local_terminal_profiles(self, profiles):
        self.connection.execute(
            "INSERT INTO settings(key,value) VALUES('local_terminal_profiles',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(profiles),))

    def terminal_profiles(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='terminal_profiles'").fetchone()
        if row:
            return json.loads(row[0])
        from remote_manager.terminal.profiles import default_profiles
        profiles = default_profiles()
        self.save_terminal_profiles(profiles)
        return profiles

    def save_terminal_profiles(self, profiles):
        ids, names = set(), set()
        for profile in profiles:
            if not profile['name'].strip() or profile['name'].casefold() in names or profile['id'] in ids:
                raise ValueError('Terminal profile names must be unique and nonempty.')
            ids.add(profile['id'])
            names.add(profile['name'].casefold())
            validate_terminal_options(profile['options'])
            if 'profile_id' in profile['options']:
                raise ValueError('Nested terminal profiles are not supported.')
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('terminal_profiles',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(profiles),))

    def replace_terminal_profile(self, old, replacement):
        profiles = self.terminal_profiles()
        if old == replacement or replacement not in {p['id'] for p in profiles}:
            raise ValueError('Choose a replacement terminal profile.')
        def replace(value):
            if isinstance(value, dict):
                return {k: replacement if k == 'profile_id' and v == old else replace(v) for k, v in value.items()}
            return value
        with self.connection:
            for table, column in (('profiles', 'terminal_options'), ('folders', 'ssh_defaults')):
                for row in self.connection.execute(f'SELECT id,{column} FROM {table}').fetchall():
                    value = json.loads(row[1])
                    updated = replace(value)
                    if updated != value:
                        self.connection.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (json.dumps(updated), row[0]))
            self.connection.execute("UPDATE settings SET value=? WHERE key='terminal_profiles'", (json.dumps([p for p in profiles if p['id'] != old]),))

    def expand_terminal_options(self, options):
        reference = options.get('profile_id')
        if reference:
            for profile in self.terminal_profiles():
                if profile['id'] == reference:
                    return dict(profile['options'])
            raise ValueError('Terminal profile no longer exists.')
        return options

    def tree_positions(self):
        return {(row[0], row[1]): row[2] for row in self.connection.execute('SELECT kind,item_id,position FROM tree_order')}

    def tree_children(self, parent_id):
        self.connection.row_factory = sqlcipher.Row
        children = [dict(row) for row in self.connection.execute(
            "SELECT items.*,o.position AS order_position FROM (SELECT 'folder' AS kind,id,name FROM folders WHERE parent_id IS ? "
            "UNION ALL SELECT 'profile',id,name FROM profiles WHERE folder_id IS ?) items "
            "LEFT JOIN tree_order o ON o.kind=items.kind AND o.item_id=items.id",
            (parent_id, parent_id))]
        children.sort(key=lambda row: (row['order_position'] is None, row['order_position'] or 0,
                                      row['kind'], row['name'].casefold(), row['id']))
        for row in children:
            row.pop('order_position')
        return children

    def _write_tree_order(self, keys):
        self.connection.executemany('INSERT INTO tree_order(kind,item_id,position) VALUES(?,?,?) '
            'ON CONFLICT(kind,item_id) DO UPDATE SET position=excluded.position',
            [(kind, item_id, index) for index, (kind, item_id) in enumerate(keys)])

    def _validate_group_parent(self, folder_id, parent_id):
        descendants = self.connection.execute(
            'WITH RECURSIVE children(id) AS (SELECT id FROM folders WHERE id=? '
            'UNION SELECT f.id FROM folders f JOIN children c ON f.parent_id=c.id) '
            'SELECT id FROM children', (folder_id,)).fetchall()
        if parent_id in {row[0] for row in descendants}:
            raise ValueError('A group cannot be moved into itself or one of its subgroups.')
        if not descendants:
            raise ValueError('Group no longer exists.')

    def move_tree_item(self, kind, item_id, parent_id, anchor=None, after=False):
        if kind not in ('folder', 'profile'):
            raise ValueError('Invalid tree item.')
        table, column = ('folders', 'parent_id') if kind == 'folder' else ('profiles', 'folder_id')
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            if self.connection.execute(f'SELECT id FROM {table} WHERE id=?', (item_id,)).fetchone() is None:
                raise ValueError('Tree item no longer exists.')
            if parent_id is not None and not self.connection.execute('SELECT id FROM folders WHERE id=?', (parent_id,)).fetchone():
                raise ValueError('Group no longer exists.')
            if kind == 'folder':
                self._validate_group_parent(item_id, parent_id)
            keys = [(entry['kind'], entry['id']) for entry in self.tree_children(parent_id)]
            key = (kind, item_id)
            if anchor is not None:
                anchor = tuple(anchor)
                if anchor not in keys:
                    raise ValueError('The ordering destination no longer exists in this group.')
                if anchor == key:
                    return
            keys = [entry for entry in keys if entry != key]
            index = keys.index(anchor) + int(after) if anchor else len(keys)
            keys.insert(index, key)
            self.connection.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (parent_id, item_id))
            self._write_tree_order(keys)

    def sort_tree_children(self, parent_id):
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            children = sorted(self.tree_children(parent_id), key=lambda row: (row['kind'], row['name'].casefold(), row['id']))
            self._write_tree_order([(row['kind'], row['id']) for row in children])

    def tree_view_state(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='tree_view'").fetchone()
        return json.loads(row[0]) if row else {}

    def save_tree_view_state(self, collapsed, selected, scroll):
        if any(type(value) is not int for value in collapsed) or type(scroll) is not int or scroll < 0:
            raise ValueError('Invalid tree view state.')
        if selected is not None and (len(selected) != 2 or selected[0] not in ('folder', 'profile') or type(selected[1]) is not int):
            raise ValueError('Invalid tree selection.')
        state = dict(collapsed=collapsed, selected=selected, scroll=scroll)
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('tree_view',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(state),))

    def _save_group_appearance(self, folder_id, appearance):
        if appearance.get('icon', 'folder') == 'folder' and not appearance.get('color', ''):
            self.connection.execute('DELETE FROM folder_appearance WHERE folder_id=?', (folder_id,))
        else:
            self.connection.execute('INSERT INTO folder_appearance(folder_id,value) VALUES(?,?) '
                'ON CONFLICT(folder_id) DO UPDATE SET value=excluded.value', (folder_id, json.dumps(appearance)))

    def language(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='language'").fetchone()
        return row[0] if row and row[0] in ('en', 'it') else 'en'

    def toolbar_mode(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='toolbar_mode'").fetchone()
        return row[0] if row and row[0] in ('large', 'small', 'disabled') else 'large'

    def set_toolbar_mode(self, mode):
        if mode not in ('large', 'small', 'disabled'):
            raise ValueError('Unsupported toolbar mode.')
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('toolbar_mode',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mode,))

    def quick_connect_visible(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='quick_connect_visible'").fetchone()
        return not row or row[0] != '0'

    def set_quick_connect_visible(self, visible):
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('quick_connect_visible',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('1' if visible else '0',))

    def startup_indicators_visible(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='startup_indicators_visible'").fetchone()
        return not row or row[0] != '0'

    def set_startup_indicators_visible(self, visible):
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('startup_indicators_visible',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('1' if visible else '0',))

    def set_language(self, language):
        if language not in ('en', 'it'):
            raise ValueError('Unsupported interface language.')
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('language',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (language,))

    def inactivity_minutes(self):
        row = self.connection.execute("SELECT value FROM settings WHERE key='inactivity_minutes'").fetchone()
        return int(row[0]) if row else 0

    def set_inactivity_minutes(self, minutes):
        if type(minutes) is not int or not 0 <= minutes <= 1440:
            raise ValueError('Inactivity timeout must be between 0 and 1440 minutes.')
        with self.connection:
            self.connection.execute("INSERT INTO settings(key,value) VALUES('inactivity_minutes',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(minutes),))

    def _backup(self, password, reason, schema):
        try:
            publish_copy(self.path, backup_path(self.path, reason, schema),
                         lambda path: self.verify_key(path, password, kdf_iterations=self.kdf_iterations),
                         raw_database=True)
        except Exception as error:
            raise BackupError('Unable to create a verified encrypted backup.') from error

    @staticmethod
    def verify_key(path, password, *, kdf_iterations=LEGACY_KDF_ITERATIONS):
        path = Path(path).resolve()
        with path.open('rb') as database:
            check_encrypted_header(database)
        connection = sqlcipher.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            _configure_encryption(connection, password, kdf_iterations)
            connection.execute('SELECT count(*) FROM sqlite_master').fetchone()
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database integrity verification failed.')
            if connection.execute('PRAGMA cipher_integrity_check').fetchall():
                raise RuntimeError('Database encryption verification failed.')
            return connection.execute('PRAGMA user_version').fetchone()[0]
        finally:
            connection.close()

    def _reopen(self, password):
        self.connection = Vault(self.path, password, kdf_iterations=self.kdf_iterations,
                                create=False).connection

    def _publish_password_change(self):
        pass  # Plain SQLCipher files are already committed at this point.

    def _password_recovery_path(self, candidate):
        return candidate.with_suffix('.original')

    def change_password(self, current, replacement):
        schema = self._verify_rekey(current, replacement)
        self._backup(current, 'password', schema)
        self._replace_encryption(current, replacement, self.kdf_iterations)

    def _verify_rekey(self, current, replacement):
        if not current or not replacement or '\x00' in current or '\x00' in replacement:
            raise ValueError('Enter nonempty master passwords without NUL characters.')
        if current == replacement:
            raise ValueError('Choose a different new master password.')
        if self.connection.in_transaction:
            raise RuntimeError('Finish the current database operation first.')
        try:
            return self.verify_key(self.path, current, kdf_iterations=self.kdf_iterations)
        except sqlcipher.DatabaseError:
            raise ValueError('Current master password is incorrect.') from None

    def _replace_encryption(self, current, replacement, iterations):
        previous_iterations = self.kdf_iterations
        fd, candidate_name = tempfile.mkstemp(prefix='.unircm-rekey-', dir=self.path.parent)
        os.close(fd)
        candidate = Path(candidate_name)
        recovery = self._password_recovery_path(candidate)
        closed = False
        keep_recovery = False
        try:
            if iterations == previous_iterations:
                shutil.copyfile(self.path, candidate)
                connection = sqlcipher.connect(str(candidate))
                try:
                    _configure_encryption(connection, current, previous_iterations)
                    connection.execute('SELECT count(*) FROM sqlite_master').fetchone()
                    connection.reset_key(replacement)
                finally:
                    connection.close()
            else:
                self._export_encrypted(candidate, replacement, iterations)
            self.verify_key(candidate, replacement, kdf_iterations=iterations)
            try:
                self.verify_key(candidate, current, kdf_iterations=previous_iterations)
            except sqlcipher.DatabaseError:
                pass
            else:
                raise RuntimeError('The previous encryption settings still open the candidate database.')
            with candidate.open('rb') as staged:
                os.fsync(staged.fileno())
            os.link(self.path, recovery)
            self.connection.close()
            closed = True
            os.replace(candidate, self.path)
            self.kdf_iterations = iterations
            self._reopen(replacement)
            self._publish_password_change()
        except Exception:
            if closed:
                self.kdf_iterations = previous_iterations
                try:
                    self.connection.close()
                except Exception:
                    pass
                try:
                    os.replace(recovery, self.path)
                    self._reopen(current)
                except Exception:
                    keep_recovery = True
                    raise RuntimeError('Unable to restore the original encrypted database; preserve the rekey recovery file.') from None
            raise
        finally:
            candidate.unlink(missing_ok=True)
            if not keep_recovery:
                recovery.unlink(missing_ok=True)

    def _export_encrypted(self, candidate, password, iterations):
        validate_kdf_iterations(iterations)
        connection = self.connection
        schema = connection.execute('PRAGMA user_version').fetchone()[0]
        connection.execute('ATTACH DATABASE ? AS upgraded KEY ?', (str(candidate), password))
        try:
            connection.execute(f'PRAGMA upgraded.kdf_iter = {iterations}')
            connection.execute("SELECT sqlcipher_export('upgraded')").fetchone()
            connection.execute(f'PRAGMA upgraded.user_version = {schema}')
        finally:
            connection.execute('DETACH DATABASE upgraded')

    def profile_exists(self, profile_id):
        return self.connection.execute('SELECT 1 FROM profiles WHERE id=?', (profile_id,)).fetchone() is not None

    def profiles(self, profile_id=None):
        self.connection.row_factory = sqlcipher.Row
        query = ('''SELECT profiles.*, (SELECT name FROM ssh_private_keys WHERE profile_id=profiles.id)
                    AS imported_key_name FROM profiles'''
                 + (' WHERE id=?' if profile_id is not None else '') + ' ORDER BY name,id')
        profiles = [dict(row) for row in self.connection.execute(query, (profile_id,) if profile_id is not None else ())]
        for profile in profiles:
            for key in ('before_connect_command', 'after_disconnect_command', 'ssh_startup_commands'):
                if not profile[key]:
                    profile.pop(key)
            if profile['authentication'] is None:
                profile.pop('authentication')
            if profile['imported_key_name'] is None:
                profile.pop('imported_key_name')
            credential = self.credential(profile.get('credential_id'))
            profile['password'] = credential['password'] if credential and profile['credential_source'] == 'local' else ''
            profile['key_passphrase'] = credential['key_passphrase'] if credential and profile['credential_source'] == 'local' else ''
            if credential and profile['credential_source'] == 'local':
                profile['username'] = credential['username']
            profile['terminal_options'] = json.loads(profile['terminal_options'])
            profile['telnet_options'] = json.loads(profile['telnet_options'])
            profile['rdp_options'] = json.loads(profile['rdp_options'])
            profile['ssh_advanced'] = json.loads(profile['ssh_advanced'])
            modes = json.loads(profile.pop('ssh_modes'))
            if modes:
                profile['ssh_modes'] = modes
        return profiles

    def credential(self, credential_id):
        if credential_id is None:
            return None
        self.connection.row_factory = sqlcipher.Row
        row = self.connection.execute('SELECT * FROM credentials WHERE id=?', (credential_id,)).fetchone()
        return dict(row) if row else None

    def shared_credentials(self):
        self.connection.row_factory = sqlcipher.Row
        return [dict(row) for row in self.connection.execute(
            "SELECT id,name,username FROM credentials WHERE name<>'' ORDER BY name,id")]

    def require_shared_credential(self, credential_id):
        credential = self.credential(credential_id)
        if not credential or not credential['name']:
            raise ValueError('Select an existing shared credential.')
        return credential

    def save_credential(self, name, username, password, credential_id=None, key_passphrase=''):
        name = name.strip()
        if not name:
            raise ValueError('Enter a credential name.')
        validate_ssh_settings({'username': username})
        validate_password(password)
        validate_password(key_passphrase)
        if credential_id:
            self.require_shared_credential(credential_id)
        credential_id = credential_id or str(uuid.uuid4())
        with self.connection:
            self.connection.execute('INSERT INTO credentials(id,name,username,password,key_passphrase) VALUES(?,?,?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET name=excluded.name,username=excluded.username,password=excluded.password,key_passphrase=excluded.key_passphrase',
                (credential_id, name, username, password, key_passphrase))
        return credential_id

    def delete_credential(self, credential_id):
        self.require_shared_credential(credential_id)
        if (self.connection.execute('SELECT 1 FROM profiles WHERE credential_id=?', (credential_id,)).fetchone()
                or any(f.get('ssh_defaults', {}).get('credential_id') == credential_id for f in self.folders())):
            raise ValueError('Credential is in use. Remove connection and group references first.')
        with self.connection:
            self.connection.execute('DELETE FROM credentials WHERE id=?', (credential_id,))

    def save(self, profile):
        with self.connection:
            profile_id = self._save_profile(profile)
            if 'imported_key' in profile:
                self.connection.execute('DELETE FROM ssh_private_keys WHERE profile_id=?', (profile_id,))
                if profile['imported_key'] is not None:
                    name, key_data = profile['imported_key']
                    self.connection.execute('INSERT INTO ssh_private_keys VALUES(?,?,?)',
                                            (profile_id, name, key_data))
            return profile_id

    def ssh_private_key(self, profile):
        if (profile.get('protocol', 'ssh') != 'ssh'
                or profile.get('ssh_modes', {}).get('identity_file', 'override') != 'override'):
            return None
        row = self.connection.execute('SELECT key_data FROM ssh_private_keys WHERE profile_id=?',
                                      (profile.get('id'),)).fetchone()
        return row[0] if row else None

    def _save_profile(self, profile):
        values = tuple(profile[k] for k in ('name', 'host', 'port', 'username', 'identity_file')) + (profile.get('folder_id'), profile.get('protocol', 'ssh'), profile.get('icon', 'terminal'), profile.get('tab_color', ''), json.dumps(profile.get('terminal_options', {})))
        validate_rdp_options(profile.get('rdp_options', {}))
        domain = profile.get('rdp_domain', '')
        if not isinstance(domain, str) or len(domain) > 255 or any(c in domain for c in '\r\n\x00'):
            raise ValueError('Invalid RDP domain.')
        validate_advanced(profile.get('ssh_advanced', {}))
        validate_terminal_options(profile.get('terminal_options', {}))
        validate_color(profile.get('tab_color', ''))
        modes = profile.get('ssh_modes', {})
        validate_ssh_settings(modes, modes=True)
        timeout = profile.get('connect_timeout', 15)
        validate_connect_timeout(timeout)
        values += (json.dumps(modes), timeout)
        source = profile.get('credential_source', 'local')
        if source not in ('local', 'shared', 'inherit', 'none'):
            raise ValueError('Invalid credential source.')
        credential_id = profile.get('credential_id')
        if source == 'local':
            if credential_id is None and profile.get('id') is not None:
                row = self.connection.execute('SELECT credential_id FROM profiles WHERE id=?', (profile['id'],)).fetchone()
                credential_id = row[0] if row else None
            previous = self.credential(credential_id)
            # Local editing must never mutate a reusable credential.
            if previous and previous['name']:
                previous = None
                credential_id = None
            password = profile.get('password', previous['password'] if previous else '')
            validate_password(password)
            key_passphrase = profile.get('key_passphrase', previous['key_passphrase'] if previous else '')
            validate_password(key_passphrase)
            credential_id = credential_id or str(uuid.uuid4())
        elif source == 'shared':
            self.require_shared_credential(credential_id)
        else:
            credential_id = None
        if profile.get('protocol', 'ssh') not in ('ssh', 'telnet', 'rdp', 'vnc'):
            raise ValueError('Unsupported connection protocol.')
        from remote_manager.terminal.telnet import validate_options
        telnet_options = profile.get('telnet_options', {})
        validate_options(telnet_options)
        reconnect_delay = profile.get('ssh_reconnect_delay', 0) if profile.get('protocol', 'ssh') == 'ssh' else 0
        if type(reconnect_delay) is not int or not 0 <= reconnect_delay <= MAX_SSH_RECONNECT_DELAY:
            raise ValueError('Invalid SSH reconnect delay.')
        authentication = profile.get('authentication')
        if authentication not in (None, 'configured', 'prompt_password', 'prompt_both'):
            raise ValueError('Invalid authentication mode.')
        values += (credential_id, source, json.dumps(telnet_options), int(bool(profile.get('connect_at_startup', False))), json.dumps(profile.get('ssh_advanced', {})), domain, json.dumps(profile.get('rdp_options', {})), reconnect_delay, authentication)
        commands = tuple(profile.get(key, '') for key in ('before_connect_command', 'after_disconnect_command'))
        if any(not isinstance(command, str) or any(char in command for char in '\r\n\x00') for command in commands):
            raise ValueError('Enter each local command on a single line.')
        startup_commands = profile.get('ssh_startup_commands', '')
        if not isinstance(startup_commands, str) or '\x00' in startup_commands:
            raise ValueError('Enter valid SSH startup commands.')
        values += (*commands, startup_commands)
        if source == 'local':
            self.connection.execute('INSERT INTO credentials(id,username,password,key_passphrase) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password=excluded.password,key_passphrase=excluded.key_passphrase',
                                    (credential_id, profile['username'], password, key_passphrase))
        if profile.get('id') is None:
            return self.connection.execute('INSERT INTO profiles(name,host,port,username,identity_file,folder_id,protocol,icon,tab_color,terminal_options,ssh_modes,connect_timeout,credential_id,credential_source,telnet_options,connect_at_startup,ssh_advanced,rdp_domain,rdp_options,ssh_reconnect_delay,authentication,before_connect_command,after_disconnect_command,ssh_startup_commands) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values).lastrowid
        self.connection.execute("DELETE FROM tree_order WHERE kind='profile' AND item_id=? AND EXISTS (SELECT 1 FROM profiles WHERE id=? AND folder_id IS NOT ?)", (profile['id'], profile['id'], profile.get('folder_id')))
        self.connection.execute('UPDATE profiles SET name=?,host=?,port=?,username=?,identity_file=?,folder_id=?,protocol=?,icon=?,tab_color=?,terminal_options=?,ssh_modes=?,connect_timeout=?,credential_id=?,credential_source=?,telnet_options=?,connect_at_startup=?,ssh_advanced=?,rdp_domain=?,rdp_options=?,ssh_reconnect_delay=?,authentication=?,before_connect_command=?,after_disconnect_command=?,ssh_startup_commands=? WHERE id=?', values + (profile['id'],))
        return profile['id']

    def copy_profile(self, profile_id, folder_id, anchor=None, after=False):
        if type(profile_id) is not int:
            raise ValueError('Connection no longer exists.')
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            records = self.profiles(profile_id)
            if not records:
                raise ValueError('Connection no longer exists.')
            if folder_id is not None and not self.connection.execute('SELECT id FROM folders WHERE id=?', (folder_id,)).fetchone():
                raise ValueError('Group no longer exists.')
            keys = [(entry['kind'], entry['id']) for entry in self.tree_children(folder_id)]
            if anchor is not None:
                anchor = tuple(anchor)
                if anchor not in keys:
                    raise ValueError('The ordering destination no longer exists in this group.')
            original = records[0]
            names = {row[0] for row in self.connection.execute('SELECT name FROM profiles')}
            name = original['name'] + ' (copy)'
            number = 2
            while name in names:
                name = f"{original['name']} (copy {number})"
                number += 1
            copy = dict(original, id=None, name=name, folder_id=folder_id,
                        credential_id=original.get('credential_id') if original.get('credential_source') == 'shared' else None)
            new_id = self._save_profile(copy)
            self.connection.execute('''INSERT INTO ssh_private_keys
                SELECT ?, name, key_data FROM ssh_private_keys WHERE profile_id=?''', (new_id, profile_id))
            index = keys.index(anchor) + int(after) if anchor else len(keys)
            keys.insert(index, ('profile', new_id))
            self._write_tree_order(keys)
            return new_id

    def delete(self, profile_id):
        with self.connection:
            self.connection.execute('DELETE FROM profiles WHERE id=?', (profile_id,))
            self.connection.execute("DELETE FROM tree_order WHERE kind='profile' AND item_id=?", (profile_id,))
            self.connection.execute("DELETE FROM credentials WHERE name='' AND id NOT IN (SELECT credential_id FROM profiles WHERE credential_id IS NOT NULL)")

    def folders(self):
        self.connection.row_factory = sqlcipher.Row
        folders = [dict(row) for row in self.connection.execute('SELECT folders.*,folder_appearance.value AS appearance FROM folders LEFT JOIN folder_appearance ON folders.id=folder_appearance.folder_id ORDER BY name,id')]
        for folder in folders:
            appearance = folder.pop('appearance')
            if appearance is not None:
                folder['appearance'] = json.loads(appearance)
            defaults = json.loads(folder.pop('ssh_defaults'))
            if defaults:
                folder['ssh_defaults'] = defaults
        return folders

    def set_folder_defaults(self, folder_id, defaults):
        validate_ssh_settings(defaults)
        if defaults.get('credential_id'):
            self.require_shared_credential(defaults['credential_id'])
        with self.connection:
            if not self.connection.execute('UPDATE folders SET ssh_defaults=? WHERE id=?',
                                           (json.dumps(defaults), folder_id)).rowcount:
                raise ValueError('Group no longer exists.')

    def effective_profile(self, profile):
        source = profile.get('credential_source', 'local')
        candidate = dict(profile)
        candidate['ssh_modes'] = dict(profile.get('ssh_modes', {}), credential_id='inherit' if source == 'inherit' else 'default' if source == 'none' else 'override')
        result = resolve_ssh(candidate, self.folders())
        result['terminal_options'] = self.expand_terminal_options(result['terminal_options'])
        credential_id = result.get('credential_id')
        if source != 'local':
            result['password'] = ''
            result['key_passphrase'] = ''
            if credential_id:
                credential = self.require_shared_credential(credential_id)
                result.update(password=credential['password'], key_passphrase=credential['key_passphrase'])
                username_mode = profile.get('ssh_modes', {}).get('username')
                if profile.get('authentication') is None or username_mode == 'credential':
                    result['username'] = credential['username']
        return result

    def save_folder(self, name, parent_id=None, folder_id=None, defaults=None, appearance=None):
        if appearance is not None:
            validate_group_appearance(appearance)
        if defaults is not None:
            validate_ssh_settings(defaults)
            if defaults.get('credential_id'):
                self.require_shared_credential(defaults['credential_id'])
        name = name.strip()
        if not name:
            raise ValueError('Enter a group name.')
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            if folder_id is None:
                folder_id = self.connection.execute('INSERT INTO folders(name,parent_id,ssh_defaults) VALUES(?,?,?)', (name, parent_id, json.dumps(defaults or {}))).lastrowid
                if appearance is not None:
                    self._save_group_appearance(folder_id, appearance)
                return folder_id
            self._validate_group_parent(folder_id, parent_id)
            previous = self.connection.execute('SELECT parent_id FROM folders WHERE id=?', (folder_id,)).fetchone()[0]
            if previous != parent_id:
                self.connection.execute("DELETE FROM tree_order WHERE kind='folder' AND item_id=?", (folder_id,))
            self.connection.execute('UPDATE folders SET name=?,parent_id=? WHERE id=?', (name, parent_id, folder_id))
            if defaults is not None:
                self.connection.execute('UPDATE folders SET ssh_defaults=? WHERE id=?', (json.dumps(defaults), folder_id))
            if appearance is not None:
                self._save_group_appearance(folder_id, appearance)
            return folder_id

    def move_profile(self, profile_id, folder_id):
        with self.connection:
            self.connection.execute("DELETE FROM tree_order WHERE kind='profile' AND item_id=? AND EXISTS (SELECT 1 FROM profiles WHERE id=? AND folder_id IS NOT ?)", (profile_id, profile_id, folder_id))
            self.connection.execute('UPDATE profiles SET folder_id=? WHERE id=?', (folder_id, profile_id))

    def delete_folder(self, folder_id):
        # Preserve all connections and subfolders by moving them up one level.
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            folder = self.connection.execute('SELECT parent_id FROM folders WHERE id=?', (folder_id,)).fetchone()
            if folder is None:
                raise ValueError('Group no longer exists.')
            parent_keys = [(entry['kind'], entry['id']) for entry in self.tree_children(folder[0])]
            child_keys = [(entry['kind'], entry['id']) for entry in self.tree_children(folder_id)]
            index = parent_keys.index(('folder', folder_id))
            parent_keys[index:index + 1] = child_keys
            self.connection.execute('UPDATE profiles SET folder_id=? WHERE folder_id=?', (folder[0], folder_id))
            self.connection.execute('UPDATE folders SET parent_id=? WHERE parent_id=?', (folder[0], folder_id))
            self.connection.execute('DELETE FROM folders WHERE id=?', (folder_id,))
            self.connection.execute("DELETE FROM tree_order WHERE kind='folder' AND item_id=?", (folder_id,))
            self._write_tree_order(parent_keys)

    def close(self):
        self.connection.close()


SSH_DEFAULTS = dict(port=22, username='', identity_file='', terminal_options={}, tab_color='', connect_timeout=15, credential_id='', ssh_advanced={})


def validate_ssh_settings(settings, modes=False):
    for key, value in settings.items():
        if key not in SSH_DEFAULTS:
            raise ValueError('Unsupported SSH property.')
        if modes:
            if value not in ('inherit', 'override', 'default') and (key, value) != ('username', 'credential'):
                raise ValueError('Invalid SSH property mode.')
        elif value is not None:
            if key == 'ssh_advanced':
                validate_advanced(value)
            elif key == 'terminal_options':
                validate_terminal_options(value)
            elif key == 'tab_color':
                validate_color(value)
            elif key == 'connect_timeout':
                validate_connect_timeout(value)
            elif key == 'port':
                if type(value) is not int or not 1 <= value <= 65535:
                    raise ValueError('Invalid SSH port.')
            elif not isinstance(value, str) or '\x00' in value:
                raise ValueError('Invalid SSH property.')
            elif key == 'username' and value:
                import re
                if value.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@-]+', value):
                    raise ValueError('Invalid username.')


def resolve_ssh(profile, folders):
    """Resolve at use time; missing group keys inherit, None stops at app default."""
    result = dict(profile)
    by_id = {folder['id']: folder for folder in folders}
    for key, default in SSH_DEFAULTS.items():
        mode = profile.get('ssh_modes', {}).get(key, 'override')
        if mode == 'override':
            if key == 'connect_timeout':
                result[key] = profile.get(key, default)
            continue
        result[key] = default
        ancestor = profile.get('folder_id') if mode in ('inherit', 'credential') else None
        visited = set()
        while ancestor is not None:
            if ancestor in visited:
                raise ValueError('Group hierarchy contains a cycle.')
            visited.add(ancestor)
            folder = by_id[ancestor]
            settings = folder.get('ssh_defaults', {})
            if key in settings:
                result[key] = default if settings[key] is None else settings[key]
                break
            ancestor = folder['parent_id']
    result['terminal_options'] = resolve_terminal_options(profile, folders)
    return result


def resolve_terminal_options(profile, folders):
    by_id = {folder['id']: folder for folder in folders}

    def parent_value(key, ancestor):
        visited = set()
        while ancestor is not None:
            if ancestor in visited:
                raise ValueError('Group hierarchy contains a cycle.')
            visited.add(ancestor)
            folder = by_id[ancestor]
            settings = folder.get('ssh_defaults', {})
            if 'terminal_options' in settings:
                values = settings['terminal_options']
                if values is None or key not in values:
                    return None  # Legacy complete profile: missing keys use defaults.
                value = values[key]
                if value is not None:
                    return None if value == {'source': 'default'} else value
            ancestor = folder['parent_id']
        return None

    mode = profile.get('ssh_modes', {}).get('terminal_options', 'override')
    ancestor = profile.get('folder_id')
    values = profile.get('terminal_options', {})
    if mode == 'default':
        return {}
    if mode == 'inherit':
        values = {}
        visited = set()
        while ancestor is not None:
            if ancestor in visited:
                raise ValueError('Group hierarchy contains a cycle.')
            visited.add(ancestor)
            folder = by_id[ancestor]
            settings = folder.get('ssh_defaults', {})
            ancestor = folder['parent_id']
            if 'terminal_options' in settings:
                values = settings['terminal_options'] or {}
                break
    result = {}
    for key, value in values.items():
        if value is None:
            value = parent_value(key, ancestor)
        if value is not None and value != {'source': 'default'}:
            result[key] = value
    return result


def validate_color(value):
    import re
    if not isinstance(value, str) or (value and not re.fullmatch(r'#[0-9a-fA-F]{6}', value)):
        raise ValueError('Invalid color: use #RRGGBB.')


def validate_terminal_options(options):
    if not isinstance(options, dict):
        raise ValueError('Invalid terminal appearance.')
    for key, value in options.items():
        if key == 'profile_id':
            if not isinstance(value, str) or not value:
                raise ValueError('Invalid terminal profile reference.')
            continue
        if key not in ('background', 'foreground', 'cursor_color', 'font_family', 'font_size', 'cursor_shape', 'cursor_blink'):
            raise ValueError('Unsupported terminal appearance property.')
        if value is None or value == {'source': 'default'}:
            continue
        if key in ('background', 'foreground', 'cursor_color'):
            validate_color(value)
            if not value:
                raise ValueError('A terminal color is required.')
        elif key == 'font_family':
            if not isinstance(value, str) or not value.strip() or '\x00' in value:
                raise ValueError('Invalid terminal font.')
        elif key == 'font_size':
            if type(value) is not int or not 6 <= value <= 72:
                raise ValueError('Invalid terminal font size.')
        elif key == 'cursor_shape':
            if value not in ('outline', 'block', 'underline', 'bar'):
                raise ValueError('Invalid cursor shape.')
        elif key == 'cursor_blink':
            if type(value) is not bool:
                raise ValueError('Invalid cursor blink setting.')
        else:
            raise ValueError('Unsupported terminal appearance property.')


def validate_connect_timeout(value):
    if type(value) is not int or not 1 <= value <= 600:
        raise ValueError('SSH connection timeout must be between 1 and 600 seconds.')


def validate_password(password):
    if not isinstance(password, str) or any(c in password for c in ('\x00', '\r', '\n')):
        raise ValueError('Password cannot contain NUL or line breaks.')


def validate_group_appearance(appearance):
    if not isinstance(appearance, dict) or set(appearance) - {'icon', 'color'}:
        raise ValueError('Invalid group appearance.')
    if appearance.get('icon', 'folder') not in ('folder', *CONNECTION_ICONS):
        raise ValueError('Invalid group icon.')
    validate_color(appearance.get('color', ''))
