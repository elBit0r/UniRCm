# Encrypted storage

**SQLCipher only**. Plain `sqlite3` must never be used to persist application configuration or secrets.

Choose and validate native SQLCipher bindings in M0 before writing database code. Fail closed when SQLCipher is unavailable; do not silently create a plaintext database.
