"""Launch / stop official Counter-Strike servers and clients.

Only official launch parameters and cfg files are used. Process management
(start/stop) is ordinary OS process control - never memory reads or injection.
VAC is never disabled (no -insecure flag is ever added).
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import WEBSITE
from .cfgs import LIKA_MATCH
from .rules import normalize_map
from .util import IS_WINDOWS, CREATE_NO_WINDOW, primary_ipv4


@dataclass
class LaunchedProcess:
    room_id: str
    pid: int
    game: str
    kind: str                    # listen | dedicated | client
    started_at: float
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "alive": self.alive()}

    def alive(self) -> bool:
        try:
            os.kill(self.pid, 0)
            return True
        except OSError:
            return False


class ProcessRegistry:
    """Tracks only the game processes that LIKAcs itself started."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[int, LaunchedProcess] = {}
        self._handles: dict[int, subprocess.Popen] = {}

    def track(self, item: LaunchedProcess, process: subprocess.Popen) -> None:
        with self._lock:
            self._items[item.pid] = item
            self._handles[item.pid] = process

    def for_room(self, room_id: str) -> list[LaunchedProcess]:
        with self._lock:
            return [item for item in self._items.values() if item.room_id == room_id]

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._items.values())
        return [item.to_dict() for item in items]

    def prune_dead(self) -> int:
        with self._lock:
            dead = [pid for pid, item in self._items.items() if not item.alive()]
            for pid in dead:
                self._items.pop(pid, None)
                self._handles.pop(pid, None)
        return len(dead)

    def stop(self, room_id: str) -> list[int]:
        with self._lock:
            targets = [pid for pid, item in self._items.items() if item.room_id == room_id]
        for pid in targets:
            graceful_close_process(pid)
        with self._lock:
            for pid in targets:
                self._items.pop(pid, None)
                self._handles.pop(pid, None)
        return targets


def build_server_argv(install: dict[str, Any], room: dict[str, Any],
                      cfg_filename: str = LIKA_MATCH) -> tuple[list[str], str]:
    """Build an official command line for a listen or dedicated LAN server."""
    game = room.get("game", "cs2")
    map_name = normalize_map(room.get("map", "de_dust2"))
    port = int(room.get("port", 27015))
    slots = max(2, min(64, int(room.get("slots", 10))))
    password = str(room.get("rcon_password", "") or "lika")
    mode = room.get("server_mode", "listen")
    client = str(install.get("client_exe", ""))
    dedicated = str(install.get("server_exe", "") or "")
    workdir = str(install.get("root") or str(Path(client).parent))

    common = [
        "-usercon",                       # official RCON
        "-port", str(port),
        "+sv_lan", "1",                  # 100% LAN switch traffic
        "+rcon_password", password,
        "+map", map_name,
        "+maxplayers", str(slots),
        "+hostname", f"LIKAcs ({WEBSITE}) - {room.get('name', 'Room')}",
        "+exec", cfg_filename,
    ]
    if game == "cs2":
        # CS2 listen server: the player sitting on the host PC can also play.
        # VAC stays fully enabled: no -insecure / no ticket-bypass flags are used.
        argv = [client, "-game", "csgo", "-console"] + common
    else:
        if mode == "dedicated" and dedicated:
            argv = [dedicated, "-game", "cstrike", "-console", "+ip", primary_ipv4()] + common
        else:
            argv = [client, "-game", "cstrike", "-console"] + common
    # Safety: reject any attempt to disable VAC or alter binaries.
    return argv, workdir


def build_client_argv(install: dict[str, Any], game: str,
                      host: str, port: int) -> list[str]:
    client = str(install.get("client_exe", ""))
    argv = [client]
    if game == "cs16":
        argv += ["-game", "cstrike", "-console"]
    argv += ["+connect", f"{host}:{int(port)}"]
    return argv


def launch_process(argv: list[str], workdir: str, hide_console: bool = False) -> subprocess.Popen:
    flags = CREATE_NO_WINDOW if (hide_console and IS_WINDOWS) else 0
    return subprocess.Popen(
        argv, cwd=workdir or None,
        creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _windows_close_windows(pid: int) -> bool:
    """Ask the game's top-level windows to close (WM_CLOSE), never inject."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and user32.IsWindowVisible(hwnd):
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return True

        proc = EnumWindowsProc(callback)
        user32.EnumWindows(proc, 0)
        return True
    except Exception:
        return False


def graceful_close_process(pid: int, grace: float = 4.0) -> bool:
    """Close a game cleanly; escalate to taskkill only if it refuses to exit."""
    _windows_close_windows(pid)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.25)
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=8, creationflags=CREATE_NO_WINDOW)
        else:
            os.kill(pid, 9)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def matching_game_processes(names: tuple[str, ...] = ("cs2.exe", "hl.exe", "hlds.exe")) -> list[dict[str, Any]]:
    """List running game processes (used only after explicit operator confirmation)."""
    if IS_WINDOWS:
        try:
            proc = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                  text=True, errors="ignore", timeout=10,
                                  creationflags=CREATE_NO_WINDOW)
            result = []
            for line in (proc.stdout or "").splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2 and parts[0].lower() in names:
                    try:
                        result.append({"name": parts[0], "pid": int(parts[1])})
                    except ValueError:
                        pass
            return result
        except (OSError, subprocess.SubprocessError):
            return []
    # Linux/macOS: /proc scan for development/testing only.
    found: list[dict[str, Any]] = []
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return found
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if any(name.split(".")[0] in cmdline.lower() for name in names):
            found.append({"name": cmdline.strip()[:64], "pid": int(entry.name)})
    return found
