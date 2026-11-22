# Development Tasks

Updated 2026-11-22. [PROJECT.md](PROJECT.md) defines product scope.

## Open work

- [ ] Restore workspace layouts and splitter proportions across restarts.
- [ ] Extend terminal keyboard protocol and full-screen application coverage.

## Verification and distribution

- [ ] Review the native desktop UI at high DPI, including tree and workspace
  dragging, splitter gestures and terminal selection.
- [ ] Verify RDP dynamic resizing against a Display Control-capable server.
  Check remote mouse wheel input, visual options, administrative sessions and
  changed-certificate acceptance limited to the active session.
- [ ] Verify Telnet against an external router or switch, including login
  prompts that may require manual entry.
- [ ] Measure terminal responsiveness and CPU usage with continuous remote
  output, including aafire.
- [ ] Verify VNC authentication, rendering and input against a real VNC server.
- [ ] Verify installation and real sessions on a Debian 13 amd64 desktop.
- [ ] Review distribution dependencies and bundled artwork obligations.
  The project license is GPL-3.0-or-later.
- [ ] Validate FreeBSD builds and runtime, and check manylinux portability.

## Current functionality

- **Icon library.** 201 icons, including 90 new service, system, device and platform
  entries. Verified rendering and English/Italian search from the Linux wheel and
  icon persistence for connections and groups in SQLCipher.

- **Connection editor.** Field icons, radio buttons for credential and username sources, and
  independent password/passphrase visibility. Optional SSH reconnection waits
  for the per-profile delay stored in SQLCipher. Verified delayed replacement
  with a real OpenSSH session on Linux loopback.

- **Vault and credentials.** SQLCipher stores profiles and shared, inherited
  and per-connection credentials. The database chooser supports create, unlock,
  switch and forget. Manual and inactivity locking close sessions and clear
  accessible credentials. Master-password changes use encrypted staging and
  check recovery on publication failure. Reopening a `.uni` after a crash
  verifies and republishes its encrypted working copy. Back up by copying the
  complete `.uni` archive. New archives default to 512,000 PBKDF2 iterations, adjustable
  to 4,096,000 at setup. Legacy archives and standalone SQLCipher files use
  256,000. Setup includes a live password-strength meter with Italian labels.
- **SSH and terminal.** Real OpenSSH PTY sessions support password and key
  authentication, host-key checking, ProxyJump and local, remote and dynamic
  forwarding. Imported private keys stay in the vault and are supplied through
  an anonymous Linux descriptor. An authenticated session can install the
  corresponding public key after fingerprint confirmation. SSH ASKPASS uses
  private socket IPC. The terminal supports ANSI/Unicode, selection, clipboard,
  mouse reporting, scrollback and live appearance updates. SFTP supports file
  upload and download with cancellation and bounded temporary-file cleanup.
- **Navigation and workspaces.** Nested groups support inherited settings and
  credentials, sorting, search, custom icons and persistent tree state.
  Individual connections can be duplicated. Workspaces support up to four
  live panes, session movement by menu or drag and drop, maximize/restore
  and detach. Layout actions can create an empty workspace that stays open
  after its last pane closes. Verified on Linux with loopback SSH.
- **Local terminal.** Session → New local terminal opens an interactive shell
  in a tab or the first vacant pane. The Local tree contains the default
  terminal and encrypted profiles with a working directory and startup
  commands. The tree starts hidden and can be shown with View → Local profiles.
  Add profiles from its context menu and drag them to a specific pane.
  Linux checks verified persistence, multiline startup
  in a real shell, exit status and cleanup.
- **RDP.** The optional native FreeRDP 3 bridge embeds the desktop in Qt.
  It supports common credentials, certificate checks, keyboard and mouse,
  scaling, fullscreen and opt-in text clipboard. Local scaling is used when
  the server lacks Display Control.
- **Telnet.** Supports negotiation, encoding, resize, manual login and
  one-shot login with shared vault credentials and cleartext warnings.
- **VNC (experimental).** The embedded Qt RFB 3.8 viewer supports raw
  framebuffers, scaling, keyboard/mouse input and view-only mode. LibVNCClient
  supplies authentication using shared vault credentials in memory. Linux
  fixture and DES vector checks passed. TLS, clipboard, wheel input,
  fullscreen and broader encoding support remain open.
- **UI and packaging.** English and Italian UI, scrollable editors with fixed
  Save/Cancel controls, and wheel/sdist packaging with an optional native RDP
  bridge. ABI-2 bridge binaries require rebuilding for ABI 3.

## Deferred or limited

- Defer HTTP/HTTPS and external credential providers.
- Keep backups manual and duplication limited to individual connections.
- SFTP directory recursion and shell-directory tracking remain unsupported.
  Connectivity or permissions can prevent cleanup of a cancelled upload.
- RDP file/image clipboard and pointer warping remain unsupported.

## Recorded Linux verification

- Built UniRCm 0.2.0 amd64 packages for Debian 13 and Ubuntu 26.04 and
  verified SHA-256 checksums. Debian installation and launcher startup
  passed in an isolated Debian 13 environment with Qt offscreen. Ubuntu
  APT upgrade simulation and package, vault, archive, and SFTP checks passed.
- Rebuilt both 0.2.0 packages with the FreeRDP 3 bridge enabled by default.
  APT resolved FreeRDP and WinPR on both targets. Installed packages loaded
  the bridge and initialized an RDP context. Four Ubuntu native and TLS tests passed.
