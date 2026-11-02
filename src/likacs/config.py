"""Persistent settings shared by Control Center and Station Agent."""

from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from .protocol import AGENT_PORT, DISCOVERY_PORT, GAME_PORT_BASE
from .security import DEFAULT_LAN_KEY
from .util import data_path, load_json, save_json

SETTINGS_FILE = "settings.json"


def _default_rules() -> dict[str, str]:
    return {
        "sv_lan": "1",
        "mp_freezetime": "3",
        "mp_friendlyfire": "1",
        "mp_autokick": "0",
        "mp_autoteambalance": "0",
        "mp_limitteams": "0",
        "mp_forcecamera": "1",
        "bot_quota": "0",
    }


@dataclass
class Settings:
    """All user-editable options. New fields always have safe defaults."""

    lan_key: str = DEFAULT_LAN_KEY
    discovery_port: int = DISCOVERY_PORT
    agent_port: int = AGENT_PORT
    game_port_base: int = GAME_PORT_BASE
    join_word: str = "lika"
    enable_f10_bind: bool = True
    f10_key: str = "F10"
    github_owner: str = "azyoff"
    github_repo: str = "LIKAcs"
    auto_check_updates: bool = True
    autostart: bool = False
    minimize_to_tray: bool = True
    silent_start: bool = False
    station_label: str = ""
    theme: str = "dark"
    server_mode: str = "listen"          # listen (host plays) | dedicated
    default_game: str = "cs2"
    default_map: str = "de_dust2"
    default_preset: str = "5vs5"
    overtime: bool = True
    rules: dict[str, str] = field(default_factory=_default_rules)
    game_paths: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        allowed = {name for name in cls.__dataclass_fields__}
        merged = {key: value for key, value in (raw or {}).items() if key in allowed}
        obj = cls(**merged)
        rules = _default_rules()
        if isinstance(obj.rules, dict):
            rules.update({str(k): str(v) for k, v in obj.rules.items()})
        obj.rules = rules
        if obj.join_word and not obj.join_word.replace("_", "").isalnum():
            obj.join_word = "lika"
        obj.join_word = (obj.join_word or "lika").strip()[:24]
        obj.f10_key = (obj.f10_key or "F10").strip()[:16]
        return obj

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SettingsStore:
    """Thread-safe load/save with an in-memory cached copy."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or str(data_path(SETTINGS_FILE))
        self._lock = threading.RLock()
        self._settings = Settings.from_dict(load_json(self.path, {}))

    @property
    def value(self) -> Settings:
        with self._lock:
            return copy.deepcopy(self._settings)

    def get(self) -> Settings:
        return self.value

    def update(self, changes: dict[str, Any]) -> Settings:
        with self._lock:
            merged = self._settings.to_dict()
            merged.update(changes)
            self._settings = Settings.from_dict(merged)
            save_json(self.path, self._settings.to_dict())
            return copy.deepcopy(self._settings)

    def reload(self) -> Settings:
        with self._lock:
            self._settings = Settings.from_dict(load_json(self.path, {}))
            return copy.deepcopy(self._settings)
