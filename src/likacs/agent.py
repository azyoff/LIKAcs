"""LIKAcs Station Agent - the few-MB service running on every gaming PC.

Responsibilities:
  * UDP heartbeat/discovery (DHCP-proof, no static IPs).
  * HMAC-verified HTTP/JSON control API for the laptop dashboard.
  * Real-time rewriting of official lika_join.cfg / lika_roomN.cfg files.
  * Launching/stopping the already-installed CS2 / CS 1.6 LAN server.
  * Official RCON bridge, steam://connect/ launcher, firewall/autostart setup.
  * Staging verified updates pushed from the laptop.

Safety: only official cfg files, launch parameters, RCON and steam:// URLs.
No memory access, no DLL injection, no binary patching, VAC always enabled.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import VERSION, WEBSITE, VAC_PLEDGE
from .cfgs import CfgManager, JoinTarget, LIKA_AUTOEXEC, LIKA_MATCH
from .config import SettingsStore
from .games import (LaunchedProcess, ProcessRegistry, build_client_argv,
                    build_server_argv, graceful_close_process, launch_process,
                    matching_game_processes)
from .http_api import AgentHTTPServer
from .network import DiscoveryService, StationTable
from .paths import detect_installs, install_summary
from .protocol import (EP_AUTOSTART, EP_CLOSE_GAME, EP_CONFIGURE_JOIN,
                       EP_FIREWALL, EP_LAUNCH_SERVER, EP_RCON, EP_SET_LABEL,
                       EP_SETUP, EP_STATUS, EP_STEAM_CONNECT, EP_STOP_SERVER,
                       EP_SYNC_SETTINGS, EP_UPDATE_BEGIN, EP_UPDATE_CHUNK,
                       EP_UPDATE_FINISH, EP_UPDATE_STATUS, EP_WRITE_CONFIG,
                       MSG_BYE, MSG_HELLO, MSG_PROBE, MSG_CONTROLLER,
                       HTTP_TIMEOUT_LONG)
from .rules import build_match_cvars
from .security import LanAuth
from .setup_windows import (apply_firewall_rules, autostart_status,
                            current_executable, elevate, one_click_setup,
                            set_autostart)
from .steam import launch_and_connect
from .rcon import execute_commands, parse_status
from .update import stage_swap
from .util import (data_path, format_duration, get_local_hostname,
                   load_json, primary_ipv4, local_ipv4_addresses,
                   save_json, sha256_file, short_id, utc_now_iso)

Logger = Callable[[str], None]
STATION_FILE = "station.json"


def redact(argv: list[str]) -> list[str]:
    """Hide rcon_password values in logs / UI."""
    out: list[str] = []
    skip = False
    for item in argv:
        if skip:
            out.append("********")
            skip = False
            continue
        if item in ("+rcon_password", "+password"):
            skip = True
        out.append(item)
    return out


class StationAgent:
    def __init__(self, settings_store: SettingsStore | None = None,
                 logger: Logger | None = None,
                 on_restart_requested: Callable[[], None] | None = None) -> None:
        self.store = settings_store or SettingsStore()
        self.settings = self.store.get()
        self.logger = logger or (lambda _msg: None)
        self.on_restart_requested = on_restart_requested
        self._lock = threading.RLock()

        identity = load_json(data_path(STATION_FILE), {})
        self.station_id = str(identity.get("id") or short_id(12))
        self.label = str(identity.get("label") or self.settings.station_label or get_local_hostname())
        self._save_identity()

        self.auth = LanAuth(self.settings.lan_key)
        self.installs = detect_installs(self.settings.game_paths)
        self.managers = {game: CfgManager(install.cfg_dir, game)
                         for game, install in self.installs.items()}
        self.registry = ProcessRegistry()
        self.servers: dict[str, dict[str, Any]] = {}
        self.assignment: dict[str, Any] = {}
        self.peers = StationTable()
        self.transfers: dict[str, dict[str, Any]] = {}
        self.pending_update: dict[str, Any] = {}
        self.started_at = time.time()
        self._last_probe_reply = 0.0

        self.discovery = DiscoveryService(
            self.settings.discovery_port, self.settings.lan_key,
            heartbeat_factory=self.heartbeat, on_message=self.on_message,
            logger=self.logger,
        )
        self.http = AgentHTTPServer(
            ("0.0.0.0", self.settings.agent_port), self.auth,
            dispatch=self.dispatch, logger=self.logger,
        )

    # ------------------------------------------------------------- lifecycle
    def _save_identity(self) -> None:
        save_json(data_path(STATION_FILE), {"id": self.station_id, "label": self.label})

    def start(self) -> None:
        self.http.start()
        self.discovery.start()
        self.discovery.announce_now()
        self.logger(f"Station Agent '{self.label}' online on UDP {self.settings.discovery_port} "
                    f"/ TCP {self.settings.agent_port} ({primary_ipv4()})")

    def stop(self) -> None:
        self.discovery.stop()
        self.http.stop()
        for transfer in list(self.transfers.values()):
            handle = transfer.get("handle")
            if handle:
                try:
                    handle.close()
                except OSError:
                    pass
        self.logger("Station Agent stopped")

    def restart_agent(self) -> None:
        """Called after an update is staged; the UI should quit its mainloop."""
        if self.on_restart_requested:
            self.on_restart_requested()
            return
        def _exit_later() -> None:
            time.sleep(1.2)
            self.stop()
            os._exit(0)
        threading.Thread(target=_exit_later, daemon=True).start()

    # ------------------------------------------------------------- discovery
    def heartbeat(self) -> dict[str, Any]:
        with self._lock:
            servers = [dict(item) for item in self.servers.values()]
            assignment = dict(self.assignment)
        return {
            "kind": MSG_HELLO,
            "id": self.station_id,
            "label": self.label,
            "hostname": get_local_hostname(),
            "ip": primary_ipv4(),
            "ips": local_ipv4_addresses(),
            "agent_port": self.settings.agent_port,
            "version": VERSION,
            "website": WEBSITE,
            "started_at": self.started_at,
            "assignment": assignment,
            "servers": servers,
            "installs": install_summary(self.installs),
            "update": self.pending_update,
        }

    def on_message(self, body: dict[str, Any], addr: tuple[str, int]) -> None:
        kind = body.get("kind")
        if kind == MSG_PROBE:
            now = time.time()
            if now - self._last_probe_reply > 0.5:
                self._last_probe_reply = now
                self.discovery.announce_now()
        elif kind == MSG_HELLO:
            peer = dict(body)
            if peer.get("id") != self.station_id:
                peer["ip"] = addr[0] if not addr[0].startswith("127.") else peer.get("ip", addr[0])
                self.peers.update(peer)
        elif kind == MSG_BYE:
            self.peers.remove(str(body.get("id", "")))
        elif kind == MSG_CONTROLLER:
            pass

    # ---------------------------------------------------------------- status
    def status_report(self) -> dict[str, Any]:
        self.registry.prune_dead()
        return {
            "ok": True,
            "app": "LIKAcs Station Agent",
            "website": WEBSITE, "version": VERSION, "vac": VAC_PLEDGE,
            "id": self.station_id, "label": self.label,
            "hostname": get_local_hostname(),
            "ip": primary_ipv4(), "ips": local_ipv4_addresses(),
            "agent_port": self.settings.agent_port,
            "discovery_port": self.settings.discovery_port,
            "uptime": format_duration(time.time() - self.started_at),
            "join_word": self.settings.join_word,
            "f10_key": self.settings.f10_key,
            "assignment": dict(self.assignment),
            "servers": [dict(item) for item in self.servers.values()],
            "processes": self.registry.all(),
            "installs": install_summary(self.installs),
            "autostart": autostart_status(),
            "peers": len(self.peers.all()),
            "update": self.pending_update,
        }

    # ---------------------------------------------------------------- install
    def refresh_installs(self) -> dict[str, dict[str, str]]:
        self.settings = self.store.get()
        self.installs = detect_installs(self.settings.game_paths)
        self.managers = {game: CfgManager(install.cfg_dir, game)
                         for game, install in self.installs.items()}
        return {game: install.to_dict() for game, install in self.installs.items()}

    def _managers_for(self, game: str | None) -> list[tuple[str, CfgManager]]:
        if not self.managers:
            self.refresh_installs()
        if game:
            manager = self.managers.get(game)
            if manager:
                return [(game, manager)]
        return list(self.managers.items())

    def _ensure_hooks(self, manager: CfgManager, game: str) -> None:
        if not (Path(manager.cfg_dir) / LIKA_AUTOEXEC).exists():
            manager.install(self.settings.join_word, self.settings.f10_key,
                            self.settings.enable_f10_bind)

    # -------------------------------------------------------------- dispatch
    def dispatch(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        handlers = {
            EP_STATUS: self._api_status,
            EP_SETUP: self._api_setup,
            EP_FIREWALL: self._api_firewall,
            EP_AUTOSTART: self._api_autostart,
            EP_CONFIGURE_JOIN: self._api_configure_join,
            EP_WRITE_CONFIG: self._api_write_config,
            EP_LAUNCH_SERVER: self._api_launch_server,
            EP_STOP_SERVER: self._api_stop_server,
            EP_RCON: self._api_rcon,
            EP_STEAM_CONNECT: self._api_steam_connect,
            EP_CLOSE_GAME: self._api_close_game,
            EP_SET_LABEL: self._api_set_label,
            EP_SYNC_SETTINGS: self._api_sync_settings,
            EP_UPDATE_BEGIN: self._api_update_begin,
            EP_UPDATE_CHUNK: self._api_update_chunk,
            EP_UPDATE_FINISH: self._api_update_finish,
            EP_UPDATE_STATUS: self._api_update_status,
        }
        handler = handlers.get(path)
        if handler is None:
            return 404, {"error": f"unknown endpoint {path}"}
        result = handler(payload)
        if isinstance(result, tuple):
            return result
        return 200, result

    # ----------------------------------------------------------- api handlers
    def _api_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.status_report()

    def _api_setup(self, payload: dict[str, Any]) -> dict[str, Any]:
        report = one_click_setup(
            self.settings,
            firewall=bool(payload.get("firewall")),
            autostart=bool(payload.get("autostart")),
        )
        self.refresh_installs()
        self.discovery.announce_now()
        return {"ok": report.get("ok", False), "report": report}

    def _api_firewall(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("elevate"):
            return {"ok": True, "elevated": elevate(["--elevated-firewall"])}
        return apply_firewall_rules(self.settings,
                                    {k: v.to_dict() for k, v in self.installs.items()})

    def _api_autostart(self, payload: dict[str, Any]) -> dict[str, Any]:
        return set_autostart(bool(payload.get("enabled")), mode="station")

    def _api_configure_join(self, payload: dict[str, Any]) -> dict[str, Any]:
        primary = JoinTarget.from_dict(payload.get("primary"))
        room_targets = [
            JoinTarget.from_dict(item) for item in (payload.get("rooms") or [])[:3]
        ]
        while len(room_targets) < 3:
            room_targets.append(None)
        written: list[str] = []
        managers = self._managers_for(payload.get("game") if not payload.get("all_games", True) else None)
        if not managers:
            return {"ok": False, "error": "No CS2 / CS 1.6 cfg folder detected - run 1-Click Station Setup first."}
        for game, manager in managers:
            self._ensure_hooks(manager, game)
            written.append(manager.set_target(primary))
            written += manager.set_room_targets(room_targets)
        with self._lock:
            self.assignment = {
                "room_id": payload.get("room_id", ""),
                "room_name": primary.room_name if primary else "",
                "primary": primary.to_dict() if primary else None,
                "updated_at": utc_now_iso(),
                "files": written,
            }
        self.discovery.announce_now()
        self.logger(f"Join target updated: {primary.host + ':' + str(primary.port) if primary else 'unassigned'}")
        return {"ok": True, "written": written, "assignment": dict(self.assignment)}

    def _api_write_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        filename = str(payload.get("filename") or "lika_custom.cfg")
        commands = [str(item) for item in (payload.get("commands") or [])]
        cvars = [(str(k), str(v)) for k, v in (payload.get("cvars") or [])]
        managers = self._managers_for(payload.get("game"))
        if not managers:
            return {"ok": False, "error": "game not installed on this PC"}
        written = []
        for _game, manager in managers:
            if cvars:
                written.append(manager.write_match(
                    cvars, commands, filename=filename,
                ))
            elif commands:
                written.append(manager.write_commands(filename, commands))
        return {"ok": True, "written": written}

    def _api_launch_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        game = str(payload.get("game") or "cs2")
        self.refresh_installs()
        install = self.installs.get(game)
        if not install:
            return {"ok": False, "error": f"{game} not installed on {self.label}; detect paths in Settings."}
        room_id = str(payload.get("id") or payload.get("room_id") or "room")
        cvars_payload = payload.get("cvars")
        if cvars_payload:
            cvars = [(str(k), str(v)) for k, v in cvars_payload]
        else:
            cvars = build_match_cvars(
                payload.get("rules") or {}, game,
                str(payload.get("preset") or "5vs5"),
                int(payload.get("slots") or 10), bool(payload.get("overtime", True)),
            )
        managers = self._managers_for(game)
        if not managers:
            return {"ok": False, "error": "cfg folder missing"}
        cfg_path = managers[0][1].write_match(cvars, filename=LIKA_MATCH)
        argv, workdir = build_server_argv(install.to_dict(), payload)
        self.logger("Launching official LAN server: " + " ".join(redact(argv)))
        try:
            process = launch_process(argv, workdir,
                                     hide_console=bool(payload.get("server_mode") == "dedicated"))
        except OSError as exc:
            return {"ok": False, "error": f"could not start game: {exc}"}
        item = LaunchedProcess(room_id=room_id, pid=process.pid, game=game,
                               kind=str(payload.get("server_mode") or "listen"),
                               started_at=time.time(), command=redact(argv))
        self.registry.track(item, process)
        pids = [process.pid]

        # Dedicated CS 1.6: also start the local client so the host PC can play.
        if game == "cs16" and payload.get("server_mode") == "dedicated" and install.server_exe:
            client_argv = build_client_argv(install.to_dict(), game, "127.0.0.1",
                                            int(payload.get("port") or 27015))
            try:
                client = launch_process(client_argv, workdir)
                self.registry.track(LaunchedProcess(
                    room_id=room_id, pid=client.pid, game=game, kind="client",
                    started_at=time.time(), command=client_argv), client)
                pids.append(client.pid)
            except OSError as exc:
                self.logger(f"could not start host client: {exc}")

        with self._lock:
            self.servers[room_id] = {
                "room_id": room_id, "room_name": str(payload.get("name") or "Room"),
                "game": game, "map": str(payload.get("map") or "de_dust2"),
                "preset": str(payload.get("preset") or "custom"),
                "host": primary_ipv4(), "port": int(payload.get("port") or 27015),
                "state": "live", "pids": pids, "started_at": utc_now_iso(),
            }
        self.discovery.announce_now()
        return {"ok": True, "pid": process.pid, "pids": pids, "argv": redact(argv),
                "cfg": cfg_path, "host": primary_ipv4()}

    def _api_stop_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        room_id = str(payload.get("room_id") or payload.get("id") or "")
        stopped = self.registry.stop(room_id)
        with self._lock:
            self.servers.pop(room_id, None)
        self.discovery.announce_now()
        return {"ok": True, "stopped": stopped}

    def _api_rcon(self, payload: dict[str, Any]) -> dict[str, Any]:
        game = str(payload.get("game") or "cs2")
        host = str(payload.get("host") or "127.0.0.1")
        port = int(payload.get("port") or 27015)
        password = str(payload.get("password") or "")
        commands = [str(item) for item in (payload.get("commands") or [])]
        if not commands:
            return {"ok": False, "error": "no RCON commands supplied"}
        if not password:
            return {"ok": False, "error": "missing rcon_password for this room"}
        results = execute_commands(game, host, port, password, commands,
                                   timeout=float(payload.get("timeout") or 3.0))
        response = {"ok": all(item["ok"] for item in results), "results": results}
        if payload.get("parse_status") or any(cmd.strip() == "status" for cmd in commands):
            combined = "\n".join(str(item.get("response", "")) for item in results)
            response["players"] = parse_status(combined)
        return response

    def _api_steam_connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        game = str(payload.get("game") or "cs2")
        install = self.installs.get(game)
        report = launch_and_connect(
            install.to_dict() if install else None, game,
            str(payload.get("host") or "127.0.0.1"),
            int(payload.get("port") or 27015),
            str(payload.get("password") or ""),
            launch_game=bool(payload.get("launch_game", True)),
            use_fallback=bool(payload.get("fallback", False)),
        )
        self.logger(f"steam://connect -> {report.get('url')} (opened={report.get('opened')})")
        return {"ok": bool(report.get("opened")), **report}

    def _api_close_game(self, payload: dict[str, Any]) -> dict[str, Any]:
        room_id = str(payload.get("room_id") or "")
        if room_id:
            pids = self.registry.stop(room_id)
            with self._lock:
                self.servers.pop(room_id, None)
            self.discovery.announce_now()
            return {"ok": True, "stopped": pids}
        if not payload.get("all_matching") or not payload.get("confirm"):
            return {"ok": False, "error": "closing all games requires explicit operator confirmation"}
        names = tuple(str(item) for item in (payload.get("names") or ("cs2.exe", "hl.exe", "hlds.exe")))
        closed = []
        for process in matching_game_processes(names):
            if graceful_close_process(process["pid"]):
                closed.append(process)
        return {"ok": True, "closed": closed}

    def _api_set_label(self, payload: dict[str, Any]) -> dict[str, Any]:
        label = str(payload.get("label") or "").strip()[:48]
        if not label:
            return {"ok": False, "error": "label cannot be empty"}
        self.label = label
        self.store.update({"station_label": label})
        self.settings = self.store.get()
        self._save_identity()
        self.discovery.announce_now()
        return {"ok": True, "label": label}

    def _api_sync_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {key for key in self.settings.to_dict() if key in payload}
        changes = {key: payload[key] for key in allowed}
        self.settings = self.store.update(changes)
        # Hot-swap the LAN key without restarting the sockets.
        self.auth.key = self.settings.lan_key
        self.discovery.lan_key = self.settings.lan_key
        self.refresh_installs()
        for game, manager in self.managers.items():
            manager.install(self.settings.join_word, self.settings.f10_key,
                            self.settings.enable_f10_bind)
        self.discovery.announce_now()
        return {"ok": True, "settings": self.settings.to_dict()}

    # ------------------------------------------------------------- updater
    def _api_update_begin(self, payload: dict[str, Any]) -> dict[str, Any]:
        transfer_id = short_id(10)
        version = str(payload.get("version") or "unknown")
        target = data_path("updates") / f"LIKAcs-{version}-{transfer_id}.exe.new"
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = open(target, "wb")
        self.transfers[transfer_id] = {
            "path": str(target), "handle": handle, "written": 0,
            "size": int(payload.get("size") or 0),
            "sha256": str(payload.get("sha256") or ""),
            "version": version,
        }
        return {"ok": True, "id": transfer_id, "version": version}

    def _api_update_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        transfer_id = str(payload.get("id") or "")
        transfer = self.transfers.get(transfer_id)
        if not transfer:
            return {"ok": False, "error": "unknown transfer id"}
        offset = int(payload.get("offset") or 0)
        if offset != transfer["written"]:
            return {"ok": False, "error": "out-of-order chunk"}
        try:
            data = base64.b64decode(payload.get("data") or "", validate=True)
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": f"bad chunk encoding: {exc}"}
        transfer["handle"].write(data)
        transfer["written"] += len(data)
        return {"ok": True, "received": transfer["written"]}

    def _api_update_finish(self, payload: dict[str, Any]) -> dict[str, Any]:
        transfer_id = str(payload.get("id") or "")
        transfer = self.transfers.pop(transfer_id, None)
        if not transfer:
            return {"ok": False, "error": "unknown transfer id"}
        try:
            transfer["handle"].close()
        except OSError:
            pass
        path = transfer["path"]
        digest = sha256_file(path)
        if transfer["sha256"] and digest != transfer["sha256"]:
            Path(path).unlink(missing_ok=True)
            return {"ok": False, "error": "SHA-256 mismatch, update rejected"}
        if transfer["size"] and Path(path).stat().st_size != transfer["size"]:
            Path(path).unlink(missing_ok=True)
            return {"ok": False, "error": "size mismatch, update rejected"}
        self.pending_update = {
            "version": transfer["version"], "path": path, "sha256": digest,
            "size": transfer["written"], "staged_at": utc_now_iso(),
        }
        save_json(data_path("pending-update.json"), self.pending_update)
        result: dict[str, Any] = {"ok": True, "staged": True, **self.pending_update}
        if payload.get("restart"):
            swap = stage_swap(current_executable(), path, os.getpid(),
                              "--mode=station --silent")
            result["swap"] = swap
            result["restarting"] = bool(swap.get("ok"))
            if swap.get("ok"):
                self.restart_agent()
        self.discovery.announce_now()
        return result

    def _api_update_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "version": VERSION, "pending": self.pending_update,
                "transfers": {key: {"written": value["written"], "version": value["version"]}
                              for key, value in self.transfers.items()}}
