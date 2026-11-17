# Platform compatibility / M0 evidence

Only mark a capability as supported after a real execution test. M0 remains incomplete.

| Platform | Display | Python/PyQt6 | SQLCipher binding | SSH terminal | FreeRDP | Status |
|---|---|---|---|---|---|---|
| Linux | xcb (X11 access within Wayland desktop) | Python 3.14.4; PyQt6/Qt 6.12.0 smoke passed | Absent | Untested | Absent | Qt only verified |
| Linux | Wayland | Python 3.14.4; PyQt6/Qt 6.12.0 smoke passed | Absent | Untested | Absent | Qt only verified |
| FreeBSD | X11 | Untested | Untested | Untested | Untested | Pending M0 |
| OpenBSD | X11 | Untested | Untested | Untested | Untested | Pending M0 |

For each real test, record: OS/version, Python, PyQt6/Qt, display server, packages, build/install steps, backend binary/API versions, observed result and limitations. `scripts/doctor.py` performs **discovery only**; its output is not proof of protocol compatibility.


## Linux Qt validation — 2026-11-13

Host: Ubuntu 26.04.1 LTS, x86_64, kernel 7.0.0-43-generic,
glibc 2.43, Python 3.14.4. Installed existing declared dependencies with
`.venv/bin/python -m pip install -e '.[dev]'`: PyQt6 6.12.0,
Qt runtime/compiled 6.12.0, PyQt6-sip 13.13.1, pytest 9.2.0, pytest-qt 4.5.0.
No dependency manifest changes. `pip check` passed.

Verified commands (desktop tests require execution outside the sandbox):

- `QT_QPA_PLATFORM=wayland .venv/bin/python -m pytest -s`: **3 passed**;
  Qt reported `wayland`.
- `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -s`: **3 passed**;
  Qt reported `xcb`. This is X11 access on the current Wayland desktop;
  a separate native Xorg session is untested.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`: **3 passed**;
  headless regression check only.

The GUI tests create the actual MainWindow, show it, wait for exposure and
verify a Qt timer callback is processed. Human visual inspection, prolonged
interaction and full application entry-point lifecycle remain untested.
Sandboxed default Qt startup aborted (exit 134); the same environment could
access desktop backends with sandbox restrictions lifted. Initial dependency
download also required network access outside the sandbox.

`.venv/bin/python scripts/doctor.py` completed: OpenSSH is present;
SQLCipher bindings/CLI and all probed FreeRDP binaries are absent. No terminal
backend or protocol session was validated. BSD installation/build/runtime,
native Xorg and protocol adapters remain untested and undecided. Next focused
M0 task: SQLCipher binding and encrypted-at-rest PoC.