- Built UniRCm 0.1.1 amd64 packages on Ubuntu 26.04 and in the isolated
  Debian 13 environment. The Ubuntu startup dialog used the `unircm` desktop
  identity and its window icon offscreen. Package tests and Ubuntu APT upgrade
  simulation passed. GNOME dock grouping still needs a desktop check.
- Revision 2 of both amd64 packages requires `python3-pyqt6.qtsvg` to fix
  the connection icon crash. APT simulation selected the dependency on both
  distributions, and the Ubuntu package rendered the SVG icons offscreen.
- Built both amd64 packages with the default maintainer, using Ubuntu 26.04
  locally and Debian 13 in an isolated PRoot environment. APT simulation and
  launcher checks passed for both. The single-command Docker/Podman path
  still needs an end-to-end run with a container engine.
- On Ubuntu 26.04.1 amd64, built `unircm_0.1.0-1+ubuntu26.04_amd64.deb`
  with Python 3.14 and `--target ubuntu26.04`. The builder rejected
  `--target debian13` on Ubuntu. APT simulation resolved all dependencies. The extracted
  package included both launchers and loaded SQLCipher 4.12.0.
- On Ubuntu 26.04.1, the existing FreeRDP 3 bridge loaded with ABI 3.
  Of 28 targeted RDP checks, 27 passed, including loopback TLS rejection and
  connection cleanup. The native channel harness was skipped because the
  FreeRDP development headers were unavailable. No authenticated RDP session
  was exercised.

- Built `unircm_0.1.0-1_amd64.deb` with FreeRDP on Debian 13. In a separate
  rootless Debian environment, dpkg configured the package after an
  ssh-agent ownership override for the user namespace. The installed launcher
  opened the startup dialog offscreen, SQLCipher reported 4.12.0, and the
  FreeRDP bridge loaded with ABI 3.

- Built and installed the 0.1.0 wheel in a temporary directory. Four targeted
  checks passed for package metadata, launchers, bundled notices and the Help
  menu's About dialog with license, email and website.

- First Git snapshot prepared with local IDE files, vaults, keys and build
  outputs excluded. Packaging metadata, GUI startup, vaults, archives and
  credentials passed 25 targeted tests, including two askpass tests run with
  local Unix sockets enabled. Three optional SSH server tests were skipped.

- Targeted vault checks covered wrong-key and plaintext rejection, permissions,
  migrations, rekeying, publication recovery and archive reopening. The latest
  KDF change passed 13 targeted checks. The strength meter was checked
  offscreen in all three states.
- Process-kill tests recovered committed changes before and after archive
  replacement and preserved the working copy on a wrong key or archive conflict.
- Reproduced rejection of schema 18 by the installed schema-17 build with the
  correct password. The current build opens it and distinguishes unsupported
  schemas from archive locks. Twelve archive and vault tests passed, including
  unchanged archive bytes after a second open attempt.
- Real OpenSSH checks covered concurrent sessions, password and encrypted key
  authentication, Vim/mc, ProxyJump and forwarding. A passphrase-protected
  imported key worked after deleting its source file. A fresh login also
  succeeded with the key installed from an authenticated session. Ten local
  SFTP checks covered transfers, cancellation and cleanup.
- RDP login and text clipboard were verified on Linux Wayland against Windows
  Server 2008 R2. Untrusted-certificate rejection was checked over local TLS.
  The native harness passed AddressSanitizer with leak detection disabled
  before the final channel-loader change.
- Real local TCP peers verified Telnet negotiation, login modes, prompts,
  encoding and reconnect. Linux packaging checks covered installed native
  and pure Python wheels, launchers, dependency consistency and an ABI-3 build.
- Targeted Linux UI checks covered forms, credentials, lock/switch lifecycle
  and tree actions. English and Italian light/dark renders were inspected.
  Full regression coverage and cross-platform validation remain open.
- Offscreen Qt drag and drop checks moved a live loopback SSH session between
  workspace tabs and into a specific empty pane without reconnecting.
- Fixed the local PTY test launcher, which exited on OpenSSH options.
  Offscreen Qt checks verified that reconnect replaces a reordered tab in place
  and that a background process exit preserves the selected tab's status.
- The SSH context menu opens a file manager with remote directory refresh,
  navigation and selected-file downloads. Ten local SFTP tests passed.
- The SSH file manager adds icons, a file context menu, folder creation,
  rename and confirmed deletion. Eleven local OpenSSH/SFTP tests passed,
  including rename collision and nonempty folder protection.
- The SSH file manager shows the remote location above its toolbars and
  displays readable sizes, modification times and Unix permissions. Eleven
  local OpenSSH/SFTP tests passed, including the new location and metadata checks.
- The SSH file manager adds a remote places sidebar and directory history
  with themed toolbar buttons. Eleven local OpenSSH/SFTP tests passed.
- File manager buttons now show icons with translated tooltips and
  accessible names. Eleven local OpenSSH/SFTP tests passed.
- Verified that all ten SSH file manager toolbar icons fit on one row
  immediately below the location field in a Qt toolbar.
- Restored labels beside the icons in the remote places sidebar and
  verified the sidebar and toolbar button styles with Qt offscreen.
- The SSH file manager toolbar uses QActions shared with the context menu.
  Eleven local OpenSSH/SFTP tests passed.
- Refreshed the README screenshots and captured the SSH file manager
  with a real local OpenSSH/SFTP session and sample files.
