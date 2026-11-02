"""LIKAcs Control Center - the laptop (or any gaming PC) remote dashboard.

Owns the room state, listens to UDP heartbeats, and orchestrates every Station
Agent through the signed HTTP/JSON API. All network work is done off the UI
thread so Tkinter never freezes.
"""

from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from . import VERSION, WEBSITE
from .branding import fit_tray_tooltip
from .config import SettingsStore
from .http_api import ApiError, SignedClient
from .network import DiscoveryService, StationTable
from .protocol import (EP_AUTOSTART, EP_CLOSE_GAME, EP_CONFIGURE_JOIN,
                       EP_FIREWALL, EP_LAUNCH_SERVER, EP_RCON, EP_SETUP,
                       EP_SET_LABEL, EP_STATUS, EP_STEAM_CONNECT, EP_STOP_SERVER,
                       EP_SYNC_SETTINGS, EP_UPDATE_STATUS, EP_WRITE_CONFIG,
                       HTTP_TIMEOUT, HTTP_TIMEOUT_LONG, MAX_TOOLTIP_CHARS,
                       MSG_BYE, MSG_CONTROLLER, MSG_HELLO, MSG_PROBE)
from .rules import (build_match_cvars, change_map_commands, commands_for,
                    normalize_map)
from .rcon import parse_status
from .state import Room, RoomManager, StationLabels
from .update import Release, UpdateManager, push_update
from .util import utc_now_iso

Logger = Callable[[str], None]


