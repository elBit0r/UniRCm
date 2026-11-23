# UniRCm project specification

Uni Remote Connection Manager (UniRCm) brings SSH terminals, Telnet terminals
and remote desktops into one desktop app for system administrators. It keeps
saved connections in a folder tree and opens concurrent sessions in a tabbed
workspace.

[README.md](README.md) explains how to get started.
[TASKS.md](TASKS.md) records implemented features, gaps and verified results.

## Scope and platforms

- Keep the end-to-end SSH workflow the priority. RDP and Telnet are part of the
  current product. VNC remains experimental. HTTP/HTTPS is a possible future
  addition after the remote session workflows are stable. Further protocol
  work requires an explicit request.
- Develop and verify on Linux first. Support X11 and Wayland where feasible.
  Debian is the first native packaging target. FreeBSD is an intended target
  and still needs validation. OpenBSD is deferred.
- Use portable Python, Qt and POSIX interfaces where possible. Isolate
  platform-specific code and record tested versions, display backends and
  limitations in [docs/compatibility.md](docs/compatibility.md).
- Serial consoles, RAW sockets, Rlogin, PowerShell-specific integration, cloud
  login, team permissions, synchronization servers, session recording and
  managed bastion services are outside the initial scope.

## Desktop workflow

- Use PyQt6 Widgets with a connection tree, tabbed workspace, connection editor,
  Quick Connect, preferences and session status. The design includes an optional
  property inspector and event panel, system/light/dark themes, high-DPI support
  and keyboard navigation.
- Support nested folders, reordering, moving connections and folders, duplicating
  individual connections, search, favorites and context menus. Double-click a
  saved connection to open it. Bulk connection, if offered, requires confirmation
  for large groups.
- Profiles include a name, address, protocol, port, username, credential
  reference, folder, notes, tags, timeout and appearance settings. Put
  protocol-specific settings in labeled panels. Validate addresses, ports and
  protocol options before saving.
- Resolve inheritable settings from the closest explicit override, then the
  application default. Keep inherit, explicit empty values and explicit
  application defaults distinct. Resolve credentials by stable reference.
- Keep sessions responsive and show meaningful status and errors. Support
  renaming and reordering tabs, reconnecting and disconnecting. Closing a tab
  releases session resources. Workspace restoration is opt-in and requires
  explicit permission before reconnecting or sending credentials.
- Use English for source text and provide Italian translations, including the
  unlock screen. Make UI text translatable with English fallback. Buttons show
  an icon and text, with a translatable tooltip where useful. Use themed icons
  with a Qt fallback.

## Architecture

Use Python 3.11+, PyQt6 and SQLCipher. Keep UI, session management, protocol
transports and storage separate. Use asynchronous I/O or workers and Qt signals
to report state without blocking the UI. Protocols report their capabilities,
session status, display mode and errors. Load optional backends on demand.

Share credential editing and storage across protocols. Adapters receive the
resolved credentials through the common encrypted reference. External
credential providers are future work. See [docs/architecture.md](docs/architecture.md)
for the current module layout.

## Encrypted storage

- Store all connection metadata, settings and credentials in SQLCipher 4.
  Create databases encrypted from the start. Fail closed if SQLCipher is
  unavailable or the key is invalid. Verify the key and active encryption
  before reading saved data. Plaintext SQLite fallback is prohibited.
- Use the per-user application data directory for the default vault. Restrict
  permissions on the directory, database, working files, sockets and backups.
  Account for auxiliary files and concurrent writers.
- Use versioned migrations, foreign keys, parameterized queries and
  transactions. Preserve access to existing vaults across upgrades. Provide
  integrity checks for maintenance.
- Only minimal non-secret pre-unlock preferences may live outside the vault,
  such as language, theme, window geometry and vault paths. A portable
  `.uni` archive may expose its public description. Connection details and
  private metadata stay encrypted.

## Vault and credentials

- On first use, ask for and confirm a master password, then verify that the new
  vault can be reopened. Require the password before loading saved connections
  on subsequent launches. Report unlock failure without exposing secrets.
- Locking disconnects sessions, closes database handles and clears accessible
  credentials. Support manual lock and configurable inactivity lock. Shutdown
  also cleans up sessions and database handles.
- Changing the master password requires the old password and SQLCipher rekeying.
  Verify the new password, rejection of the old password and recovery if
  publication fails. A forgotten password has no bypass.
- Support shared, inherited and per-connection credentials, SSH identity paths
  and private-key passphrases. Prefer keys and the SSH agent where available.
  Revealing or copying a stored password requires deliberate user action.
