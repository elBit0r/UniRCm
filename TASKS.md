# Development tasks

[PROJECT.md](PROJECT.md) defines product scope. [README.md](README.md) describes
current features.

## Open work

- [ ] Restore workspace layouts and splitter proportions across restarts.
- [ ] Extend terminal keyboard protocol and fullscreen application coverage.
- [ ] Review the native desktop UI at high DPI, including tree and workspace
  dragging, splitter gestures and terminal selection.
- [ ] Measure responsiveness and CPU usage with continuous terminal output.
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

- **Vault.** Verified Argon2id defaults, the legacy PBKDF2 upgrade, automatic
  encrypted backups and restore to a separate file. Key-file coverage includes
  required and incorrect files, password-only compatibility, rekey and
  recovery before and after archive publication.
- **SSH and SFTP.** Real loopback OpenSSH checks covered concurrent sessions,
  authentication, imported keys, forwarding, ProxyJump, reconnect and file
  transfers with cancellation. The file manager was verified against OpenSSH.
- **RDP.** Linux Wayland verified login and text clipboard with Windows Server
  2008 R2. Local checks covered certificate rejection. A live Ubuntu session
  verified Dynamic Display Control resize and clean disconnect.
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
