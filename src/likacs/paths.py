"""Detect already-installed Steam games across every drive.

Zero SteamCMD, zero extra download: LIKAcs only locates the cs2.exe / hl.exe /
hlds.exe that are already on the gaming PC, plus their official cfg folders.
"""

from __future__ import annotations

import os
import re
import string
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .util import IS_WINDOWS, CREATE_NO_WINDOW, run_quiet

STEAM_LIBRARY_FILE = "steamapps/libraryfolders.vdf"

CS2_RELATIVE = Path("steamapps/common/Counter-Strike Global Offensive")
CS16_RELATIVE = Path("steamapps/common/Half-Life")


@dataclass(frozen=True)
class GameInstall:
    game: str                 # cs2 | cs16
    root: str                 # game install root
    client_exe: str           # listen-server / client executable
    server_exe: str           # dedicated server executable (may be empty)
    cfg_dir: str              # official cfg folder for autoexec/userconfig
    autoexec_name: str
    detected_via: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def exists(self) -> bool:
        return Path(self.client_exe).exists() and Path(self.cfg_dir).is_dir()


def logical_drives() -> list[str]:
    """A:, C:, D:, ... on Windows; on other platforms just the filesystem root."""
    if not IS_WINDOWS:
        return ["/"]
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{letter}:\\" for index, letter in enumerate(string.ascii_uppercase) if mask & (1 << index)]
    except Exception:
        return [f"{letter}:\\" for letter in "CDEF" if Path(f"{letter}:\\").exists()]


def _unescape_vdf(text: str) -> str:
    return text.replace("\\\\", "\\").replace("\\/", "/")


def parse_libraryfolders(path: str | Path) -> list[Path]:
    """Read the official Steam libraryfolders.vdf without a VDF dependency."""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return [Path(_unescape_vdf(found)) for found in re.findall(r'"path"\s*"([^"]+)"', raw, re.I)]


def steam_libraries() -> list[Path]:
    candidates: list[Path] = []
    program_files = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Steam")
    for drive in logical_drives():
        root = Path(drive)
        candidates += [
            root / "Steam",
            root / "SteamLibrary",
            root / "Program Files (x86)" / "Steam",
            root / "Program Files" / "Steam",
            root / "Games" / "Steam",
            root / "Games" / "SteamLibrary",
        ]
    libraries: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        vdf = candidate / STEAM_LIBRARY_FILE
        if vdf.exists():
            libraries.extend(parse_libraryfolders(vdf))
        if (candidate / "steamapps" / "common").is_dir():
            libraries.append(candidate)
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            libraries.append(candidate)
    unique: list[Path] = []
    visited: set[str] = set()
    for library in libraries:
        key = str(library).lower().rstrip("/\\")
        if key not in visited:
            visited.add(key)
            unique.append(library)
    return unique


def _pick(root: Path, *relative: str) -> Path:
    return root.joinpath(*relative)


def detect_cs2(library: Path) -> GameInstall | None:
    root = library / CS2_RELATIVE
    cfg = _pick(root, "game", "csgo", "cfg")
    client = _pick(root, "game", "bin", "win64", "cs2.exe")
    if not client.exists():
        client = _pick(root, "csgo.exe")  # legacy CS:GO layout (still official)
    if not client.exists() or not cfg.is_dir():
        return None
    return GameInstall(
        game="cs2", root=str(root), client_exe=str(client),
        server_exe=str(client),  # CS2 listen server host can play at the same time
        cfg_dir=str(cfg), autoexec_name="autoexec.cfg",
        detected_via=str(library),
    )


def detect_cs16(library: Path) -> GameInstall | None:
    root = library / CS16_RELATIVE
    cfg = root / "cstrike" / "cfg"
    if not cfg.is_dir():
        cfg = root / "cstrike"  # some non-Steam installs keep userconfig.cfg here
    client = root / "hl.exe"
    if not client.exists():
        return None
    server = root / "hlds.exe"
    return GameInstall(
        game="cs16", root=str(root), client_exe=str(client),
        server_exe=str(server) if server.exists() else "",
        cfg_dir=str(cfg), autoexec_name="userconfig.cfg",
        detected_via=str(library),
    )


def detect_installs(overrides: dict[str, dict[str, str]] | None = None) -> dict[str, GameInstall]:
    """Return a mapping of game -> detected install, with manual overrides winning."""
    found: dict[str, GameInstall] = {}
    for library in steam_libraries():
        for detector in (detect_cs2, detect_cs16):
            install = detector(library)
            if install and install.game not in found:
                found[install.game] = install
    for game, values in (overrides or {}).items():
        if game not in ("cs2", "cs16") or not isinstance(values, dict):
            continue
        try:
            cfg_dir = values.get("cfg_dir", "")
            client_exe = values.get("client_exe", "")
            if not cfg_dir or not client_exe:
                continue
            found[game] = GameInstall(
                game=game,
                root=values.get("root", str(Path(client_exe).parent)),
                client_exe=client_exe,
                server_exe=values.get("server_exe", ""),
                cfg_dir=cfg_dir,
                autoexec_name=values.get("autoexec_name", "autoexec.cfg" if game == "cs2" else "userconfig.cfg"),
                detected_via="manual override",
            )
        except (TypeError, ValueError):
            continue
    return found


def install_summary(installs: dict[str, GameInstall]) -> list[dict[str, Any]]:
    return [
        {**install.to_dict(), "exists": install.exists, "cfg_writable": os.access(install.cfg_dir, os.W_OK)}
        for install in installs.values()
    ]


def game_cfg_dirs(installs: dict[str, GameInstall]) -> dict[str, str]:
    return {game: install.cfg_dir for game, install in installs.items()}
