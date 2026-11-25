# Development tasks

[PROJECT.md](PROJECT.md) defines product scope. [README.md](README.md) describes
current features.

## Open work

- [ ] Restore workspace layouts and splitter proportions across restarts.
- [ ] Extend terminal keyboard protocol and fullscreen application coverage.
- [ ] Review the native desktop UI at high DPI, including tree and workspace
  dragging, splitter gestures and terminal selection.
- [ ] Measure responsiveness and CPU usage with continuous terminal output.
- [ ] Evaluate bounded SFTP request pipelining and verify cancellation.
- [ ] Verify remote RDP mouse wheel input, visual options, administrative
  sessions and changed-certificate acceptance limited to the active session.
- [ ] Verify Telnet login against a real router or switch.
- [ ] Verify authenticated VNC rendering and input on a real server.
- [ ] Verify the Debian 13 amd64 package in an interactive desktop session.
- [ ] Run the Docker/Podman package build end to end and review distribution
  dependencies and artwork obligations.
- [ ] Validate FreeBSD builds and runtime and assess manylinux portability.

## Current limits

- SFTP directory recursion and shell-directory tracking are unsupported.
  Connectivity or permissions can prevent cleanup of a cancelled upload.
- RDP clipboard sharing supports only text. Pointer warping is unsupported.
- Experimental VNC supports RFB 3.8, classic password authentication, raw
  frames, resize, scaling, keyboard and mouse input and view-only mode.
  TLS, clipboard, fullscreen and additional encodings are deferred.

## Recorded verification

- **Legacy vault and SFTP.** Linux tests verified shared directory permissions
  with both valid and invalid vault passwords. Loopback OpenSSH verified upload
  success with a listing warning and download success without a listing request.
  A 1 MiB loopback transfer with 100 ms of added wait per data request measured
  315 KiB/s upload and 306 KiB/s download.

- **SSH Unicode.** A real session to `172.16.10.213` in the Linux embedded
  terminal displayed the pre-authentication banner and the full weather line.
  An offscreen Qt check verified color emoji rendering.

- **Quick Connect.** Linux Qt checks covered the toolbar, protocol default
  ports, the View toggle, encrypted visibility persistence and vault locking.
  The controls stay left-aligned at fixed widths when the window grows.
  A real OpenSSH loopback connection verified sign-in without saving a profile.
- **Toolbar.** Linux Qt checks covered large, compact and hidden modes,
  tooltips in compact mode, Italian labels and restoration from the encrypted vault.
  The Connect action uses a green plug, gold pins and a blue socket in the menu
  and toolbar.
- **Vault.** Verified Argon2id defaults, the legacy PBKDF2 upgrade, automatic
  encrypted backups and restore to a separate file. Key-file coverage includes
  required and incorrect files, password-only compatibility, rekey and
  recovery before and after archive publication.
- **Unlock UI.** Verified key file controls and the password checkbox stay
  separate in the scrollable Linux desktop chooser. Verified per-database
  path prefill, clearing and removal with an encrypted archive.
- **SSH and SFTP.** Real loopback OpenSSH checks covered concurrent sessions,
  authentication, imported keys, forwarding, ProxyJump, reconnect and file
  transfers with cancellation. The file manager was verified against OpenSSH.
- **RDP.** Linux Wayland verified login and text clipboard with Windows Server
  2008 R2. Local checks covered certificate rejection. A live Ubuntu session
  verified Dynamic Display Control resize and clean disconnect.
  Local Qt tests verified credential prompts, cancellation on reconnect, and
  encrypted persistence of the authentication mode without saving prompt input.
- **Shared connection authentication.** Edit Connection now configures saved
  credentials and connection-time prompts for SSH, Telnet, RDP and VNC.
  Linux checks covered SQLCipher, the RDP prompt, loopback OpenSSH key
  authentication, Telnet login and VNC challenge-response.
- **Telnet and VNC.** Local TCP peers verified Telnet negotiation and login.
  VNC has wire-fixture checks for authentication, framebuffer updates and
  input, including resize and scrolling.
- **Packaging and UI.** The 0.2.0 amd64 packages were built for Debian 13 and
  Ubuntu 26.04. Debian launched with Qt offscreen in an isolated environment.
  Ubuntu passed APT upgrade simulation. Both loaded the FreeRDP 3 bridge.
  Linux UI checks covered credential forms, lock/switch, drag and drop and
  English and Italian rendering.
- **Pre-release review.** Passed 47 targeted Linux tests across vault, VNC,
  the Qt UI and workspace sessions. Checked the built-in help in English
  and Italian.
- **0.2.2 packages.** Built Debian 13 and Ubuntu 26.04 amd64 packages and
  verified both checksums. In isolated environments, APT simulation, Qt
  startup, native FreeRDP context creation and Argon2id key-file backup
  and restore passed.
- **0.2.3 packages.** Built Debian 13 and Ubuntu 26.04 amd64 packages and
  verified SHA-256 checksums, APT install simulation, Qt startup, the native
  FreeRDP bridge and encrypted archive backup and restore. Passed 14 targeted
  package and security settings tests.
- **PTY output.** Removed the fixed read delay and redundant repaints. Local
  shell benchmark with 96,000 bytes of terminal output improved from 1.16 s
  to 0.33 s median over five runs. All 28 screen and selection tests passed.
- **Local connection commands.** Added single-line commands before connecting
  and after disconnecting, stored in SQLCipher. Verified both commands with
  loopback SSH, Telnet and a VNC protocol fixture, including closing the VNC
  tab. A refused RDP connection ran only the before command. A successful RDP
  session still needs a live-server check.
- **Before-connection command errors.** Added Continue, Cancel and Retry to
  the error dialog. Verified that all three choices control transport startup.
- **SSH startup commands.** Added per-profile multiline commands stored in
  SQLCipher. Verified execution in a real loopback SSH shell, continued
  interactive use, and no command input after failed authentication.
- **tmux over SSH.** Fixed a terminal crash on DEC private cursor position
  queries and suppressed the incorrect primary reply to secondary device
  attributes queries. Verified tmux 3.6 startup, first command and return
  to the shell over loopback SSH.
- **Midnight Commander borders.** Enabled DEC line drawing in UTF-8 terminal
  streams. Verified panel borders and return to the shell over loopback SSH
  with Midnight Commander running under the C locale.
- **SSH animation output.** Reduced processing time for 500 kB of captured
  `aafire` output from 1.16 s to 0.67 s with identical screen and cursor state.
  Verified return to the shell after Ctrl+C on `unirc` using a copy of the
  encrypted test archive. All 37 terminal screen and selection tests passed.
- **0.2.4 packages.** Built Debian 13 and Ubuntu 26.04 amd64 packages.
  APT upgrade simulation, Qt offscreen startup, FreeRDP bridge initialization,
  and encrypted archive backup and restore passed in both build environments.
