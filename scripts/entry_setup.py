"""PyInstaller entry point: LIKAcs-Setup.exe (installer / uninstaller)."""

import sys
from pathlib import Path

try:
    from likacs.installer import main
except ModuleNotFoundError:  # running directly from a source checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from likacs.installer import main

if __name__ == "__main__":
    sys.exit(main())
