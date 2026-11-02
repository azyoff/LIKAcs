"""Generate assets/lika.ico (used as the .exe and system tray icon)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from likacs.icon import ico_bytes  # noqa: E402


def main() -> int:
    target = ROOT / "assets" / "lika.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ico_bytes())
    print(f"Wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
