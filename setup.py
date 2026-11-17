"""Optional platform wheel containing a FreeRDP bridge; default wheels are pure Python."""
import ctypes
import importlib.util
import os
from pathlib import Path
import shutil

from setuptools import Distribution, setup
from setuptools.command.build_py import build_py
from setuptools.command.bdist_wheel import bdist_wheel

ROOT = Path(__file__).parent
PREBUILT = os.environ.get('UNIRCM_RDP_BRIDGE')
NATIVE = os.environ.get('UNIRCM_BUILD_RDP') == '1' or bool(PREBUILT)


class PackageDistribution(Distribution):
    def has_ext_modules(self):
        return NATIVE


class BuildPy(build_py):
    def run(self):
        super().run()
        destination = Path(self.build_lib) / 'remote_manager/protocols/native/librdp.so'
        # Never reuse a binary left by a previous build for a pure wheel.
        destination.unlink(missing_ok=True)
        if not NATIVE:
            return
        if PREBUILT:
            source = Path(PREBUILT).resolve(strict=True)
        else:
            spec = importlib.util.spec_from_file_location('build_rdp', ROOT / 'src/remote_manager/protocols/build_rdp.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            source = module.build_bridge(destination=destination)
        lib = ctypes.CDLL(str(source.resolve()))
        lib.urdp_abi_version.restype = ctypes.c_uint
        if lib.urdp_abi_version() != 3:
            raise RuntimeError('RDP bridge ABI mismatch; rebuild from the packaged source.')
        if source != destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


class Wheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        if NATIVE:
            self.root_is_pure = False

    def get_tag(self):
        python, abi, platform = super().get_tag()
        # The bridge uses ctypes, with no CPython ABI dependency.
        return ('py3', 'none', platform) if NATIVE else (python, abi, platform)


setup(distclass=PackageDistribution, cmdclass={'build_py': BuildPy, 'bdist_wheel': Wheel})
