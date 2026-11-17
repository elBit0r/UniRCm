# Development Tasks

Updated 2026-11-17. [PROJECT.md](PROJECT.md) defines product scope.

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
- [ ] Select a Debian release and architecture, then build and install the
  `.deb` on Debian. The builder is implemented. Ubuntu checks covered syntax,
  help and rejection of non-Debian builds.
- [ ] Review distribution dependencies and bundled artwork obligations.
  The project license is GPL-3.0-or-later.
- [ ] Validate FreeBSD builds and runtime, and check manylinux portability.

## Current functionality

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
  and detach.
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
