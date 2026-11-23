# Architecture notes

The [project specification](../PROJECT.md#architecture) describes the intended architecture.
The current implementation uses:

- `ui`: PyQt6 widgets, connection editors and session workspaces; English/Italian
  translation is provided by `ui/language.py`.
- `storage`: SQLCipher vault, shared credentials, inheritance, archive
  backups, rekey recovery and optional key-file derivation.
- `terminal`: OpenSSH PTY sessions, private authentication IPC, SFTP, Telnet and
  terminal rendering.
- `protocols`: native FreeRDP/Qt and RFB/Qt viewers, plus shared desktop validation.
- `session.py`: protocol-independent session status.
