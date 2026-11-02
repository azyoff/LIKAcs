"""Build standalone Windows 10/11 .exe files with PyInstaller.

Usage:
    python scripts/build.py             # all three exes + SHA256SUMS.txt
    python scripts/build.py --quick     # unified LIKAcs.exe only (CI smoke build)

No runtime dependencies: the produced .exe embeds CPython 3.11, Tkinter and
the LIKAcs standard-library-only package. Cafe PCs need no Python or Node.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPECS = BUILD / "specs"
ICON = ROOT / "assets" / "lika.ico"

TARGETS = [
    ("LIKAcs", "scripts/entry_unified.py"),
    ("LIKAcs-ControlCenter", "scripts/entry_control.py"),
    ("LIKAcs-StationAgent", "scripts/entry_station.py"),
]

# Imports that happen inside functions/threads are invisible to PyInstaller's
# static analysis, so list them explicitly.
HIDDEN_IMPORTS = [
    "likacs.selftest",
    "likacs.setup_windows",
    "likacs.ui.about",
    "likacs.ui.control_center",
    "likacs.ui.mode_chooser",
    "likacs.ui.smoke",
    "likacs.ui.station_agent",
    "likacs.ui.theme",
    "likacs.ui.widgets",
    "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.simpledialog",
    "winreg",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_icon() -> None:
    sys.path.insert(0, str(SRC))
    from likacs.icon import ico_bytes
    ICON.parent.mkdir(parents=True, exist_ok=True)
    ICON.write_bytes(ico_bytes())


def build_one(name: str, entry: str) -> Path:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed", "--clean", "--noconfirm",
        "--name", name,
        "--icon", str(ICON),
        "--paths", str(SRC),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / name),
        "--specpath", str(SPECS),
    ]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    command.append(str(ROOT / entry))
    print(f"\n=== Building {name}.exe ===", flush=True)
    subprocess.run(command, check=True, cwd=str(ROOT))
    output = DIST / f"{name}.exe"
    if not output.is_file():
        raise SystemExit(f"PyInstaller did not produce {output}")
    print(f"{output} ({output.stat().st_size:,} bytes)")
    return output


def write_checksums(files: list[Path]) -> Path:
    target = DIST / "SHA256SUMS.txt"
    lines = []
    for path in files:
        if path.is_file():
            lines.append(f"{sha256(path)}  {path.name}\n")
    target.write_text("".join(lines), encoding="utf-8")
    print(f"\nWrote {target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build LIKAcs Windows executables")
    parser.add_argument("--quick", action="store_true", help="build only the unified exe")
    args = parser.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is required: python -m pip install -r requirements-build.txt",
              file=sys.stderr)
        return 2

    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    SPECS.mkdir(parents=True, exist_ok=True)
    ensure_icon()

    targets = TARGETS[:1] if args.quick else TARGETS
    built = [build_one(name, entry) for name, entry in targets]
    for extra in (ROOT / "README.md", ROOT / "LICENSE"):
        if extra.is_file():
            built.append(extra)
    write_checksums(built)
    print("\nRelease artifacts:")
    for path in DIST.iterdir():
        if path.is_file():
            print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
