"""Run the application directly from the source checkout or from PyCharm."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from remote_manager.app import main

if __name__ == '__main__':
    raise SystemExit(main())
