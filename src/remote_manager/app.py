"""Start with the encrypted database locked; no profiles load before unlock."""
import os
from pathlib import Path
import sys

from . import APP_NAME, APP_SHORT_NAME


def main() -> int:
    from PyQt6.QtCore import QStandardPaths
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication
    from .ui.databases import DatabaseChooser
    from .ui.main_window import MainWindow

    os.umask(0o077)
    app = QApplication(sys.argv)
    app.setDesktopFileName('unircm')
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'ui' / 'assets' / 'unircm.png')))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName('UnixRemoteManager')
    # Closing startup/lock dialogs must not schedule app exit on successful unlock.
    app.setQuitOnLastWindowClosed(False)
    path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / 'unircm' / 'connections.db'
    app.setApplicationDisplayName(APP_SHORT_NAME)
    chooser = DatabaseChooser(path)
    if not chooser.exec():
        return 0
    window = MainWindow(chooser.vault, chooser.path,
                        allow_startup_connections=chooser.allow_startup_connections)
    window.show()
    app.setQuitOnLastWindowClosed(True)
    return app.exec()
