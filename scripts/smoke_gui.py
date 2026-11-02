"""Build every LIKAcs window against a real Tk root (Windows CI guard).

Run on a Windows runner:

    python scripts/smoke_gui.py

This constructs the mode chooser, About dialog, Control Center and Station
Agent — including every ttk widget class and style — so a bad Tk option or
font string fails CI before any .exe is published. Import-only checks cannot
catch this class of bug: v1.0.1 shipped an unbraced "Segoe UI 10" font that
crashed on the first ttk.Label while all import checks passed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from likacs.ui.smoke import run_gui_smoke  # noqa: E402


if __name__ == "__main__":
    sys.exit(run_gui_smoke())
