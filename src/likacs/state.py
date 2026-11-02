"""Rooms, station labels and other persistent cafe state."""

from __future__ import annotations

import secrets
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import Settings
from .protocol import GAME_PORT_BASE
from .rules import DEFAULT_RULES, preset_slots
from .util import data_path, load_json, save_json, short_id, utc_now_iso

ROOMS_FILE = "rooms.json"
ALIASES_FILE = "station-labels.json"


@dataclass
class Room:
    id: str
    name: str
    game: str = "cs2"
    preset: str = "5vs5"
    map: str = "de_dust2"
    custom_slots: int = 10
    host_station_id: str = ""
    host_ip: str = ""                 # last known LAN IP of the host PC
    station_ids: list[str] = field(default_factory=list)
    rules: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_RULES))
    overtime: bool = True
    state: str = "idle"               # idle | starting | live | paused | stopped
    port: int = GAME_PORT_BASE
    rcon_password: str = ""
    server_mode: str = "listen"       # listen | dedicated
    created_at: str = ""
    started_at: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Room":
        allowed = set(cls.__dataclass_fields__)
        data = {key: value for key, value in raw.items() if key in allowed}
        room = cls(**data)
        rules = dict(DEFAULT_RULES)
        if isinstance(room.rules, dict):
            rules.update({str(k): str(v) for k, v in room.rules.items()})
        room.rules = rules
        room.station_ids = [str(item) for item in (room.station_ids or [])]
        room.custom_slots = max(2, min(64, int(room.custom_slots or 10)))
        return room

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def slots(self) -> int:
        return preset_slots(self.preset, self.custom_slots)

    @property
    def number(self) -> int:
        digits = "".join(ch for ch in self.name if ch.isdigit())
        return int(digits) if digits else 0

    @property
    def label(self) -> str:
        return f"{self.name}: {self.preset} {'playing' if self.state == 'live' else self.state}"


class RoomManager:
    """Thread-safe, JSON-persisted list of rooms."""

    def __init__(self, path: str | None = None, settings: Settings | None = None) -> None:
        self.path = path or str(data_path(ROOMS_FILE))
        self.settings = settings or Settings()
        self._lock = threading.RLock()
        raw = load_json(self.path, {"rooms": []})
        self._rooms: dict[str, Room] = {}
        for item in raw.get("rooms", []):
            try:
                room = Room.from_dict(item)
                self._rooms[room.id] = room
            except (TypeError, ValueError):
                continue

    def save(self) -> None:
        with self._lock:
            payload = {"version": 1, "rooms": [room.to_dict() for room in self._rooms.values()]}
        save_json(self.path, payload)

    def list(self) -> list[Room]:
        import copy
        with self._lock:
            rooms = [copy.deepcopy(room) for room in self._rooms.values()]
        return sorted(rooms, key=lambda r: (r.number or 9999, r.created_at))

    def get(self, room_id: str) -> Room | None:
        import copy
        with self._lock:
            room = self._rooms.get(room_id)
            return copy.deepcopy(room) if room else None

    def _next_number(self) -> int:
        numbers = [room.number for room in self._rooms.values()]
        return max(numbers, default=0) + 1

    def _next_port(self) -> int:
        used = {int(room.port) for room in self._rooms.values()}
        base = self.settings.game_port_base
        port = base
        while port in used and port < base + 200:
            port += 1
        return port

    def create(self, **kwargs: Any) -> Room:
        with self._lock:
            number = self._next_number()
            payload = dict(kwargs)
            # Always keep the pre-loaded cafe defaults, even when the operator
            # supplies only one or two overridden cvars.
            rules = dict(DEFAULT_RULES)
            if isinstance(payload.get("rules"), dict):
                rules.update({str(k): str(v) for k, v in payload["rules"].items()})
            payload["rules"] = rules
            room = Room(
                id=short_id(10),
                name=str(payload.pop("name", "") or f"Room {number}"),
                port=self._next_port(),
                rcon_password=secrets.token_urlsafe(12),
                created_at=utc_now_iso(),
                **payload,
            )
            self._rooms[room.id] = room
        self.save()
        return self.get(room.id)  # type: ignore[return-value]

    def update(self, room_id: str, changes: dict[str, Any]) -> Room | None:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            merged = room.to_dict()
            merged.update(changes)
            self._rooms[room_id] = Room.from_dict(merged)
        self.save()
        return self.get(room_id)

    def delete(self, room_id: str) -> bool:
        with self._lock:
            existed = self._rooms.pop(room_id, None) is not None
        if existed:
            self.save()
        return existed

    def room_for_station(self, station_id: str) -> Room | None:
        for room in self.list():
            if station_id in room.station_ids:
                return room
        return None

    def statuses(self) -> list[str]:
        return [room.label for room in self.list()]


class StationLabels:
    """Operator-friendly PC names (PC 1, PC 2, ...) persisted on the laptop."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or str(data_path(ALIASES_FILE))
        self._lock = threading.RLock()
        self._labels: dict[str, str] = dict(load_json(self.path, {}))

    def get(self, station_id: str, fallback: str = "") -> str:
        with self._lock:
            return self._labels.get(station_id) or fallback

    def set(self, station_id: str, label: str) -> None:
        with self._lock:
            self._labels[station_id] = label.strip()[:48]
            save_json(self.path, dict(self._labels))

    def all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._labels)
