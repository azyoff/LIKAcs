"""GitHub Releases update check + one-click push to every LAN Station PC.

* Laptop checks the latest release (public GitHub REST API, no extra deps).
* The .exe asset is downloaded and verified against SHA256SUMS.txt.
* The verified binary is streamed in signed chunks to each Station Agent.
* Each agent stages a safe swap (Windows cannot overwrite a running .exe) and
  restarts silently when the operator confirms.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import VERSION
from .protocol import EP_UPDATE_BEGIN, EP_UPDATE_CHUNK, EP_UPDATE_FINISH, UPDATE_CHUNK_SIZE
from .util import (CREATE_NO_WINDOW, IS_WINDOWS, atomic_write_text, data_path,
                   sha256_bytes, sha256_file, version_is_newer)

Progress = Callable[[str, int, int, str], None]


@dataclass
class Release:
    tag: str
    name: str = ""
    body: str = ""
    html_url: str = ""
    published_at: str = ""
    assets: list[dict[str, Any]] = field(default_factory=list)

    def asset(self, name: str) -> dict[str, Any] | None:
        for item in self.assets:
            if str(item.get("name", "")).lower() == name.lower():
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag, "name": self.name, "body": self.body,
            "html_url": self.html_url, "published_at": self.published_at,
            "assets": [{"name": a.get("name"), "size": a.get("size"),
                        "url": a.get("browser_download_url")} for a in self.assets],
        }


def parse_release(raw: dict[str, Any]) -> Release:
    assets = []
    for asset in raw.get("assets", []) or []:
        assets.append({
            "name": str(asset.get("name", "")),
            "size": int(asset.get("size", 0) or 0),
            "browser_download_url": str(asset.get("browser_download_url", "")),
            "digest": str(asset.get("digest", "") or ""),
        })
    return Release(
        tag=str(raw.get("tag_name", "")), name=str(raw.get("name", "") or ""),
        body=str(raw.get("body", "") or ""), html_url=str(raw.get("html_url", "") or ""),
        published_at=str(raw.get("published_at", "") or ""), assets=assets,
    )


class UpdateManager:
    def __init__(self, owner: str, repo: str, current_version: str = VERSION,
                 opener: Callable[..., Any] | None = None) -> None:
        self.owner = owner.strip() or "azyoff"
        self.repo = repo.strip() or "LIKAcs"
        self.current_version = current_version
        self._opener = opener  # injectable for offline unit tests

    @property
    def api_url(self) -> str:
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"

    def _fetch(self, url: str, timeout: float = 12.0) -> bytes:
        request = urllib.request.Request(url, headers={
            "User-Agent": f"LIKAcs/{self.current_version}",
            "Accept": "application/vnd.github+json",
        })
        if self._opener is not None:
            response = self._opener(request, timeout=timeout)
            if hasattr(response, "read"):
                return response.read()
            return bytes(response)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def check(self) -> dict[str, Any]:
        raw = json.loads(self._fetch(self.api_url).decode("utf-8"))
        release = parse_release(raw)
        return {
            "ok": True,
            "current": self.current_version,
            "latest": release.tag,
            "update_available": bool(release.tag) and version_is_newer(release.tag, self.current_version),
            "release": release,
        }

    def expected_sha256(self, release: Release, asset_name: str) -> str:
        asset = release.asset(asset_name)
        if asset and asset.get("digest", "").startswith("sha256:"):
            return asset["digest"].split(":", 1)[1].lower()
        checksums = release.asset("SHA256SUMS.txt")
        if checksums and checksums.get("browser_download_url"):
            try:
                text = self._fetch(checksums["browser_download_url"]).decode("utf-8", "replace")
            except (OSError, urllib.error.URLError):
                return ""
            for line in text.splitlines():
                match = re.match(r"([a-fA-F0-9]{64})\s+\*?(.+)", line.strip())
                if match and Path(match.group(2)).name.lower() == asset_name.lower():
                    return match.group(1).lower()
        return ""

    def download(self, release: Release, asset_name: str = "LIKAcs.exe",
                 dest: str | None = None,
                 progress: Progress | None = None) -> dict[str, Any]:
        asset = release.asset(asset_name)
        if not asset or not asset.get("browser_download_url"):
            return {"ok": False, "error": f"release has no {asset_name} asset"}
        target = Path(dest) if dest else data_path("updates") / f"{release.tag}-{asset_name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(asset["browser_download_url"], headers={
            "User-Agent": f"LIKAcs/{self.current_version}",
        })
        total = int(asset.get("size", 0) or 0)
        downloaded = 0
        chunks: list[bytes] = []
        if self._opener is not None:
            raw = self._opener(request, timeout=60)
            chunks = [raw.read() if hasattr(raw, "read") else bytes(raw)]
        else:
            with urllib.request.urlopen(request, timeout=60) as response:
                while True:
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    chunks.append(block)
                    downloaded += len(block)
                    if progress:
                        progress("download", downloaded, total or downloaded, release.tag)
        data = b"".join(chunks)
        digest = sha256_bytes(data)
        expected = self.expected_sha256(release, asset_name)
        if expected and digest != expected:
            return {"ok": False, "error": "SHA-256 mismatch - download discarded",
                    "sha256": digest, "expected": expected}
        target.write_bytes(data)
        return {"ok": True, "path": str(target), "size": len(data),
                "sha256": digest, "verified": bool(expected), "version": release.tag}


def build_swap_script(target: str, staged: str, pid: int, args: str = "--mode=station --silent") -> str:
    """Windows batch helper: waits for the running exe to exit, swaps, restarts."""
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "TARGET={target}"\r\n'
        f'set "STAGED={staged}"\r\n'
        f'set "PID={int(pid)}"\r\n'
        ":wait\r\n"
        'tasklist /FI "PID eq %PID%" /NH | find "%PID%" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'move /Y "%STAGED%" "%TARGET%"\r\n'
        f'start "" "%TARGET%" {args}\r\n'
        'start /b cmd /c del "%~f0"\r\n'
        "endlocal\r\n"
    )


def stage_swap(target: str, staged: str, pid: int,
               args: str = "--mode=station --silent") -> dict[str, Any]:
    """Write and launch the swap helper. The caller should exit right after."""
    if not IS_WINDOWS:
        return {"ok": False, "error": "Automatic .exe swap requires Windows"}
    script = Path(tempfile.gettempdir()) / "LIKAcs" / f"likacs-update-{pid}.cmd"
    atomic_write_text(script, build_swap_script(target, staged, pid, args))
    try:
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True, "script": str(script), "target": target, "staged": staged}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def push_update(client: Any, stations: list[dict[str, Any]], asset_path: str,
                version: str, progress: Progress | None = None,
                restart_agents: bool = False,
                timeout: float = 30.0) -> dict[str, Any]:
    """Stream a verified .exe to every station agent over the signed LAN API."""
    path = Path(asset_path)
    if not path.is_file():
        return {"ok": False, "error": f"missing update file: {asset_path}"}
    size = path.stat().st_size
    digest = sha256_file(path)
    results: list[dict[str, Any]] = []
    for station in stations:
        host = station.get("ip") or station.get("host")
        port = int(station.get("agent_port", 27056))
        label = station.get("label") or station.get("hostname") or str(host)
        if not host:
            results.append({"id": station.get("id"), "label": label, "ok": False,
                            "error": "no LAN IP"})
            continue
        try:
            begin = client.request(host, port, EP_UPDATE_BEGIN,
                                   {"version": version, "size": size,
                                    "sha256": digest, "filename": path.name},
                                   timeout=timeout)
            transfer_id = begin.get("id", "")
            sent = 0
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(UPDATE_CHUNK_SIZE)
                    if not chunk:
                        break
                    client.request(host, port, EP_UPDATE_CHUNK, {
                        "id": transfer_id, "offset": sent,
                        "data": base64.b64encode(chunk).decode("ascii"),
                    }, timeout=timeout)
                    sent += len(chunk)
                    if progress:
                        progress(label, sent, size, version)
            finish = client.request(host, port, EP_UPDATE_FINISH,
                                    {"id": transfer_id, "restart": restart_agents},
                                    timeout=timeout)
            results.append({"id": station.get("id"), "label": label, "host": host,
                            "ok": bool(finish.get("ok", True)), "detail": finish})
        except Exception as exc:
            results.append({"id": station.get("id"), "label": label, "host": host,
                            "ok": False, "error": str(exc)})
    return {
        "ok": all(item["ok"] for item in results) if results else False,
        "version": version, "sha256": digest, "size": size, "results": results,
    }
