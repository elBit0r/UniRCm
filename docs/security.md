# Security decisions

- All saved connection metadata and secrets must be encrypted at rest with **SQLCipher 4**.
- A master password is required on every launch; avoid secondary custom cryptographic designs.
- Fail closed if the SQLCipher driver is absent or the key is invalid.
- Never persist an unencrypted shadow copy, plaintext backup, secret in logs, or passwords in process arguments.
- Preserve SSH host-key and RDP/TLS certificate validation; Telnet remains a plaintext transport.
- Locked state must close DB handles and disconnect remote sessions by default.
- Protect files and directories with restrictive Unix permissions.
- Python memory cannot be assumed securely zeroized.

See the [project security requirements](../PROJECT.md#security) and [encrypted storage requirements](../PROJECT.md#encrypted-storage).