- Allow a connection to import an OpenSSH private key into the encrypted vault.
  On Linux, supply it to OpenSSH through an anonymous in-memory file and close
  the descriptor after authentication or session failure. Never fall back to a
  disk file. Imported keys are included in encrypted vault backups.
- Install the corresponding public key into the active SSH account's
  `~/.ssh/authorized_keys` through the authenticated session. Confirm the
  destination and fingerprint first, and preserve existing authorizations.
- Before changing the schema version, master password or archive KDF, save and
  verify an encrypted backup beside the database. Abort the change if backup
  verification fails. Restore to a separate file using the master password
  valid when the backup was created and its key file if required. Keep archive
  publication consistent after committed changes.
- Portable archives can require an optional key file alongside the master
  password. Combine the password KDF output and the SHA-256 file digest with
  HKDF. Store only the key file requirement in public metadata. Generate key
  files with 32 random bytes and mode `0600`. Adding, removing or replacing a
  key file uses the verified backup and encrypted-staging rekey workflow.
- New portable archives default to Argon2id. PBKDF2 remains selectable for new
  archives that require compatibility. The legacy archive KDF upgrade changes
  PBKDF2 from 256,000 to 512,000 iterations.
- If JSON import/export is added, version the format and validate sizes,
  structure, protocols and references. Exclude credentials and secrets from
  plaintext exports and warn that exported connection metadata is readable.

## Protocols

### SSH

Use OpenSSH with an embedded PTY terminal. Support keys, agent and password
authentication, known-host verification, jump hosts, forwarding, keepalives and
configurable terminal profiles. Keep agent forwarding off by default. Support
Unicode, colors, resize, scrollback, clipboard and interactive terminal input.
Report authentication errors and process exit status.

Provide SFTP upload and download from an open, authenticated SSH session. Reuse
the connection and support remote directory browsing, overwrite confirmation,
progress and cancellation. SFTP requires server support.

### RDP

Use the optional native FreeRDP 3 bridge and embedded Qt desktop. Support
username, password and optional domain, keyboard and mouse, scaling,
resolution settings and fullscreen. Request dynamic resolution when the server
supports it. Text clipboard sharing is opt-in. Keep certificate checks enabled
and show actionable errors. If an external display mode is added, label it
explicitly and keep disconnect and cleanup under application control.

### Telnet

Provide an interactive terminal with option negotiation, configurable terminal
type and encoding, and resize where supported. Clearly warn that credentials
and session data travel unencrypted. Sending stored credentials requires an
explicit login mode and a warning.

### VNC

The intended workflow includes an embedded remote framebuffer, authentication,
keyboard and mouse, view-only mode, scaling, fullscreen and clipboard where
supported. Flag unencrypted transport. If a local bridge is used, bind it to
loopback, restrict access and stop it with the session.

### HTTP/HTTPS

If requested later, keep the browser backend optional. Support navigation,
authentication prompts, isolated browser profiles where appropriate and HTTPS
certificate validation. Flag plaintext HTTP. Offer an explicitly labeled
system browser option where embedding is unavailable. Never inject saved vault
passwords into arbitrary pages.

## Security

- Never put passwords in arguments, environment variables, logs, plaintext files
  or exports. Use private, short-lived authentication channels when needed.
  Pass subprocess arguments as arrays and keep user input out of shell commands.
- Verify SSH host keys and RDP/TLS certificates by default. Show fingerprints or
  certificate details when requesting trust decisions.
- Log operational events without recording terminal input, tokens, passwords,
  private keys or sensitive exception details.
- SQLCipher protects saved data against offline access. An unlocked process and
  compromised desktop remain exposed to local inspection. Python cannot
  guarantee that all copies of a secret are erased from memory.
- Telemetry, cloud services and automatic network updates require a separate
  product decision.

## Verification and distribution

- Keep essential checks for encrypted storage, wrong-password rejection,
  rekeying, migrations, archive reopening, credential leaks and session cleanup.
  Verify connection editing and inheritance when those paths change.
- Validate protocol changes with real sessions on the current development
  platform. Cover authentication, trust failures and interactive features
  relevant to the change. A TCP connection alone does not verify a session.
- Package from `pyproject.toml` using constrained dependencies. Support ordinary
  execution without root. Validate native dependencies and package builds on
  each target before claiming support.
- Use original or appropriately licensed code and assets. Preserve license
  notices, attribution and dependency obligations when distributing builds.
