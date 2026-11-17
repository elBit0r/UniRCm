# Development installation

On Linux with Python and virtualenv available:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/doctor.py
python -m pytest -q
python -m remote_manager
```

For automated GUI smoke tests in a headless Linux CI environment, set `QT_QPA_PLATFORM=offscreen` (actual desktop integration still requires a graphical session).

## Debian package build

Build on the intended Debian release and architecture with its system Python:

```sh
sudo apt install python3-pip python3-setuptools python3-wheel python3-pyqt6 dpkg-dev binutils
/usr/bin/python3 scripts/build_deb.py --maintainer 'Your Name <you@example.org>'
```

The build itself does not require root. Output is `dist/unircm_VERSION_ARCH.deb`.
Qt and OpenSSH are system dependencies; other Python dependencies are bundled
privately, including SQLCipher (never a plaintext SQLite fallback). Building
requires package-index access, or `--wheelhouse /path/to/wheels` for offline use.
If SQLCipher has no compatible binary wheel for the build interpreter/architecture,
the build fails rather than substituting SQLite. Native runtime dependencies are
computed with `dpkg-shlibdeps`; the package requires the builder's Python minor version.

SSH is included by default. To include the RDP bridge, also install
`build-essential pkg-config freerdp3-dev` and pass `--with-rdp`.
No compiler or pip invocation runs during package installation or application startup.
Use `sudo apt install ./dist/unircm_VERSION_ARCH.deb` on a clean matching Debian
system to validate the resulting package. Debian installation/runtime validation
and the third-party license review remain required before public release.

**BSD:** test native Python/PyQt6 package installations and the SQLCipher/FreeRDP build independently. Do not infer package availability from Linux pip behavior.
