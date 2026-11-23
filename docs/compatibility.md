# Platform compatibility

| Environment | Verified | Still open |
|---|---|---|
| Ubuntu 26.04.1 amd64 | Qt on Wayland and XWayland, SQLCipher vault, loopback OpenSSH and SFTP, RDP login and clipboard on Wayland | Native Xorg, wider server and desktop coverage |
| Debian 13 amd64 | Package installation and launcher startup in an isolated environment with Qt offscreen | Interactive desktop and real sessions |
| FreeBSD | Intended target | Build, installation and runtime |
| OpenBSD | Deferred | Build, installation and runtime |

Telnet has been checked with local peers. The experimental VNC viewer has
been checked with an RFB test server. Authenticated rendering and input on a
real VNC server still need validation.

[Development tasks](../TASKS.md) records protocol and packaging checks.
`scripts/doctor.py` reports which runtime dependencies are available.
