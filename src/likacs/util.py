"""Small, dependency-free helpers (paths, JSON, networking, hashing, versions)."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

__all__ = [
    "IS_WINDOWS", "CREATE_NO_WINDOW", "app_data_dir", "data_path",
    "atomic_write_text", "atomic_write_bytes", "load_json", "save_json",
    "local_ipv4_addresses", "broadcast_addresses", "sha256_bytes",
    "sha256_file", "parse_version", "version_is_newer", "short_id", "slug",
    "utc_now_iso", "format_duration", "open_url", "run_quiet",
    "get_local_hostname", "primary_ipv4", "safe_int",
]


def app_data_dir() -> Path:
    """Per-user writable state directory (roaming on Windows)."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "LIKAcs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_path(name: str) -> Path:
    return app_data_dir() / name


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    """Crash-safe write: same-directory temp file + os.replace()."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".likacs-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return target


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def load_json(path: str | Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return default


def save_json(path: str | Path, value: Any) -> Path:
    return atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _valid_mask(text: str) -> bool:
    try:
        bits = int(ipaddress.IPv4Address(text))
    except ipaddress.AddressValueError:
        return False
    inverted = bits ^ 0xFFFFFFFF
    return inverted and ((inverted & (inverted + 1)) == 0)


def get_local_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "STATION"


def _windows_ipconfig_interfaces() -> list[tuple[str, str]]:
    """Parse `ipconfig /all` for IPv4 + subnet mask pairs (locale tolerant)."""
    if not IS_WINDOWS:
        return []
    try:
        proc = subprocess.run(
            ["ipconfig", "/all"], capture_output=True, text=True,
            errors="ignore", timeout=8, creationflags=CREATE_NO_WINDOW,
        )
        raw = proc.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []
    quad = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
    pairs: list[tuple[str, str]] = []
    pending_ip: str | None = None
    for line in raw.splitlines():
        found = quad.findall(line)
        if not found:
            continue
        lower = line.lower()
        looks_like_mask = "mask" in lower or "masque" in lower or "máscara" in lower
        for value in found:
            if value.startswith("127."):
                continue
            if looks_like_mask or _valid_mask(value):
                if pending_ip:
                    pairs.append((pending_ip, value))
                    pending_ip = None
            elif not value.startswith("255."):
                pending_ip = value
    return pairs


def local_ipv4_addresses() -> list[str]:
    """All non-loopback IPv4 addresses of this machine, best effort."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(get_local_hostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    # UDP connect does not send a packet; it only asks the OS for the route.
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1, no traffic leaves the host
        ip = probe.getsockname()[0]
        if not ip.startswith("127."):
            found.add(ip)
        probe.close()
    except OSError:
        pass
    for ip, _mask in _windows_ipconfig_interfaces():
        found.add(ip)
    return sorted(found)


def primary_ipv4() -> str:
    ips = local_ipv4_addresses()
    return ips[0] if ips else "127.0.0.1"


def broadcast_addresses() -> list[str]:
    """Global + directed broadcast addresses for every detected LAN interface."""
    result: list[str] = ["255.255.255.255"]
    interfaces = _windows_ipconfig_interfaces()
    for ip, mask in interfaces:
        try:
            network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            result.append(str(network.broadcast_address))
        except (ipaddress.AddressValueError, ValueError):
            pass
    for ip in local_ipv4_addresses():
        try:
            result.append(str(ipaddress.IPv4Network(f"{ip}/24", strict=False).broadcast_address))
        except ValueError:
            pass
    seen: set[str] = set()
    ordered: list[str] = []
    for address in result:
        if address not in seen:
            seen.add(address)
            ordered.append(address)
    return ordered


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_version(text: str) -> tuple[int, ...]:
    """Turn 'v1.2.3-beta' into (1, 2, 3) for a safe comparison."""
    cleaned = (text or "").strip().lstrip("vV")
    numbers = re.findall(r"\d+", cleaned.split("-")[0].split("+")[0])
    return tuple(int(part) for part in numbers[:4]) or (0,)


def version_is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def short_id(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


def slug(text: str, default: str = "item") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "").strip())
    return cleaned.strip("_")[:48] or default


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def open_url(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def run_quiet(argv: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    """Run a helper without flashing a console window on Windows."""
    return subprocess.run(
        argv, capture_output=True, text=True, errors="ignore", timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def safe_int(value: Any, default: int, low: int = 1, high: int = 65535) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if low <= number <= high else default
