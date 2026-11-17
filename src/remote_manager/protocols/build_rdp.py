"""Build the optional ctypes bridge using the host's FreeRDP 3 development files."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile


def build_bridge(source=None, destination=None):
    source = Path(source) if source else Path(__file__).with_name('native') / 'rdp.c'
    destination = Path(destination) if destination else source.with_name('librdp.so')
    flags = subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'freerdp-client3', 'freerdp3', 'winpr3'], text=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.so', delete=False) as output:
        temporary = Path(output.name)
    try:
        subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-shared', '-fPIC', '-O2', '-Wall', '-pthread',
                        str(source), '-o', str(temporary), *shlex.split(flags)], check=True)
        temporary.chmod(0o755)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    try:
        path = build_bridge()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit('Cannot build RDP bridge: install a C compiler, pkg-config and FreeRDP 3 development libraries.') from error
    print(f'Built native FreeRDP 3 backend: {path}')


if __name__ == '__main__':
    main()
