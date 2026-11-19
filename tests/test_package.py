from remote_manager import __version__


def test_version_declared() -> None:
    assert __version__ == "0.1.1"


def test_installed_metadata_and_launchers():
    from importlib.metadata import distribution
    package = distribution('unix-remote-manager')
    assert package.version == __version__
    launchers = {entry.name: entry.value for entry in package.entry_points if entry.group == 'console_scripts'}
    assert launchers['unircm'] == 'remote_manager.app:main'
    assert launchers['unix-remote-manager'] == launchers['unircm']
    assert 'sqlcipher3-binary==0.6.0' in package.requires


def test_packaged_native_source_and_icon_notices():
    from importlib.resources import files
    source = files('remote_manager.protocols').joinpath('native/rdp.c')
    assert 'urdp_abi_version' in source.read_text()
    for header in ('pointer.h', 'clipboard.h'):
        assert files('remote_manager.protocols').joinpath('native', header).is_file()
    assets = files('remote_manager.ui').joinpath('assets/papirus')
    assert assets.joinpath('LICENSE').is_file()
    assert assets.joinpath('SOURCES.json').is_file()
    assert len(list(assets.iterdir())) > 2
