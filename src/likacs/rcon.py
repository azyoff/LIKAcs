"""Official RCON clients: Source RCON (CS2, TCP) and GoldSrc RCON (CS 1.6, UDP).

RCON is a first-party server feature enabled with -usercon + rcon_password.
No memory access, no injection, no binary modification.
"""

from __future__ import annotations

import re
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any

__all__ = ["RconError", "SourceRcon", "GoldSrcRcon", "make_rcon", "parse_status"]

# Source RCON packet types
SERVERDATA_RESPONSE_VALUE = 0
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_AUTH = 3

CONNECTION_CLOSED = b"\xff\xff\xff\xff"
GOLDSRC_PREFIX = b"\xff\xff\xff\xff"


class RconError(Exception):
    pass


@dataclass
class _Packet:
    request_id: int
    kind: int
    body: str


def encode_packet(request_id: int, kind: int, body: str) -> bytes:
    payload = body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<iii", 4 + 4 + len(payload), request_id, kind) + payload


def decode_packets(data: bytes) -> list[_Packet]:
    packets: list[_Packet] = []
    offset = 0
    while offset + 12 <= len(data):
        size = struct.unpack_from("<i", data, offset)[0]
        if size < 10 or offset + 4 + size > len(data):
            break
        request_id, kind = struct.unpack_from("<ii", data, offset + 4)
        body = data[offset + 12: offset + 4 + size].rstrip(b"\x00")
        packets.append(_Packet(request_id, kind, body.decode("utf-8", "replace")))
        offset += 4 + size
    return packets


