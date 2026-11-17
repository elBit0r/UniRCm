#!/usr/bin/env python3
"""Local dependency discovery; does not connect to remote hosts or start a GUI."""

import ctypes
from ctypes.util import find_library
from importlib.util import find_spec
import os
from pathlib import Path
import platform
import shutil
import sys


def main() -> int:
    print('UniRCm — Uni Remote Connection Manager — environment discovery')
    print('OS:', platform.platform())
    print('Python:', sys.version.split()[0])
    print('Display:', 'Wayland' if os.environ.get('WAYLAND_DISPLAY') else ('X11' if os.environ.get('DISPLAY') else 'No display detected'))
    print('Python modules:')
    for module in ('PyQt6', 'sqlcipher3', 'pyte', 'telnetlib3'):
        print(f'  {module}:', 'found' if find_spec(module) else 'not found')
    print('Executables:')
    for executable in ('ssh', 'sftp'):
        print(f'  {executable}:', shutil.which(executable) or 'not found')
    print('Optional VNC authentication library:')
    print('  LibVNCClient:', find_library('vncclient') or 'not found')
    print('Optional native RDP bridge:')
    package = find_spec('remote_manager')
    root = Path(package.origin).parent if package and package.origin else Path(__file__).resolve().parents[1] / 'src/remote_manager'
    bridge = root / 'protocols/native/librdp.so'
    print('  Path:', bridge)
    if bridge.is_file():
        try:
            library = ctypes.CDLL(str(bridge))
            library.urdp_abi_version.restype = ctypes.c_uint
            version = library.urdp_abi_version()
            print('  Status:', 'loadable (ABI 3)' if version == 3 else f'ABI mismatch ({version}; expected 3), rebuild required')
        except (OSError, AttributeError) as error:
            print('  Status: cannot load bridge:', error)
    else:
        print('  Status: not built; run python -m remote_manager.protocols.build_rdp')
    print('Optional RDP build tools:')
    for executable in ('cc', 'pkg-config'):
        print(f'  {executable}:', shutil.which(executable) or 'not found')
    print('\nNote: discovery does not establish functional protocol support or security.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
