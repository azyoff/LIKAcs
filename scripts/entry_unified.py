"""PyInstaller entry point: unified LIKAcs.exe (mode chooser or --mode flag)."""

import sys
from pathlib import Path

try:
    from likacs.__main__ import main
except ModuleNotFoundError:  # running directly from a source checkout
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from likacs.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