class SourceRcon:
    """Source RCON over TCP (CS2 / CS:GO / modern HLDS)."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 3.0) -> None:
        self.host, self.port, self.password = host, int(port), password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._next_id = 1

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def connect(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise RconError(f"cannot connect to RCON {self.host}:{self.port}: {exc}") from exc
        sock.settimeout(self.timeout)
        self._sock = sock
        auth_id = self._id()
        sock.sendall(encode_packet(auth_id, SERVERDATA_AUTH, self.password))
        deadline = time.monotonic() + self.timeout + 1.0
        chunks = b""
        while time.monotonic() < deadline:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            chunks += data
            if len(chunks) > 1024 * 1024:
                break
            for packet in decode_packets(chunks):
                if packet.kind == SERVERDATA_AUTH_RESPONSE:
                    if packet.request_id == -1:
                        self.close()
                        raise RconError("bad rcon_password (check the room's RCON password)")
                    return
            # Keep partial packet bytes: the next recv() completes them.
        self.close()
        raise RconError("RCON authentication timed out (is -usercon enabled?)")

    def _drain(self, sock: socket.socket, first: bytes) -> str:
        """Collect a possibly multi-packet response."""
        chunks = first
        deadline = time.monotonic() + min(2.0, self.timeout)
        sock.settimeout(0.25)
        while time.monotonic() < deadline:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            chunks += data
            if decode_packets(chunks) and decode_packets(chunks)[-1].body == "":
                break
        return "\n".join(p.body for p in decode_packets(chunks) if p.kind == SERVERDATA_RESPONSE_VALUE)

    def command(self, command: str) -> str:
        if self._sock is None:
            self.connect()
        sock = self._sock
        assert sock is not None
        request_id = self._id()
        try:
            sock.sendall(encode_packet(request_id, SERVERDATA_EXECCOMMAND, command))
            sock.settimeout(self.timeout)
            first = sock.recv(65536)
            if not first:
                raise RconError("RCON connection closed by server")
            return self._drain(sock, first)
        except socket.timeout as exc:
            raise RconError(f"RCON timed out for '{command}'") from exc
        except OSError as exc:
            self.close()
            raise RconError(f"RCON error: {exc}") from exc

    def execute(self, commands: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            self.connect()
            for command in commands:
                try:
                    response = self.command(command)
                    results.append({"command": command, "response": response, "ok": True})
                except RconError as exc:
                    results.append({"command": command, "response": "", "ok": False, "error": str(exc)})
        finally:
            self.close()
        return results

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class GoldSrcRcon:
    """GoldSrc UDP challenge/response RCON (CS 1.6 / HLDS)."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 2.0) -> None:
        self.host, self.port, self.password = host, int(port), password
        self.timeout = timeout

    def _exchange(self, payload: bytes, collect: float = 0.0) -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        try:
            sock.sendto(GOLDSRC_PREFIX + payload, (self.host, self.port))
            try:
                first, _ = sock.recvfrom(65535)
            except socket.timeout as exc:
                raise RconError("no RCON reply (is -usercon + rcon_password set?)") from exc
            parts = [first]
            if collect:
                sock.settimeout(collect)
                while True:
                    try:
                        data, _ = sock.recvfrom(65535)
                    except socket.timeout:
                        break
                    parts.append(data)
            return b"".join(parts)
        finally:
            sock.close()

    def challenge(self) -> str:
        for request in (b"challenge rcon\n", b"getchallenge\n", b"challenge rcon\n\x00"):
            try:
                raw = self._exchange(request)
            except RconError:
                continue
            match = re.search(rb"rcon\s+(\d+)", raw)
            if match:
                return match.group(1).decode("ascii")
        raise RconError("could not obtain a GoldSrc RCON challenge")

    def command(self, command: str) -> str:
        challenge = self.challenge()
        password = self.password.replace('"', "'").encode("utf-8")
        payload = b'rcon ' + challenge.encode("ascii") + b' "' + password + b'" ' + command.encode("utf-8") + b"\n"
        raw = self._exchange(payload, collect=0.35)
        pieces: list[str] = []
        for part in raw.split(GOLDSRC_PREFIX):
            if not part:
                continue
            text = part[1:] if part[:1] in (b"l", b"n") else part  # HLDS packet marker
            pieces.append(text.decode("latin-1", "replace").strip("\x00\n"))
        return "\n".join(piece for piece in pieces if piece).strip()

    def execute(self, commands: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for command in commands:
            try:
                response = self.command(command)
                lowered = response.lower()
                failed = "bad rcon" in lowered or "invalid password" in lowered
                results.append({
                    "command": command, "response": response, "ok": not failed,
                    "error": "bad rcon_password" if failed else None,
                })
            except RconError as exc:
                results.append({"command": command, "response": "", "ok": False, "error": str(exc)})
        return results


def make_rcon(game: str, host: str, port: int, password: str, timeout: float = 3.0):
    if game == "cs16":
        return GoldSrcRcon(host, port, password, timeout=min(timeout, 2.0))
    return SourceRcon(host, port, password, timeout=timeout)


def execute_commands(game: str, host: str, port: int, password: str,
                     commands: list[str], timeout: float = 3.0) -> list[dict[str, Any]]:
    """Run commands with the game's native RCON; HLDS falls back to Source RCON."""
    primary = make_rcon(game, host, port, password, timeout)
    results = primary.execute(commands)
    if game == "cs16" and results and all(not item["ok"] for item in results):
        # Post-2020 HLDS builds also accept Source RCON over TCP when -usercon is set.
        fallback = SourceRcon(host, port, password, timeout=timeout)
        fallback_results = fallback.execute(commands)
        if any(item["ok"] for item in fallback_results):
            return fallback_results
    return results


IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})(?::(\d+))?")


def parse_status(output: str) -> list[dict[str, Any]]:
    """Parse `status` output into players, so PCs can be kicked by LAN IP."""
    players: list[dict[str, Any]] = []
    for line in (output or "").splitlines():
        if not line.lstrip().startswith("#"):
            continue
        match = re.search(r'#\s+(\d+)\s+\d+\s+"([^"]*)"\s+(\S+)', line)
        ip_match = IP_RE.search(line)
        userid = match.group(1) if match else ""
        name = match.group(2) if match else ""
        uniqueid = match.group(3) if match else ""
        if not userid and not ip_match:
            continue
        players.append({
            "userid": userid, "name": name, "uniqueid": uniqueid,
            "ip": ip_match.group(1) if ip_match else "",
            "port": int(ip_match.group(2)) if ip_match and ip_match.group(2) else 0,
            "raw": line.strip(),
        })
    return players