class ControlCenter:
    def __init__(self, settings_store: SettingsStore | None = None,
                 logger: Logger | None = None,
                 on_change: Callable[[], None] | None = None) -> None:
        self.store = settings_store or SettingsStore()
        self.settings = self.store.get()
        self.logger = logger or (lambda _msg: None)
        self.on_change = on_change
        self.client = SignedClient(self.settings.lan_key)
        self.rooms = RoomManager(settings=self.settings)
        self.labels = StationLabels()
        self.stations = StationTable()
        self.discovery = DiscoveryService(
            self.settings.discovery_port, self.settings.lan_key,
            on_message=self.on_message, probe=True, logger=self.logger,
        )
        self.updater = UpdateManager(self.settings.github_owner,
                                     self.settings.github_repo, VERSION)
        self.last_error = ""
        self._expire_thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.discovery.start()
        self.discovery.send_probe()
        self._stop.clear()
        self._expire_thread = threading.Thread(target=self._expire_loop,
                                               name="likacs-expire", daemon=True)
        self._expire_thread.start()
        self.logger(f"Control Center listening for stations on UDP {self.settings.discovery_port}")

    def stop(self) -> None:
        self._stop.set()
        self.discovery.stop()
        if self._expire_thread:
            self._expire_thread.join(timeout=1.5)
        self.logger("Control Center stopped")

    def _expire_loop(self) -> None:
        while not self._stop.wait(3.0):
            expired = self.stations.expire()
            if expired and self.on_change:
                self.on_change()

    def on_message(self, body: dict[str, Any], addr: tuple[str, int]) -> None:
        kind = body.get("kind")
        if kind == MSG_HELLO:
            station = dict(body)
            if addr and not addr[0].startswith("127."):
                station["ip"] = addr[0]
            station_id = str(station.get("id") or "")
            label = self.labels.get(station_id, str(station.get("label") or station.get("hostname") or station_id))
            station["label"] = label
            station["agent_port"] = int(station.get("agent_port") or self.settings.agent_port)
            self.stations.update(station)
            if self.on_change:
                self.on_change()
        elif kind == MSG_BYE:
            self.stations.remove(str(body.get("id", "")))
            if self.on_change:
                self.on_change()
        elif kind in (MSG_PROBE, MSG_CONTROLLER):
            pass

    # ------------------------------------------------------------- stations
    def online_stations(self) -> list[dict[str, Any]]:
        self.stations.expire()
        return self.stations.all()

    def station(self, station_id: str) -> dict[str, Any] | None:
        return self.stations.get(station_id)

    def _host_for(self, room: Room) -> tuple[str, int] | None:
        station = self.station(room.host_station_id) if room.host_station_id else None
        if station and station.get("ip"):
            return str(station["ip"]), int(station.get("agent_port") or self.settings.agent_port)
        return None

    def _send(self, host: str, port: int, path: str, payload: dict[str, Any],
              timeout: float = HTTP_TIMEOUT) -> dict[str, Any]:
        try:
            return self.client.request(host, port, path, payload, timeout=timeout)
        except ApiError as exc:
            self.last_error = str(exc)
            self.logger(str(exc))
            return {"ok": False, "error": str(exc)}

    def _send_station(self, station: dict[str, Any], path: str,
                      payload: dict[str, Any], timeout: float = HTTP_TIMEOUT) -> dict[str, Any]:
        host = station.get("ip") or station.get("host")
        port = int(station.get("agent_port") or self.settings.agent_port)
        if not host:
            return {"ok": False, "error": "station has no LAN IP"}
        return self._send(str(host), port, path, payload, timeout)

    def _parallel(self, tasks: list[tuple[str, Callable[[], dict[str, Any]]]]) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        if not tasks:
            return results
        with ThreadPoolExecutor(max_workers=min(12, len(tasks))) as pool:
            futures = {pool.submit(task): key for key, task in tasks}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as exc:
                    results[key] = {"ok": False, "error": str(exc)}
        return results

    # --------------------------------------------------------------- rooms
    def create_room(self, **kwargs: Any) -> Room:
        defaults = {
            "game": self.settings.default_game,
            "map": self.settings.default_map,
            "preset": self.settings.default_preset,
            "rules": dict(self.settings.rules),
            "overtime": self.settings.overtime,
            "server_mode": self.settings.server_mode,
        }
        defaults.update(kwargs)
        room = self.rooms.create(**defaults)
        self.logger(f"Created {room.name} ({room.preset}, {room.game}, {room.map})")
        self.refresh_join_configs()
        return room

    def update_room(self, room_id: str, changes: dict[str, Any]) -> Room | None:
        if "map" in changes:
            changes["map"] = normalize_map(str(changes["map"]))
        room = self.rooms.update(room_id, changes)
        if room:
            self.logger(f"Updated {room.name}")
            if room.state == "live" and any(key in changes for key in ("rules", "overtime", "slots", "preset")):
                self.write_match_rules(room_id)
            self.refresh_join_configs()
        return room

    def delete_room(self, room_id: str) -> bool:
        room = self.rooms.get(room_id)
        if room and room.state == "live":
            self.stop_room(room_id)
        existed = self.rooms.delete(room_id)
        self.refresh_join_configs()
        return existed

    def assign_stations(self, room_id: str, station_ids: list[str]) -> Room | None:
        """A PC belongs to exactly one room; the host is always included."""
        ids = [str(item) for item in dict.fromkeys(station_ids)]
        for other in self.rooms.list():
            if other.id == room_id:
                continue
            cleaned = [item for item in other.station_ids if item not in ids]
            if cleaned != other.station_ids:
                self.rooms.update(other.id, {"station_ids": cleaned})
        room = self.rooms.get(room_id)
        if room and room.host_station_id and room.host_station_id not in ids:
            ids.append(room.host_station_id)
        updated = self.rooms.update(room_id, {"station_ids": ids})
        self.logger(f"{updated.name if updated else 'Room'} now has {len(ids)} PCs assigned")
        self.refresh_join_configs()
        return updated

    def set_host(self, room_id: str, station_id: str) -> Room | None:
        room = self.rooms.update(room_id, {"host_station_id": station_id})
        if room:
            ids = list(dict.fromkeys([*room.station_ids, station_id])) if station_id else room.station_ids
            room = self.rooms.update(room_id, {"station_ids": ids})
        self.refresh_join_configs()
        return room

    # --------------------------------------------------- smart lika targeting
    def _target_for(self, room: Room) -> dict[str, Any] | None:
        if room.state != "live":
            return None
        station = self.station(room.host_station_id) if room.host_station_id else None
        host = (station or {}).get("ip") or room.host_ip
        if not host:
            return None
        return {
            "host": str(host), "port": int(room.port), "password": "",
            "room_name": room.name, "room_number": room.number,
        }

    def refresh_join_configs(self) -> dict[str, dict[str, Any]]:
        """Push live per-PC join targets to every discovered Station Agent.

        This is the heart of multi-room routing: Room 1's PCs get lika_join.cfg
        pointing at PC 1, Room 2's PCs get one pointing at PC 5, and every PC
        gets lika_room1..3.cfg for the lika1/lika2/lika3 aliases.
        """
        rooms = self.rooms.list()
        # Keep positional slots: lika1 always means Room 1, even if it is idle.
        room_targets = [self._target_for(room) for room in rooms[:3]]
        tasks = []
        for station in self.online_stations():
            assigned = self.rooms.room_for_station(str(station.get("id")))
            primary = self._target_for(assigned) if assigned else None
            payload = {
                "all_games": True,
                "room_id": assigned.id if assigned else "",
                "primary": primary,
                "rooms": room_targets,
            }
            tasks.append((str(station.get("id")),
                          lambda s=station, p=payload: self._send_station(
                              s, EP_CONFIGURE_JOIN, p, timeout=4.0)))
        results = self._parallel(tasks)
        failed = [key for key, value in results.items() if not value.get("ok", True)]
        if failed:
            self.logger(f"Join config could not reach {len(failed)} station(s)")
        return results

    # --------------------------------------------------------- room controls
    def cvars_for_room(self, room: Room) -> list[list[str]]:
        return [[key, value] for key, value in build_match_cvars(
            room.rules, room.game, room.preset, room.slots, room.overtime)]

    def write_match_rules(self, room_id: str) -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "room not found"}
        endpoint = self._host_for(room)
        if not endpoint:
            return {"ok": False, "error": "host PC is offline"}
        payload = {
            "game": room.game, "filename": "lika_match.cfg",
            "cvars": self.cvars_for_room(room), "commands": [],
        }
        result = self._send(endpoint[0], endpoint[1], EP_WRITE_CONFIG, payload)
        if result.get("ok"):
            return self.send_rcon(room_id, ["exec lika_match.cfg"])
        return result

    def start_room(self, room_id: str) -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "room not found"}
        endpoint = self._host_for(room)
        if not endpoint:
            return {"ok": False, "error": f"{room.name}: host PC is offline (choose a Host PC first)"}
        if not room.station_ids:
            self.logger(f"{room.name}: no PCs assigned yet (host will still be able to play)")
        self.rooms.update(room_id, {"state": "starting", "host_ip": endpoint[0]})
        payload = self.rooms.get(room_id).to_dict()  # type: ignore[union-attr]
        payload["slots"] = room.slots
        payload["cvars"] = self.cvars_for_room(room)
        result = self._send(endpoint[0], endpoint[1], EP_LAUNCH_SERVER,
                            payload, timeout=HTTP_TIMEOUT_LONG)
        if not result.get("ok"):
            self.rooms.update(room_id, {"state": "stopped", "note": str(result.get("error"))})
            return result
        self.rooms.update(room_id, {
            "state": "live", "started_at": utc_now_iso(),
            "host_ip": result.get("host") or endpoint[0], "note": "",
        })
        self.logger(f"{room.name} LIVE on {endpoint[0]}:{room.port} ({room.game}, {room.map})")
        self.refresh_join_configs()
        return result

    def stop_room(self, room_id: str) -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "room not found"}
        endpoint = self._host_for(room)
        result = {"ok": True, "stopped": []}
        if endpoint:
            result = self._send(endpoint[0], endpoint[1], EP_STOP_SERVER,
                                {"room_id": room_id}, timeout=HTTP_TIMEOUT_LONG)
        self.rooms.update(room_id, {"state": "stopped"})
        self.logger(f"{room.name} stopped")
        self.refresh_join_configs()
        return result

    def send_rcon(self, room_id: str, commands: list[str],
                  parse_players: bool = False) -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "room not found"}
        endpoint = self._host_for(room)
        if not endpoint:
            return {"ok": False, "error": "host PC is offline"}
        return self._send(endpoint[0], endpoint[1], EP_RCON, {
            "game": room.game, "host": "127.0.0.1", "port": int(room.port),
            "password": room.rcon_password, "commands": commands,
            "parse_status": parse_players,
        }, timeout=HTTP_TIMEOUT_LONG)

    def live_control(self, room_id: str, action: str, **params: Any) -> dict[str, Any]:
        room = self.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "room not found"}
        if action == "change_map":
            map_name = normalize_map(str(params.get("map") or room.map))
            commands = change_map_commands(room.game, map_name)
            self.rooms.update(room_id, {"map": map_name})
        elif action == "knife_round":
            commands = commands_for(action, room.game)
            endpoint = self._host_for(room)
            if endpoint:
                written = self._send(endpoint[0], endpoint[1], EP_WRITE_CONFIG, {
                    "game": room.game, "filename": "lika_knife.cfg", "commands": commands,
                })
                if written.get("ok"):
                    commands = ["exec lika_knife.cfg"]
        elif action == "apply_rules":
            # write_match_rules() already execs the regenerated cfg over RCON.
            return self.write_match_rules(room_id)
        else:
            commands = commands_for(action, room.game)
        if not commands:
            return {"ok": False, "error": f"unknown live control '{action}'"}
        result = self.send_rcon(room_id, commands)
        if result.get("ok"):
            state = {"pause": "paused", "unpause": "live"}.get(action)
            if state:
                self.rooms.update(room_id, {"state": state})
            self.logger(f"{room.name}: {action} -> {len(commands)} official RCON command(s)")
        return result

    def start_connect_selected(self, room_id: str, station_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Tick [x] PC 1 [x] PC 2 ... -> Start & Connect Selected PCs."""
        room = self.rooms.get(room_id)
        if not room:
            return {"error": {"ok": False, "error": "room not found"}}
        if room.state != "live":
            started = self.start_room(room_id)
            if not started.get("ok"):
                return {"error": started}
            room = self.rooms.get(room_id)  # type: ignore[assignment]
        endpoint = self._host_for(room)
        if not endpoint:
            return {"error": {"ok": False, "error": "host PC is offline"}}
        selected = [self.station(item) for item in station_ids]
        tasks = []
        for station in selected:
            if not station:
                continue
            payload = {
                "game": room.game, "host": endpoint[0], "port": int(room.port),
                "password": "", "launch_game": True, "fallback": room.game == "cs16",
            }
            tasks.append((str(station.get("id")),
                          lambda s=station, p=payload: self._send_station(
                              s, EP_STEAM_CONNECT, p, timeout=HTTP_TIMEOUT_LONG)))
        results = self._parallel(tasks)
        self.logger(f"Start & Connect sent to {len(results)} PC(s) for {room.name}")
        return results

    def disconnect_stations(self, room_id: str, station_ids: list[str]) -> dict[str, Any]:
        """Return selected PCs to the main menu via official RCON kick by LAN IP."""
        room = self.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "room not found"}
        status = self.send_rcon(room_id, ["status"], parse_players=True)
        players = status.get("players") or []
        if not players and status.get("results"):
            players = parse_status("\n".join(
                str(item.get("response", "")) for item in status["results"]))
        wanted_ips: set[str] = set()
        for station_id in station_ids:
            station = self.station(station_id) or {}
            for key in ("ip",):
                if station.get(key):
                    wanted_ips.add(str(station[key]))
            for extra in station.get("ips") or []:
                wanted_ips.add(str(extra))
        kicks: list[str] = []
        matched: list[str] = []
        for player in players:
            if player.get("ip") in wanted_ips and player.get("userid"):
                matched.append(player.get("name", ""))
                if room.game == "cs2":
                    kicks.append(f"kickid {player['userid']} \"LIKAcs: session finished\"")
                else:
                    kicks.append(f"kick # {player['userid']}")
        if not kicks:
            # Some servers hide client IPs in `status`; fall back to agent-side
            # graceful close of the game (explicit operator action).
            self.logger("RCON status did not expose player IPs; using agent-side close instead")
            return self.close_games(station_ids)
        result = self.send_rcon(room_id, kicks)
        result["matched_players"] = matched
        return result

    def close_games(self, station_ids: list[str]) -> dict[str, Any]:
        tasks = []
        for station_id in station_ids:
            station = self.station(station_id)
            if not station:
                continue
            tasks.append((station_id, lambda s=station: self._send_station(
                s, EP_CLOSE_GAME,
                {"all_matching": True, "confirm": True,
                 "names": ["cs2.exe", "hl.exe", "hlds.exe"]},
                timeout=HTTP_TIMEOUT_LONG)))
        results = self._parallel(tasks)
        return {"ok": all(item.get("ok", False) for item in results.values()) if results else False,
                "results": results}

    # -------------------------------------------------------- station admin
    def station_status(self, station_id: str) -> dict[str, Any]:
        station = self.station(station_id)
        return self._send_station(station, EP_STATUS, {}, timeout=4.0) if station else {
            "ok": False, "error": "station offline"}

    def setup_station(self, station_id: str, firewall: bool = False,
                      autostart: bool = False) -> dict[str, Any]:
        station = self.station(station_id)
        if not station:
            return {"ok": False, "error": "station offline"}
        return self._send_station(station, EP_SETUP,
                                  {"firewall": firewall, "autostart": autostart},
                                  timeout=HTTP_TIMEOUT_LONG)

    def setup_all_stations(self, firewall: bool = False,
                           autostart: bool = False) -> dict[str, dict[str, Any]]:
        return self._parallel([
            (str(station.get("id")), lambda s=station: self._send_station(
                s, EP_SETUP, {"firewall": firewall, "autostart": autostart},
                timeout=HTTP_TIMEOUT_LONG))
            for station in self.online_stations()
        ])

    def firewall_station(self, station_id: str, elevate: bool = False) -> dict[str, Any]:
        station = self.station(station_id)
        return self._send_station(station, EP_FIREWALL, {"elevate": elevate},
                                  timeout=HTTP_TIMEOUT_LONG) if station else {
            "ok": False, "error": "station offline"}

    def autostart_station(self, station_id: str, enabled: bool) -> dict[str, Any]:
        station = self.station(station_id)
        return self._send_station(station, EP_AUTOSTART, {"enabled": enabled},
                                  timeout=HTTP_TIMEOUT_LONG) if station else {
            "ok": False, "error": "station offline"}

    def rename_station(self, station_id: str, label: str) -> dict[str, Any]:
        self.labels.set(station_id, label)
        station = self.station(station_id)
        if station:
            station["label"] = label
            self.stations.update(station)
        result = self._send_station(station, EP_SET_LABEL, {"label": label}) if station else {
            "ok": True, "note": "saved locally; will sync when the PC is online"}
        if self.on_change:
            self.on_change()
        return result

    def sync_settings(self, changes: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Push LAN key / join word / F10 key changes to every station.

        Important: the sync requests themselves must be signed with the OLD key,
        because stations still hold the old key until their reply arrives.
        Only after the push do we switch our own client/discovery to the new key.
        """
        self.settings = self.store.update(changes)
        payload = {key: value for key, value in changes.items()
                   if key in ("lan_key", "join_word", "f10_key", "enable_f10_bind",
                              "game_paths", "discovery_port", "agent_port")}
        tasks = [
            (str(station.get("id")), lambda s=station: self._send_station(
                s, EP_SYNC_SETTINGS, payload, timeout=HTTP_TIMEOUT_LONG))
            for station in self.online_stations()
        ]
        results = self._parallel(tasks)
        self.client = SignedClient(self.settings.lan_key)
        self.discovery.lan_key = self.settings.lan_key
        self.updater = UpdateManager(self.settings.github_owner,
                                     self.settings.github_repo, VERSION)
        return results

    def update_settings(self, changes: dict[str, Any]) -> None:
        self.settings = self.store.update(changes)
        self.client = SignedClient(self.settings.lan_key)
        self.discovery.lan_key = self.settings.lan_key
        self.updater = UpdateManager(self.settings.github_owner,
                                     self.settings.github_repo, VERSION)
        self.rooms.settings = self.settings

    # ------------------------------------------------------------- updates
    def check_updates(self) -> dict[str, Any]:
        try:
            result = self.updater.check()
            self.logger(f"Update check: current {VERSION}, latest {result['latest']}")
            return result
        except Exception as exc:
            self.logger(f"Update check failed: {exc}")
            return {"ok": False, "error": str(exc), "current": VERSION,
                    "latest": VERSION, "update_available": False}

    def download_update(self, release: Release, progress: Callable[..., None] | None = None) -> dict[str, Any]:
        return self.updater.download(release, "LIKAcs.exe", progress=progress)

    def push_update(self, asset_path: str, version: str,
                    progress: Callable[..., None] | None = None,
                    restart_agents: bool = False) -> dict[str, Any]:
        stations = [{
            "id": station.get("id"), "label": station.get("label"),
            "ip": station.get("ip"), "hostname": station.get("hostname"),
            "agent_port": station.get("agent_port"),
        } for station in self.online_stations()]
        result = push_update(self.client, stations, asset_path, version,
                             progress=progress, restart_agents=restart_agents)
        if result.get("ok"):
            self.logger(f"Pushed verified update {version} to {len(stations)} station(s)")
        return result

    def station_update_status(self, station_id: str) -> dict[str, Any]:
        station = self.station(station_id)
        return self._send_station(station, EP_UPDATE_STATUS, {}) if station else {
            "ok": False, "error": "station offline"}

    # ---------------------------------------------------------------- tray
    def tray_tooltip(self) -> str:
        statuses = [room.label for room in self.rooms.list() if room.state == "live"]
        online = len(self.online_stations())
        if online:
            statuses.append(f"{online} PC(s) online")
        return fit_tray_tooltip(statuses, MAX_TOOLTIP_CHARS)

    def tray_menu_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {"label": f"LIKAcs | {WEBSITE}", "id": "website"},
            {"separator": True},
        ]
        live = [room for room in self.rooms.list() if room.state == "live"]
        if live:
            for room in live:
                items.append({
                    "label": f"  {room.name}: {room.preset} playing ({room.map})",
                    "id": None, "disabled": True,
                })
        else:
            items.append({"label": "  No active rooms", "id": None, "disabled": True})
        items.append({"label": f"  {len(self.online_stations())} station PC(s) online",
                      "id": None, "disabled": True})
        items += [
            {"separator": True},
            {"label": "Open Control Center", "id": "show"},
            {"label": "Check for Updates / Push to PCs", "id": "updates"},
            {"label": "About LIKAcs", "id": "about"},
            {"separator": True},
            {"label": "Exit LIKAcs", "id": "exit"},
        ]
        return items
