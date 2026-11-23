# Development installation

On Linux, install Python, virtualenv and the Argon2 runtime library (`libargon2-1` on Debian and Ubuntu):

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

With Docker or Podman available, run from the repository root to build both packages:

```sh
python3 scripts/build_deb.py
```

The script uses separate Debian 13 and Ubuntu 26.04 LTS containers, installs build
dependencies in them, and saves both packages in `dist/`. It needs network access
for the container images and dependencies. The maintainer is set by default.

To build a single package natively, use the corresponding distribution and its
system Python. Install the build prerequisites on that system:

```sh
sudo apt install python3-pip python3-setuptools python3-wheel dpkg-dev binutils \
  build-essential pkg-config freerdp3-dev zlib1g-dev
```

| Build environment | Target flag | Example amd64 output |
| --- | --- | --- |
| Debian 13 with Python 3.13 | `--target debian13` | `dist/unircm_0.2.0-1+debian13_amd64.deb` |
| Ubuntu 26.04 LTS with Python 3.14 | `--target ubuntu26.04` | `dist/unircm_0.2.0-1+ubuntu26.04_amd64.deb` |

```sh
/usr/bin/python3 scripts/build_deb.py --target debian13
```

The native build itself does not require root.
Qt and OpenSSH are system dependencies; other Python dependencies are bundled
privately, including SQLCipher (never a plaintext SQLite fallback). Building
requires package-index access, or `--wheelhouse /path/to/wheels` for offline use.
If SQLCipher has no compatible binary wheel for the build interpreter/architecture,
the build fails rather than substituting SQLite. Native runtime dependencies are
computed with `dpkg-shlibdeps`; the package requires the builder's Python minor version.

The packages include SSH and the native FreeRDP 3 bridge by default. APT
installs the FreeRDP runtime libraries when you install the package. Use
`--without-rdp` only for a build without embedded RDP support. A compiler and
pip are needed only on the build system.
Use `sudo apt install ./dist/unircm_VERSION_ARCH.deb` on a matching Debian or
Ubuntu system. Validate real desktop sessions on the target and complete the
third-party license review before public release.

**BSD:** test native Python/PyQt6 package installations and the SQLCipher/FreeRDP build independently. Do not infer package availability from Linux pip behavior.
