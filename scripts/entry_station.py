"""PyInstaller entry point: LIKAcs-StationAgent.exe."""

import sys
from pathlib import Path

try:
    from likacs.__main__ import main
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from likacs.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["--mode=station"]))
