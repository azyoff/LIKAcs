"""Build standalone Windows 10/11 .exe files with PyInstaller.

Usage:
    python scripts/build.py             # all exes + SHA256SUMS.txt + latest.json
    python scripts/build.py --quick     # LIKAcs.exe only (CI smoke build)
    python scripts/build.py --tag v1.1.0

Published to GitHub Releases: ONE user-facing exe, ``LIKAcs.exe``. On first
run it shows the Setup wizard and installs itself per-user (no UAC). On later
runs it is the app. ``LIKAcs-Setup.exe`` is an OPTIONAL workflow artifact for
silent cafe deployment (``--silent --autostart``); it embeds LIKAcs.exe.

No runtime dependencies: each .exe embeds CPython 3.11, Tkinter and the
standard-library-only LIKAcs package. Cafe PCs need no Python or Node.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPECS = BUILD / "specs"
ICON = ROOT / "assets" / "lika.ico"
SETUP_NAME = "LIKAcs-Setup"

sys.path.insert(0, str(SRC))
from likacs import VERSION  # noqa: E402

TARGETS = [
    ("LIKAcs", "scripts/entry_unified.py"),
    ("LIKAcs-ControlCenter", "scripts/entry_control.py"),
    ("LIKAcs-StationAgent", "scripts/entry_station.py"),
]

# Imports that happen inside functions/threads are invisible to PyInstaller's
# static analysis, so list them explicitly.
HIDDEN_IMPORTS = [
    "likacs.installer",
    "likacs.runtime",
    "likacs.selfupdate",
    "likacs.selftest",
    "likacs.setup_windows",
    "likacs.ui.about",
    "likacs.ui.control_center",
    "likacs.ui.mode_chooser",
    "likacs.ui.setup_wizard",
    "likacs.ui.smoke",
    "likacs.ui.station_agent",
    "likacs.ui.theme",
    "likacs.ui.update_panel",
    "likacs.ui.widgets",
    "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.simpledialog",
    "tkinter.filedialog", "tkinter.font",
    "winreg",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_icon() -> None:
    from likacs.icon import ico_bytes
    ICON.parent.mkdir(parents=True, exist_ok=True)
    ICON.write_bytes(ico_bytes())


def build_one(name: str, entry: str, extra_args: list[str] | None = None) -> Path:
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
    command += list(extra_args or [])
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


def write_checksums(files: list[Path]) -> tuple[Path, dict[str, str]]:
    target = DIST / "SHA256SUMS.txt"
    checksums: dict[str, str] = {}
    lines = []
    for path in files:
        if path.is_file():
            checksums[path.name] = sha256(path)
            lines.append(f"{checksums[path.name]}  {path.name}\n")
    target.write_text("".join(lines), encoding="utf-8")
    print(f"\nWrote {target}")
    return target, checksums


SITE = "http://likaapps.com"


def release_notes() -> str:
    path = ROOT / "docs" / "RELEASE_NOTES.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return f"LIKAcs v{VERSION} - {SITE}"


def write_manifest(tag: str, checksums: dict[str, str]) -> Path:
    """Write latest.json - the rate-limit-free source for one-click updates."""
    from likacs.selfupdate import build_manifest
    sizes = {name: (DIST / name).stat().st_size for name in checksums
             if (DIST / name).is_file()}
    payload = build_manifest(tag, checksums, sizes, notes=release_notes(),
                             version=VERSION)
    payload["download_url"] = (f"https://github.com/azyoff/LIKAcs/releases/"
                               f"download/{tag}/LIKAcs.exe")
    payload["download_name"] = "LIKAcs.exe"
    path = DIST / "latest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build LIKAcs Windows executables")
    parser.add_argument("--quick", action="store_true",
                        help="build only LIKAcs.exe (CI smoke build)")
    parser.add_argument("--tag", default=f"v{VERSION}",
                        help="release tag used in latest.json")
    parser.add_argument("--no-setup", action="store_true",
                        help="skip the optional silent-deployment Setup exe")
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

    if not args.quick and not args.no_setup:
        # The setup exe embeds the app exe that was just built.
        payload = DIST / "LIKAcs.exe"
        built.append(build_one(
            SETUP_NAME, "scripts/entry_setup.py",
            ["--add-data", f"{payload}{os.pathsep}."]))

    for extra in (ROOT / "README.md", ROOT / "LICENSE"):
        if extra.is_file():
            built.append(extra)
    _checksums_file, checksums = write_checksums(built)
    write_manifest(args.tag, checksums)
    print("\nRelease artifacts:")
    for path in sorted(DIST.glob("*")):
        if path.is_file():
            print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
