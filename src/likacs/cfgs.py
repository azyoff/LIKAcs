"""Official Counter-Strike config-file writer.

The whole "smart lika join" trick lives here:

  autoexec.cfg / userconfig.cfg   ->  exec lika_autoexec.cfg   (installed once)
  lika_autoexec.cfg               ->  alias lika "exec lika_join.cfg"
                                     alias lika1..3 "exec lika_roomN.cfg"
                                     bind F10 "lika"
  lika_join.cfg / lika_roomN.cfg  ->  connect <host_ip>:<port>  (rewritten live)

Because `exec` reads the target file from disk *at the moment the alias is
used*, the Station Agent can retarget a PC instantly by rewriting a tiny .cfg
even while CS2 or CS 1.6 is already running. No memory access, no injection.

All existing player settings (crosshair, sensitivity, binds) are preserved:
only a single, clearly marked hook line is appended to autoexec/userconfig,
and only the F10 key is rebound.
"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import WEBSITE
from .branding import CFG_HEADER
from .rules import render_cvars
from .util import atomic_write_text

AUTOEXEC_CS2 = "autoexec.cfg"
AUTOEXEC_CS16 = "userconfig.cfg"
LIKA_AUTOEXEC = "lika_autoexec.cfg"
LIKA_JOIN = "lika_join.cfg"
LIKA_ROOM_PREFIX = "lika_room"
LIKA_MATCH = "lika_match.cfg"
LIKA_KNIFE = "lika_knife.cfg"
LIKA_WARMUP = "lika_warmup.cfg"

MARKER_START = "// >>> LIKAcs (likaapps.com) managed block - START"
MARKER_END = "// <<< LIKAcs (likaapps.com) managed block - END"
HOOK_LINE = f"exec {LIKA_AUTOEXEC}"

ROOM_ALIAS_COUNT = 3


@dataclass(frozen=True)
class JoinTarget:
    """Where a PC should connect when it types lika / presses F10."""

    host: str
    port: int
    password: str = ""
    room_name: str = ""
    room_number: int = 0

    def to_dict(self) -> dict:
        return {
            "host": self.host, "port": int(self.port), "password": self.password,
            "room_name": self.room_name, "room_number": self.room_number,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "JoinTarget | None":
        if not isinstance(raw, dict) or not raw.get("host"):
            return None
        try:
            port = int(raw.get("port", 27015))
        except (TypeError, ValueError):
            port = 27015
        return cls(
            host=str(raw["host"]), port=port,
            password=str(raw.get("password", "") or ""),
            room_name=str(raw.get("room_name", "") or ""),
            room_number=int(raw.get("room_number", 0) or 0),
        )


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _newline_for(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _strip_managed_block(text: str) -> str:
    """Remove a previously installed LIKAcs block, keeping every other line."""
    lines = text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == MARKER_START:
            skipping = True
            continue
        if skipping:
            if stripped == MARKER_END:
                skipping = False
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def install_autoexec_hook(cfg_dir: str | Path, autoexec_name: str,
                          make_backup: bool = True) -> dict:
    """Append `exec lika_autoexec.cfg` safely and idempotently.

    Never overwrites player settings. A timestamped backup is created the very
    first time the file is modified.
    """
    directory = Path(cfg_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / autoexec_name
    original = _read(path)
    newline = _newline_for(original)
    stripped = _strip_managed_block(original)
    block = newline.join([MARKER_START, HOOK_LINE, MARKER_END])

    backup = ""
    if make_backup and path.exists() and MARKER_START not in original:
        backup_path = directory / f"{autoexec_name}.likacs-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.copy2(path, backup_path)
            backup = str(backup_path)
        except OSError:
            backup = ""

    body = stripped.rstrip("\r\n")
    content = (body + newline if body else "") + block + newline
    atomic_write_text(path, content)
    return {
        "file": str(path),
        "created": not bool(original),
        "backup": backup,
        "hook_count": content.count(HOOK_LINE),
    }


def render_lika_autoexec(join_word: str = "lika", f10_key: str = "F10",
                         enable_f10: bool = True, game: str = "cs2") -> str:
    """Generate lika_autoexec.cfg (aliases + console + optional F10 bind)."""
    words = {"lika", (join_word or "lika").strip() or "lika"}
    lines = [CFG_HEADER.rstrip(), ""]
    lines.append("// Console enabling (official cvar only; never edits game binaries)")
    lines.append("con_enable 1" if game == "cs2" else "console 1")
    lines.append("")
    lines.append("// Type lika (or the custom word) to join your assigned room")
    for word in sorted(words):
        if not re.fullmatch(r"[A-Za-z0-9_]+", word):
            continue
        lines.append(f'alias "{word}" "exec {LIKA_JOIN}"')
    for index in range(1, ROOM_ALIAS_COUNT + 1):
        lines.append(f'alias "lika{index}" "exec {LIKA_ROOM_PREFIX}{index}.cfg"')
    lines.append("")
    if enable_f10:
        key = re.sub(r"[^A-Za-z0-9_]", "", (f10_key or "F10"))[:16] or "F10"
        lines.append(f'// 1-key join: overrides CS 1.6\'s default "quit prompt" F10 bind')
        lines.append(f'unbind "{key}"')
        lines.append(f'bind "{key}" "lika"')
    lines.append("")
    lines.append(f'echo "LIKAcs ready - {WEBSITE} - type lika or press F10 to join"')
    return "\n".join(lines) + "\n"


def render_join_cfg(target: JoinTarget | None) -> str:
    """Generate the tiny per-PC file that is rewritten in real time."""
    lines = [CFG_HEADER.rstrip(), ""]
    if target is None:
        lines += [
            "// No room assigned to this PC yet.",
            f'echo "LIKAcs ({WEBSITE}): no room assigned yet - ask the cafe desk"',
        ]
    else:
        label = target.room_name or f"Room {target.room_number or 1}"
        lines.append(f"// Assigned: {label} -> {target.host}:{target.port}")
        if target.password:
            safe_pw = target.password.replace('"', "'")
            lines.append(f'password "{safe_pw}"')
        lines.append(f"connect {target.host}:{target.port}")
        lines.append(f'echo "LIKAcs: joining {label} ({target.host}:{target.port})"')
    return "\n".join(lines) + "\n"


class CfgManager:
    """Writes LIKAcs cfg files into one game's cfg directory."""

    def __init__(self, cfg_dir: str | Path, game: str) -> None:
        self.cfg_dir = Path(cfg_dir)
        self.game = game
        self.autoexec_name = AUTOEXEC_CS2 if game == "cs2" else AUTOEXEC_CS16

    def ensure_dir(self) -> None:
        self.cfg_dir.mkdir(parents=True, exist_ok=True)

    def install(self, join_word: str = "lika", f10_key: str = "F10",
                enable_f10: bool = True) -> dict:
        self.ensure_dir()
        hook = install_autoexec_hook(self.cfg_dir, self.autoexec_name)
        autoexec = render_lika_autoexec(join_word, f10_key, enable_f10, self.game)
        atomic_write_text(self.cfg_dir / LIKA_AUTOEXEC, autoexec)
        if not (self.cfg_dir / LIKA_JOIN).exists():
            self.set_target(None)
        for index in range(1, ROOM_ALIAS_COUNT + 1):
            path = self.cfg_dir / f"{LIKA_ROOM_PREFIX}{index}.cfg"
            if not path.exists():
                atomic_write_text(path, render_join_cfg(None))
        hook["generated"] = [LIKA_AUTOEXEC, LIKA_JOIN] + [
            f"{LIKA_ROOM_PREFIX}{i}.cfg" for i in range(1, ROOM_ALIAS_COUNT + 1)
        ]
        return hook

    def set_target(self, target: JoinTarget | None) -> str:
        self.ensure_dir()
        path = self.cfg_dir / LIKA_JOIN
        atomic_write_text(path, render_join_cfg(target))
        return str(path)

    def set_room_targets(self, targets: Iterable[JoinTarget | None]) -> list[str]:
        written = []
        items = list(targets)[:ROOM_ALIAS_COUNT]
        for index in range(1, ROOM_ALIAS_COUNT + 1):
            target = items[index - 1] if index <= len(items) else None
            path = self.cfg_dir / f"{LIKA_ROOM_PREFIX}{index}.cfg"
            atomic_write_text(path, render_join_cfg(target))
            written.append(str(path))
        return written

    def write_match(self, cvars: list[tuple[str, str]], extra_commands: list[str] | None = None,
                    filename: str = LIKA_MATCH) -> str:
        """Write the per-room server rules cfg (exec'd via official RCON)."""
        self.ensure_dir()
        safe_name = Path(re.sub(r"[^a-zA-Z0-9_.\-]", "", filename)).name or LIKA_MATCH
        header = CFG_HEADER + f"// Match rules for {self.game}\n"
        text = render_cvars(cvars, header)
        if extra_commands:
            text += "\n" + "\n".join(extra_commands) + "\n"
        # Warmup is ended automatically once the room is ready.
        if self.game == "cs2":
            text += "mp_warmup_end\n"
        else:
            text += "sv_restart 1\n"
        path = self.cfg_dir / safe_name
        atomic_write_text(path, text)
        return str(path)

    def write_commands(self, filename: str, commands: list[str]) -> str:
        self.ensure_dir()
        safe_name = Path(re.sub(r"[^a-zA-Z0-9_.\-]", "", filename)).name or LIKA_KNIFE
        path = self.cfg_dir / safe_name
        atomic_write_text(path, CFG_HEADER + "\n".join(commands) + "\n")
        return str(path)

    def describe(self) -> dict:
        return {
            "game": self.game,
            "cfg_dir": str(self.cfg_dir),
            "files": {name: (self.cfg_dir / name).exists() for name in (
                self.autoexec_name, LIKA_AUTOEXEC, LIKA_JOIN,
                *(f"{LIKA_ROOM_PREFIX}{i}.cfg" for i in range(1, ROOM_ALIAS_COUNT + 1)),
                LIKA_MATCH,
            )},
        }
