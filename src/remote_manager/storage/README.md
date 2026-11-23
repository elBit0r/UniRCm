# Encrypted storage

`vault.py` manages SQLCipher configuration, schema migrations and shared
credentials. `archive.py` manages portable archives, verified backups and
rekey recovery. `kdf.py` implements Argon2id and optional key-file derivation.

See [the security notes](../../../docs/security.md) for key file and backup
requirements.
