# Security decisions

- All saved connection metadata and secrets must be encrypted at rest with **SQLCipher 4**.
- A master password is required to unlock each vault. A portable `.uni` archive
  can also require a key file. UniRCm combines the password KDF output with a
  SHA-256 digest of the file using HKDF-SHA-256. The public archive metadata
  records whether the key file is required. Its path, contents and digest are
  kept out of the archive and backups.
- **Generate new key file** creates 32 random bytes with mode `0600`. Keep a
  separate copy of the exact bytes. A renamed or copied file works if its
  contents are identical.
- Adding, replacing or removing a key file creates a verified encrypted backup
  before rekeying. To restore that backup, use the master password and any key
  file that were valid when it was made. Losing a required file prevents
  unlocking both the archive and backups that require it. Key-file archives
  require a UniRCm version that supports the key-file format.
- Fail closed if the SQLCipher driver is absent or the key is invalid.
- Never persist an unencrypted shadow copy, plaintext backup, secret in logs, or passwords in process arguments.
- Preserve SSH host-key and RDP/TLS certificate validation; Telnet remains a plaintext transport.
- Locked state must close DB handles and disconnect remote sessions by default.
- Protect files and directories with restrictive Unix permissions.
- Python memory cannot be assumed securely zeroized.

See the [project security requirements](../PROJECT.md#security) and [encrypted storage requirements](../PROJECT.md#encrypted-storage).
