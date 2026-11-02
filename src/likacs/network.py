"""UDP broadcast LAN discovery (DHCP-proof, zero static IPs).

Station Agents heartbeat every 2 seconds. Control Centers listen and send
signed probes so quiet stations answer immediately. Every packet is HMAC signed
with the cafe LAN key, so random devices on the switch cannot inject stations
or commands.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, Callable

from .protocol import (HEARTBEAT_INTERVAL, MSG_BYE, MSG_HELLO, MSG_PROBE,
                       PROBE_INTERVAL, STATION_TIMEOUT)
from .security import AuthError, NonceCache, sign_packet, verify_packet
from .util import broadcast_addresses, get_local_hostname, primary_ipv4

OnMessage = Callable[[dict[str, Any], tuple[str, int]], None]

__all__ = ["DiscoveryService", "StationTable"]


class DiscoveryService:
    """One UDP socket per process: sends heartbeats and/or receives packets."""

    def __init__(self, port: int, lan_key: str,
                 heartbeat_factory: Callable[[], dict[str, Any]] | None = None,
                 on_message: OnMessage | None = None,
                 probe: bool = False,
                 broadcast_targets: list[str] | None = None,
                 logger: Callable[[str], None] | None = None) -> None:
        self.port = int(port)
        self.lan_key = lan_key
        self.heartbeat_factory = heartbeat_factory
        self.on_message = on_message
        self.probe_enabled = probe
        self.broadcast_targets = broadcast_targets
        self.logger = logger or (lambda _msg: None)
        self.nonce_cache = NonceCache()
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._send_lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.port))
            sock.settimeout(0.4)
        except OSError:
            sock.close()
            raise
        self._sock = sock
        self._stop.clear()
        self._threads.append(threading.Thread(target=self._listen_loop, name="likacs-udp-listen", daemon=True))
        if self.heartbeat_factory is not None:
            self._threads.append(threading.Thread(target=self._heartbeat_loop, name="likacs-udp-heartbeat", daemon=True))
        if self.probe_enabled:
            self._threads.append(threading.Thread(target=self._probe_loop, name="likacs-udp-probe", daemon=True))
        for thread in self._threads:
            thread.start()
        self.logger(f"LAN discovery listening on UDP {self.port}")

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                if self.heartbeat_factory is not None:
                    self._broadcast({"kind": MSG_BYE, "id": (self.heartbeat_factory() or {}).get("id", "")})
            except Exception:
                pass
        for thread in self._threads:
            thread.join(timeout=1.5)
        self._threads.clear()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def running(self) -> bool:
        return self._sock is not None and not self._stop.is_set()

    # ---------------------------------------------------------------- sending
    def targets(self) -> list[str]:
        if self.broadcast_targets is not None:
            return self.broadcast_targets
        try:
            return broadcast_addresses()
        except Exception:
            return ["255.255.255.255"]

    def _send_raw(self, packet: dict[str, Any], address: str) -> None:
        if self._sock is None:
            return
        data = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        with self._send_lock:
            try:
                self._sock.sendto(data, (address, self.port))
            except OSError as exc:
                self.logger(f"LAN send to {address}:{self.port} failed: {exc}")

    def _broadcast(self, body: dict[str, Any]) -> None:
        signed = sign_packet(body, self.lan_key)
        for address in self.targets():
            self._send_raw(signed, address)

    def announce_now(self) -> None:
        if self.heartbeat_factory is None:
            return
        self._broadcast(self.heartbeat_factory())

    def send_probe(self) -> None:
        self._broadcast({
            "kind": MSG_PROBE,
            "id": "controller",
            "hostname": get_local_hostname(),
            "ip": primary_ipv4(),
        })

    # ---------------------------------------------------------------- loops
    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            try:
                payload = self.heartbeat_factory()  # type: ignore[misc]
                if payload:
                    self._broadcast(payload)
            except Exception as exc:
                self.logger(f"heartbeat error: {exc}")

    def _probe_loop(self) -> None:
        while not self._stop.wait(PROBE_INTERVAL):
            try:
                self.send_probe()
            except Exception as exc:
                self.logger(f"probe error: {exc}")

    def _listen_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                packet = json.loads(data.decode("utf-8"))
                body = verify_packet(packet, self.lan_key, self.nonce_cache)
            except (ValueError, UnicodeError, AuthError) as exc:
                # Most traffic on a LAN switch is not ours; only log packets
                # that look like ours but failed verification (wrong key, etc.).
                if data.lstrip()[:1] == b"{":
                    self.logger(f"ignored LAN packet from {addr[0]}: {exc}")
                continue
            if self.on_message:
                try:
                    self.on_message(body, addr)
                except Exception as exc:
                    self.logger(f"discovery handler error: {exc}")


class StationTable:
    """Thread-safe view of stations seen recently on the LAN."""

    def __init__(self, timeout: float = STATION_TIMEOUT) -> None:
        self.timeout = timeout
        self._lock = threading.RLock()
        self._stations: dict[str, dict[str, Any]] = {}

    def update(self, station: dict[str, Any]) -> None:
        station_id = str(station.get("id") or "")
        if not station_id:
            return
        with self._lock:
            station = dict(station)
            station["last_seen"] = time.time()
            self._stations[station_id] = station

    def remove(self, station_id: str) -> None:
        with self._lock:
            self._stations.pop(station_id, None)

    def get(self, station_id: str) -> dict[str, Any] | None:
        with self._lock:
            station = self._stations.get(station_id)
            return dict(station) if station else None

    def all(self, include_stale: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            items = [dict(value) for value in self._stations.values()]
        if include_stale:
            return sorted(items, key=lambda item: str(item.get("label", item.get("hostname", ""))))
        fresh = [item for item in items if now - float(item.get("last_seen", 0)) <= self.timeout]
        return sorted(fresh, key=lambda item: str(item.get("label", item.get("hostname", ""))))

    def expire(self) -> list[str]:
        now = time.time()
        expired: list[str] = []
        with self._lock:
            for station_id, station in list(self._stations.items()):
                if now - float(station.get("last_seen", 0)) > self.timeout:
                    del self._stations[station_id]
                    expired.append(station_id)
        return expired
