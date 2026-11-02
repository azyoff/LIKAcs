"""HMAC authentication for LAN discovery packets and control requests.

The LAN key is a shared secret configured once on the laptop and on every
station. Every message carries a timestamp and a random nonce; signatures
cover the exact request bytes. Replays are rejected by a bounded nonce cache.
This keeps cafe PCs from accepting commands from random devices on the LAN.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any

from .protocol import HEADERS, MAGIC

DEFAULT_LAN_KEY = "lika-lan"
SKEW_SECONDS = 90
NONCE_TTL = 180

__all__ = ["DEFAULT_LAN_KEY", "LanAuth", "canonical_json", "sign_packet", "verify_packet", "AuthError"]


class AuthError(Exception):
    """Raised when an inbound message is unsigned, stale or replayed."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(key: str, timestamp: int, nonce: str, payload: bytes) -> str:
    message = f"{timestamp}\n{nonce}\n".encode("utf-8") + payload
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


class NonceCache:
    """Thread-safe, size/time bounded replay protection."""

    def __init__(self, ttl: float = NONCE_TTL, max_items: int = 4096) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._items: dict[str, float] = {}
        self._lock = threading.Lock()

    def accept(self, nonce: str) -> bool:
        now = time.time()
        with self._lock:
            if len(self._items) > self.max_items:
                for key, added in list(self._items.items()):
                    if now - added > self.ttl:
                        del self._items[key]
            if nonce in self._items:
                return False
            self._items[nonce] = now
            return True


class LanAuth:
    """Sign outbound HTTP requests and verify inbound ones."""

    def __init__(self, key: str | None = None, skew: int = SKEW_SECONDS) -> None:
        self.key = key or DEFAULT_LAN_KEY
        self.skew = skew
        self.nonces = NonceCache()

    def headers_for(self, payload: bytes) -> dict[str, str]:
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        return {
            HEADERS["ts"]: timestamp,
            HEADERS["nonce"]: nonce,
            HEADERS["signature"]: _digest(self.key, int(timestamp), nonce, payload),
            HEADERS["keyhint"]: hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:8],
        }

    def verify(self, headers: dict[str, str], payload: bytes) -> None:
        # HTTP header names are case-insensitive; normalize once.
        normalized = {str(key).lower(): str(value) for key, value in headers.items()}

        def header(name: str) -> str:
            return normalized.get(name.lower(), "")

        try:
            timestamp = int(header(HEADERS["ts"]))
        except ValueError as exc:
            raise AuthError("missing or invalid timestamp") from exc
        nonce = header(HEADERS["nonce"])
        signature = header(HEADERS["signature"])
        if not nonce or not signature:
            raise AuthError("missing signature")
        if abs(time.time() - timestamp) > self.skew:
            raise AuthError("stale timestamp (check the PC clocks)")
        expected = _digest(self.key, timestamp, nonce, payload)
        if not hmac.compare_digest(expected, signature):
            raise AuthError("bad signature (LAN key mismatch?)")
        if not self.nonces.accept(nonce):
            raise AuthError("replayed request")


def sign_packet(packet: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a copy with magic/timestamp/nonce/signature fields."""
    body = {k: v for k, v in packet.items() if not k.startswith("_")}
    body["magic"] = MAGIC
    timestamp = int(time.time())
    nonce = secrets.token_hex(12)
    signature = _digest(key, timestamp, nonce, canonical_json(body).encode("utf-8"))
    return {**body, "_ts": timestamp, "_nonce": nonce, "_sig": signature}


def verify_packet(packet: dict[str, Any], key: str, cache: NonceCache | None = None,
                  skew: int = SKEW_SECONDS) -> dict[str, Any]:
    """Validate a discovery packet. Raises AuthError on any problem."""
    if not isinstance(packet, dict) or packet.get("magic") != MAGIC:
        raise AuthError("not a LIKAcs packet")
    try:
        timestamp = int(packet["_ts"])
        nonce = str(packet["_nonce"])
        signature = str(packet["_sig"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("incomplete signature fields") from exc
    if abs(time.time() - timestamp) > skew:
        raise AuthError("stale discovery packet")
    body = {k: v for k, v in packet.items() if not k.startswith("_")}
    expected = _digest(key, timestamp, nonce, canonical_json(body).encode("utf-8"))
    if not hmac.compare_digest(expected, signature):
        raise AuthError("bad discovery signature")
    if cache is not None and not cache.accept(nonce):
        raise AuthError("replayed discovery packet")
    return body
