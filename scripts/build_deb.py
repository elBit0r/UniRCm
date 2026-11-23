#!/usr/bin/env python3
"""Build the Debian 13 and Ubuntu 26.04 LTS packages in dist/.

Run without arguments to build both with Docker or Podman and network access.
Use --target for a native build on the matching distribution with /usr/bin/python3.
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
MAINTAINER = 'victor <victor@unirc.eu>'
TARGETS = {
    'debian13': ('debian', '13', 13),
    'ubuntu26.04': ('ubuntu', '26.04', 14),
}
IMAGES = {
    'debian13': 'docker.io/library/debian:13',
    'ubuntu26.04': 'docker.io/library/ubuntu:26.04',
}
BUILD_DEPENDENCIES = ('python3-pip', 'python3-setuptools', 'python3-wheel', 'dpkg-dev', 'binutils')


def run(*args: str, **kwargs):
    return subprocess.run(list(args), check=True, **kwargs)


def write(path: Path, content: str, mode: int = 0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def build_all(engine: str, args: argparse.Namespace) -> None:
    dependencies = BUILD_DEPENDENCIES
    if args.with_rdp:
        dependencies += ('build-essential', 'pkg-config', 'freerdp3-dev', 'zlib1g-dev')
    output = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix='unircm-debs-') as temporary:
        staging = Path(temporary)
        packages = []
        for target, image in IMAGES.items():
            command = [engine, 'run', '--rm', '--env', 'DEBIAN_FRONTEND=noninteractive',
                       '--volume', f'{ROOT}:/source:ro', '--volume', f'{staging}:/packages']
            build = ['/usr/bin/python3', '/source/scripts/build_deb.py', '--target', target,
                     '--maintainer', args.maintainer, '--revision', args.revision, '--output', '/packages']
            if not args.with_rdp:
                build.append('--without-rdp')
            if args.wheelhouse:
                command += ['--volume', f'{args.wheelhouse.resolve()}:/wheels:ro']
                build += ['--wheelhouse', '/wheels']
            print(f'Building {target} in {image}', flush=True)
            run(*command, image, '/bin/sh', '-ec',
                f'apt-get update\napt-get install -y --no-install-recommends ca-certificates {" ".join(dependencies)}\nexec "$@"',
                'build_deb', *build)
            matches = list(staging.glob(f'unircm_*+{target}_*.deb'))
            if len(matches) != 1:
                raise OSError(f'expected one .deb for {target}, found {len(matches)}')
            packages.extend(matches)
        output.mkdir(parents=True, exist_ok=True)
        for package in packages:
            destination = output / package.name
            with tempfile.NamedTemporaryFile(dir=output, prefix='.unircm-', delete=False) as staged:
                staged_path = Path(staged.name)
            try:
                shutil.copyfile(package, staged_path)
                staged_path.chmod(0o644)
                staged_path.replace(destination)
            finally:
                staged_path.unlink(missing_ok=True)
            print(f'Built: {destination}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--target', choices=TARGETS, help='Build one package natively (default: build both in containers)')
    parser.add_argument('--maintainer', default=MAINTAINER, help='Override the package maintainer (Name <email>)')
    parser.add_argument('--revision', default='1', help='Debian package revision (default: %(default)s)')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    rdp = parser.add_mutually_exclusive_group()
    rdp.add_argument('--with-rdp', action='store_true', default=True, help='Include the native FreeRDP 3 bridge (default)')
    rdp.add_argument('--without-rdp', action='store_false', dest='with_rdp', help='Build without embedded RDP support')
    parser.add_argument('--wheelhouse', type=Path, help='Offline wheel directory, including application build dependencies')
    args = parser.parse_args()
    if not re.fullmatch(r'[^<>\r\n]+ <[^<>\s]+@[^<>\s]+>', args.maintainer):
        parser.error('--maintainer must be Name <email>')
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~]*', args.revision):
        parser.error('invalid Debian revision')
    if args.target is None:
        engine = shutil.which('docker') or shutil.which('podman')
        if engine is None:
            parser.error('Docker or Podman is required to build both packages')
        build_all(engine, args)
        return 0

    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    host_release = (release.get('ID', '').strip('"'), release.get('VERSION_ID', '').strip('"'))
    target = args.target
    distro, version_id, python_minor = TARGETS[target]
    if host_release != (distro, version_id):
        parser.error(f'--target {target} requires its matching build environment; found {" ".join(host_release)}')
    if Path(sys.prefix) != Path(sys.base_prefix) or not Path(sys.executable).samefile('/usr/bin/python3'):
        parser.error('use the target system interpreter /usr/bin/python3')
    if sys.version_info[:2] != (3, python_minor):
        parser.error(f'{target} requires Python 3.{python_minor}')
    for command in ('dpkg', 'dpkg-deb', 'dpkg-shlibdeps', 'readelf'):
        if not shutil.which(command):
            parser.error(f'missing {command}; install dpkg-dev and binutils')
    for module in ('pip', 'setuptools', 'wheel'):
        if importlib.util.find_spec(module) is None:
            parser.error(f'missing {module}; install the build prerequisites listed in --help')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    version = f'{project["version"]}-{args.revision}+{target}'
    arch = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
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
        write(stage / 'usr/share/applications/unircm.desktop', '[Desktop Entry]\nType=Application\nName=UniRCm\nComment=Remote connection manager\nExec=unircm\nIcon=unircm\nStartupWMClass=Uni Remote Connection Manager\nTerminal=false\nCategories=Network;RemoteAccess;\n')
        icon = stage / 'usr/share/icons/hicolor/256x256/apps/unircm.png'
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'src/remote_manager/ui/assets/unircm.png', icon)
        doc = stage / 'usr/share/doc/unircm'
        doc.mkdir(parents=True)
        shutil.copy2(ROOT / 'LICENSE', doc / 'LICENSE')
        shutil.copy2(ROOT / 'README.md', doc / 'README.md')
        write(doc / 'copyright', 'UniRCm application code: GPL-3.0-or-later.\nSee LICENSE for the complete GPLv3 terms.\nThird-party components retain their own licenses; see the bundled\n*.dist-info license files and remote_manager/ui/assets/papirus/LICENSE\nand SOURCES.json under /usr/lib/unircm.\n')
        # Derive native library constraints from the binaries actually shipped.
        # Mark the staging root so dpkg-shlibdeps recognizes bundled libraries
        # (such as SQLCipher's libcrypto) as part of this same package.
        (stage / 'DEBIAN').mkdir()
        write(work / 'debian/control', 'Source: unircm\nSection: net\nPriority: optional\nMaintainer: ' + args.maintainer + '\n\nPackage: unircm\nArchitecture: any\nDescription: Remote connection manager\n')
        binaries = sorted(private.rglob('*.so')) + sorted(private.rglob('*.so.*'))
        native_dependencies = ''
        if binaries:
            result = subprocess.check_output(['dpkg-shlibdeps', '-O',
                *[f'-l{directory}' for directory in sorted({str(p.parent) for p in binaries})],
                *[f'-e{binary}' for binary in binaries]], cwd=work, text=True)
            native_dependencies = next((line.split('=', 1)[1] for line in result.splitlines() if line.startswith('shlibs:Depends=')), '')
        depends = [f'python3 (>= 3.{python_minor})', f'python3 (<< 3.{python_minor + 1})',
                   'python3-pyqt6 (>= 6.6)', 'python3-pyqt6.qtsvg', 'openssh-client', 'libargon2-1']
        if native_dependencies:
            depends.append(native_dependencies)
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        write(stage / 'DEBIAN/control', f'Package: unircm\nVersion: {version}\nArchitecture: {arch}\nMaintainer: {args.maintainer}\nSection: net\nPriority: optional\nDepends: {", ".join(depends)}\nRecommends: libvncclient1\nInstalled-Size: {(size + 1023) // 1024}\nDescription: Uni Remote Connection Manager\n Encrypted connection profiles and shared credentials with real SSH sessions.\n')
        artifact = output / f'unircm_{version}_{arch}.deb'
        run('dpkg-deb', '--root-owner-group', '--build', str(stage), str(artifact))
        run('dpkg-deb', '--info', str(artifact))
        print(f'Built: {artifact}\nValidate installation and real sessions on a clean {target} system before release.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Build failed: {error}')
