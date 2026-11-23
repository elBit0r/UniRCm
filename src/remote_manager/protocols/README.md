# Protocol backends

SSH runs OpenSSH in a PTY. Telnet uses telnetlib3. The embedded desktop
backends use FreeRDP 3 for RDP and an experimental RFB viewer for VNC.
All protocols use credentials resolved by the encrypted vault.

See [the project specification](../../../PROJECT.md#protocols) for scope and
transport requirements.
