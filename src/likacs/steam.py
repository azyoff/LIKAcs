"""Steam's official steam://connect/ protocol helpers.

Used by the laptop's "Start & Connect Selected PCs" action: the command is sent
to each Station Agent, which opens the official Steam URL *locally* on that PC.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from typing import Any

from .protocol import STEAM_APP_CS16, STEAM_APP_CS2
from .util import IS_WINDOWS, CREATE_NO_WINDOW, run_quiet


def connect_url(host: str, port: int, password: str = "") -> str:
    url = f"steam://connect/{host}:{int(port)}"
    if password:
        safe = "".join(ch for ch in password if ch.isalnum() or ch in "-_.")[:64]
        if safe:
            url += "/" + safe
    return url


def rungame_url(game: str) -> str:
    return f"steam://rungameid/{STEAM_APP_CS2 if game == 'cs2' else STEAM_APP_CS16}"


def open_steam_url(url: str) -> bool:
    """Open an official steam:// URL through the OS handler (Steam)."""
    if not url.startswith("steam://"):
        return False
    try:
        if IS_WINDOWS:
            os.startfile(url)  # type: ignore[attr-defined]  # Windows-only API
            return True
        return bool(webbrowser.open(url))
    except Exception:
        return False


def connect_fallback_argv(client_exe: str, game: str, host: str, port: int,
                          password: str = "") -> list[str]:
    """GoldSrc also supports the official +connect launch parameter."""
    argv = [client_exe]
    if game == "cs16":
        argv += ["-game", "cstrike", "-console"]
    if password:
        argv += ["+password", password]
    argv += ["+connect", f"{host}:{int(port)}"]
    return argv


def launch_and_connect(install: dict[str, Any] | None, game: str, host: str,
                       port: int, password: str = "", launch_game: bool = True,
                       use_fallback: bool = False) -> dict[str, Any]:
    """Run on the gaming PC. Returns a report for the Control Center."""
    report: dict[str, Any] = {"url": connect_url(host, port, password), "opened": False}
    if launch_game:
        report["game_url"] = rungame_url(game)
        report["game_opened"] = open_steam_url(report["game_url"])
    report["opened"] = open_steam_url(report["url"])
    if not report["opened"] and use_fallback and install and install.get("client_exe"):
        # Only used if the Steam URL handler is unavailable on that PC.
        import subprocess
        argv = connect_fallback_argv(install["client_exe"], game, host, port, password)
        try:
            subprocess.Popen(argv, creationflags=0)
            report["fallback"] = argv
            report["opened"] = True
        except OSError as exc:
            report["fallback_error"] = str(exc)
    return report
