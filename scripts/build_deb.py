#!/usr/bin/env python3
"""Build a native Debian .deb without root or installation-time downloads.

Run on the Debian release/architecture being targeted, using its system Python.
Build prerequisites: python3-pip python3-setuptools python3-wheel python3-pyqt6
  dpkg-dev binutils (plus build-essential pkg-config freerdp3-dev for --with-rdp).
Example: /usr/bin/python3 scripts/build_deb.py --maintainer 'Name <email@example.org>'
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, **kwargs):
    return subprocess.run(list(args), check=True, **kwargs)


def write(path: Path, content: str, mode: int = 0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--maintainer', required=True, help='Debian Maintainer field: Name <email>')
    parser.add_argument('--revision', default='1', help='Debian package revision (default: 1)')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--with-rdp', action='store_true', help='Compile and include the native FreeRDP 3 bridge')
    parser.add_argument('--wheelhouse', type=Path, help='Offline wheel directory, including application build dependencies')
    args = parser.parse_args()
    if not re.fullmatch(r'[^<>\r\n]+ <[^<>\s]+@[^<>\s]+>', args.maintainer):
        parser.error('--maintainer must be Name <email>')
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~]*', args.revision):
        parser.error('invalid Debian revision')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'debian':
        parser.error('build on Debian itself (or in a Debian container/VM); cross-distribution builds are not supported')
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required')
    if Path(sys.prefix) != Path(sys.base_prefix):
        parser.error('use the target Debian system Python, not a virtual environment')
    for command in ('dpkg', 'dpkg-deb', 'dpkg-shlibdeps', 'readelf'):
        if not shutil.which(command):
            parser.error(f'missing {command}; install dpkg-dev and binutils')
    for module in ('pip', 'setuptools', 'wheel', 'PyQt6'):
        if importlib.util.find_spec(module) is None:
            parser.error(f'missing {module}; install the build prerequisites listed in --help')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    version = f'{project["version"]}-{args.revision}'
    arch = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
    python_minor = sys.version_info.minor
    network = ['--no-index', '--find-links', str(args.wheelhouse.resolve())] if args.wheelhouse else []
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='unircm-deb-') as temporary:
        work = Path(temporary)
        stage = work / 'package'
        private = stage / 'usr/lib/unircm'
        private.mkdir(parents=True)
        # Build from a clean copy: never ship a developer's existing native bridge.
        source = work / 'source'
        source.mkdir()
        for filename in ('pyproject.toml', 'setup.py', 'README.md', 'LICENSE', 'MANIFEST.in'):
            shutil.copy2(ROOT / filename, source / filename)
        shutil.copytree(ROOT / 'src', source / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so', '*.egg-info'))
        env = os.environ.copy()
        env.pop('UNIRCM_RDP_BRIDGE', None)
        env['UNIRCM_BUILD_RDP'] = '1' if args.with_rdp else '0'
        run(sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
            '--no-deps', '--no-build-isolation', '--target', str(private), *network, str(source), env=env)
        dependencies = [dep for dep in project['dependencies'] if not dep.startswith('PyQt6')]
        run(sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
            '--only-binary=:all:', '--target', str(private), *network, *dependencies)
        run(sys.executable, '-c',
            'import sys; sys.path.insert(0, sys.argv[1]); '
            'from sqlcipher3 import dbapi2; '
            'db = dbapi2.connect(":memory:"); '
            'assert db.execute("PRAGMA cipher_version").fetchone(), "SQLCipher unavailable"; '
            'db.close(); import pyte, telnetlib3', str(private))
        # pip's generated entry points carry the builder's paths; use our fixed launcher.
        shutil.rmtree(private / 'bin', ignore_errors=True)
        write(stage / 'usr/bin/unircm', '#!/usr/bin/python3\nimport sys\nsys.path.insert(0, "/usr/lib/unircm")\nfrom remote_manager.app import main\nraise SystemExit(main())\n', 0o755)
        write(stage / 'usr/share/applications/unircm.desktop', '[Desktop Entry]\nType=Application\nName=UniRCm\nComment=Remote connection manager\nExec=unircm\nIcon=unircm\nTerminal=false\nCategories=Network;RemoteAccess;\n')
        icon = stage / 'usr/share/icons/hicolor/256x256/apps/unircm.png'
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'src/remote_manager/ui/assets/unircm.png', icon)
        doc = stage / 'usr/share/doc/unircm'
        doc.mkdir(parents=True)
        shutil.copy2(ROOT / 'LICENSE', doc / 'LICENSE')
        shutil.copy2(ROOT / 'README.md', doc / 'README.md')
        write(doc / 'copyright', 'UniRCm application code: GPL-3.0-or-later.\nSee LICENSE for the complete GPLv3 terms.\nThird-party components retain their own licenses; see the bundled\n*.dist-info license files and remote_manager/ui/assets/papirus/LICENSE\nand SOURCES.json under /usr/lib/unircm.\n')
        # Derive native library constraints from the binaries actually shipped.
        write(work / 'debian/control', 'Source: unircm\nSection: net\nPriority: optional\nMaintainer: ' + args.maintainer + '\n\nPackage: unircm\nArchitecture: any\nDescription: Remote connection manager\n')
        binaries = sorted(private.rglob('*.so')) + sorted(private.rglob('*.so.*'))
        native_dependencies = ''
        if binaries:
            result = subprocess.check_output(['dpkg-shlibdeps', '-O',
                *[f'-l{directory}' for directory in sorted({str(p.parent) for p in binaries})],
                *[f'-e{binary}' for binary in binaries]], cwd=work, text=True)
            native_dependencies = next((line.split('=', 1)[1] for line in result.splitlines() if line.startswith('shlibs:Depends=')), '')
        depends = [f'python3 (>= 3.{python_minor})', f'python3 (<< 3.{python_minor + 1})',
                   'python3-pyqt6 (>= 6.6)', 'openssh-client']
        if native_dependencies:
            depends.append(native_dependencies)
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        write(stage / 'DEBIAN/control', f'Package: unircm\nVersion: {version}\nArchitecture: {arch}\nMaintainer: {args.maintainer}\nSection: net\nPriority: optional\nDepends: {", ".join(depends)}\nRecommends: libvncclient1\nInstalled-Size: {(size + 1023) // 1024}\nDescription: Uni Remote Connection Manager\n Encrypted connection profiles and shared credentials with real SSH sessions.\n')
        artifact = output / f'unircm_{version}_{arch}.deb'
        run('dpkg-deb', '--root-owner-group', '--build', str(stage), str(artifact))
        run('dpkg-deb', '--info', str(artifact))
        print(f'Built: {artifact}\nValidate installation and real sessions on a clean matching Debian system before release.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Build failed: {error}')
