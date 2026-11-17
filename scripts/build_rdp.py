#!/usr/bin/env python3
"""Build the optional native RDP bridge in a source checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from remote_manager.protocols.build_rdp import main

if __name__ == '__main__':
    main()
