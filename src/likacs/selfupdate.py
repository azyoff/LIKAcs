"""One-click self-update for an installed LIKAcs.exe, straight from GitHub.

Design goals:
  * ONE button. Check + download + verify + stage + restart in one call.
  * No GitHub API rate limits: reads ``latest.json`` published as a release
    asset at the stable ``/releases/latest/download/`` URL, with the REST API
    as a fallback.
  * Integrity: SHA-256 from the manifest AND from SHA256SUMS.txt must agree.
  * Safety: Windows cannot overwrite a running .exe, so a small helper waits
    for the process to exit, keeps a .bak, verifies the new binary boots
    (``--version``), rolls back automatically on failure, then relaunches with
    the same command line. No admin rights and no UAC.
  * Never swaps ``python.exe``: self-update only works in a frozen build.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import GITHUB_OWNER, GITHUB_REPO, VERSION
from .util import (CREATE_NO_WINDOW, IS_WINDOWS, atomic_write_text, sha256_bytes,
                   utc_now_iso, version_is_newer)

MANIFEST_NAME = "latest.json"
Progress = Callable[[str, int, int, str], None]


def manifest_url(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> str:
    """Stable URL that always resolves to the newest published manifest."""
    return f"https://github.com/{owner}/{repo}/releases/latest/download/{MANIFEST_NAME}"


def release_download_url(tag: str, name: str,
                         owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{name}"


@dataclass
class UpdateInfo:
    version: str
    tag: str
    notes: str = ""
    html_url: str = ""
    published_at: str = ""
    url: str = ""
    sha256: str = ""
    size: int = 0
    setup_url: str = ""
    setup_sha256: str = ""
    checksums_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "tag": self.tag, "notes": self.notes,
            "html_url": self.html_url, "published_at": self.published_at,
            "url": self.url, "sha256": self.sha256, "size": self.size,
            "setup_url": self.setup_url, "setup_sha256": self.setup_sha256,
            "checksums_url": self.checksums_url,
        }


def parse_manifest(raw: dict[str, Any],
                   owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> UpdateInfo:
    """Normalise a latest.json document into an UpdateInfo."""
    tag = str(raw.get("tag") or "").strip()
    version = str(raw.get("version") or tag.lstrip("v") or "").strip()
    if not version:
        raise ValueError("manifest has no version")
    tag = tag or f"v{version}"
    assets = raw.get("assets") or {}
    exe = assets.get("LIKAcs.exe") or {}
    setup = assets.get("LIKAcs-Setup.exe") or {}
    url = str(exe.get("url") or "").strip() or release_download_url(tag, "LIKAcs.exe", owner, repo)
    digest = str(exe.get("sha256") or "").strip().lower()
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("manifest sha256 is not a valid SHA-256 digest")
    checksums = str(raw.get("checksums_url") or "").strip() or release_download_url(
        tag, "SHA256SUMS.txt", owner, repo)
    return UpdateInfo(
        version=version, tag=tag, notes=str(raw.get("notes") or ""),
        html_url=str(raw.get("html_url") or f"https://github.com/{owner}/{repo}/releases/tag/{tag}"),
        published_at=str(raw.get("published_at") or ""),
        url=url, sha256=digest, size=int(exe.get("size") or 0),
        setup_url=str(setup.get("url") or "").strip(),
        setup_sha256=str(setup.get("sha256") or "").strip().lower(),
        checksums_url=checksums,
    )


def build_manifest(tag: str, checksums: dict[str, str], sizes: dict[str, int],
                   notes: str = "", owner: str = GITHUB_OWNER,
                   repo: str = GITHUB_REPO, version: str = VERSION) -> dict[str, Any]:
    """Build the latest.json document attached to every release."""
    def asset(name: str) -> dict[str, Any]:
        return {
            "url": release_download_url(tag, name, owner, repo),
            "sha256": checksums.get(name, "").lower(),
            "size": int(sizes.get(name, 0)),
        }
    return {
        "schema": 1,
        "product": "LIKAcs",
        "version": version,
        "tag": tag,
        "website": "http://likaapps.com",
        "published_at": utc_now_iso(),
        "notes": notes,
        "html_url": f"https://github.com/{owner}/{repo}/releases/tag/{tag}",
        "checksums_url": release_download_url(tag, "SHA256SUMS.txt", owner, repo),
        "assets": {
            name: asset(name) for name in ("LIKAcs.exe", "LIKAcs-Setup.exe")
            if name in checksums
        },
    }


def build_self_swap_script(target: str, staged: str, backup: str, pid: int,
                           args: str = "") -> str:
    """Delayed swap with automatic rollback if the new exe fails to boot."""
    launch = f'start "" "%TARGET%" {args}'.rstrip()
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "TARGET={target}"\r\n'
        f'set "STAGED={staged}"\r\n'
        f'set "BACKUP={backup}"\r\n'
        f'set "PID={int(pid)}"\r\n'
        ":wait\r\n"
        'tasklist /FI "PID eq %PID%" /NH | find "%PID%" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'if exist "%BACKUP%" del /F /Q "%BACKUP%" 2>nul\r\n'
        'copy /Y "%TARGET%" "%BACKUP%" >nul 2>nul\r\n'
        'move /Y "%STAGED%" "%TARGET%" >nul 2>nul\r\n'
        'if not exist "%TARGET%" goto rollback\r\n'
        "rem Boot-check the new build with a hard 20 second timeout.\r\n"
        "rem A broken GUI would hang a plain start /wait forever.\r\n"
        'powershell -NoProfile -NonInteractive -Command "$p=Start-Process -FilePath $env:TARGET -ArgumentList \'--version\' -PassThru; if(-not $p.WaitForExit(20000)){try{$p.Kill()}catch{}; exit 1}; exit $p.ExitCode"\r\n'
        "if errorlevel 1 goto rollback\r\n"
        f"{launch}\r\n"
        "goto cleanup\r\n"
        ":rollback\r\n"
        'move /Y "%BACKUP%" "%TARGET%" >nul 2>nul\r\n'
        f"{launch}\r\n"
        'echo LIKAcs update failed - previous version restored > "%TARGET%.update-failed"\r\n'
        "goto cleanup\r\n"
        ":cleanup\r\n"
        'del /F /Q "%STAGED%" 2>nul\r\n'
        'start /b cmd /c del "%~f0"\r\n'
        "endlocal\r\n"
    )


class SelfUpdater:
    """Check + verify + stage a self-update in one call."""

    def __init__(self, owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO,
                 current_version: str = VERSION, opener: Callable[..., Any] | None = None,
                 timeout: float = 12.0) -> None:
        self.owner = owner
        self.repo = repo
        self.current_version = current_version
        self._opener = opener
        self.timeout = timeout

    @property
    def url(self) -> str:
        return manifest_url(self.owner, self.repo)

    def _fetch(self, url: str, timeout: float | None = None) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": f"LIKAcs/{self.current_version}"})
        if self._opener is not None:
            response = self._opener(request, timeout=timeout or self.timeout)
            return response.read() if hasattr(response, "read") else bytes(response)
        with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
            return response.read()

    def check(self) -> dict[str, Any]:
        """Return update availability. Manifest first, GitHub API as fallback."""
        info: UpdateInfo | None = None
        error = ""
        try:
            info = parse_manifest(json.loads(self._fetch(self.url).decode("utf-8")),
                                  self.owner, self.repo)
        except Exception as exc:
            error = str(exc)
        if info is None:
            try:
                from .update import UpdateManager
                result = UpdateManager(self.owner, self.repo, self.current_version,
                                       opener=self._opener).check()
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "API check failed")
                release = result["release"]
                asset = release.asset("LIKAcs.exe") or {}
                info = UpdateInfo(
                    version=release.tag.lstrip("v"), tag=release.tag,
                    notes=release.body, html_url=release.html_url,
                    published_at=release.published_at,
                    url=str(asset.get("browser_download_url") or ""),
                    sha256=str(asset.get("digest") or "").removeprefix("sha256:").lower(),
                    size=int(asset.get("size") or 0),
                    checksums_url=release_download_url(release.tag, "SHA256SUMS.txt",
                                                       self.owner, self.repo),
                )
            except Exception as exc:
                return {"ok": False, "error": f"{error}; API fallback: {exc}",
                        "current": self.current_version, "update_available": False}
        return {
            "ok": True, "current": self.current_version, "latest": info.tag,
            "update_available": version_is_newer(info.tag, self.current_version),
            "info": info, "source": "manifest" if not error else "api",
        }

    def download_verified(self, info: UpdateInfo, dest: Path,
                          progress: Progress | None = None) -> dict[str, Any]:
        """Download and verify SHA-256 against manifest + SHA256SUMS.txt."""
        if not info.url:
            return {"ok": False, "error": "release has no LIKAcs.exe asset"}
        if not info.sha256:
            return {"ok": False, "error": "manifest has no SHA-256 for LIKAcs.exe"}
        chunks: list[bytes] = []
        request = urllib.request.Request(info.url,
                                         headers={"User-Agent": f"LIKAcs/{self.current_version}"})
        if self._opener is not None:
            response = self._opener(request, timeout=60)
            chunks = [response.read() if hasattr(response, "read") else bytes(response)]
        else:
            with urllib.request.urlopen(request, timeout=60) as response:
                while True:
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    chunks.append(block)
                    if progress:
                        progress("download", sum(len(c) for c in chunks), info.size, info.tag)
        data = b"".join(chunks)
        digest = sha256_bytes(data)
        if digest != info.sha256:
            return {"ok": False, "error": "SHA-256 mismatch - download discarded",
                    "sha256": digest, "expected": info.sha256}
        if info.size and len(data) != info.size:
            return {"ok": False, "error": "unexpected file size - download discarded"}
        # Cross-check the independent checksums file when reachable.
        try:
            text = self._fetch(info.checksums_url).decode("utf-8", "replace")
            for line in text.splitlines():
                match = re.match(r"([a-fA-F0-9]{64})\s+\*?(.+)", line.strip())
                if match and Path(match.group(2)).name.lower() == "likacs.exe":
                    if match.group(1).lower() != digest:
                        return {"ok": False,
                                "error": "SHA256SUMS.txt disagrees with manifest - discarded"}
                    break
        except (OSError, urllib.error.URLError):
            pass  # manifest digest is authoritative; checksums file is optional
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write = dest.parent / (dest.name + ".tmp")
        atomic_write.write_bytes(data)
        os.replace(atomic_write, dest)
        return {"ok": True, "path": str(dest), "size": len(data), "sha256": digest,
                "version": info.tag}

    def stage_swap(self, staged: Path, args: str = "") -> dict[str, Any]:
        """Write and launch the swap helper. Caller must exit immediately after."""
        if not getattr(sys, "frozen", False):
            return {"ok": False, "error": "one-click updates require the installed LIKAcs.exe"}
        if not IS_WINDOWS:
            return {"ok": False, "error": "automatic .exe swap requires Windows"}
        if not Path(staged).is_file():
            return {"ok": False, "error": "staged update file is missing"}
        target = Path(sys.executable)
        backup = target.with_suffix(".exe.bak")
        helper = Path(tempfile.gettempdir()) / "LIKAcs" / f"likacs-selfupdate-{os.getpid()}.cmd"
        atomic_write_text(helper, build_self_swap_script(
            str(target), str(staged), str(backup), os.getpid(), args))
        try:
            subprocess.Popen(["cmd", "/c", str(helper)], creationflags=CREATE_NO_WINDOW,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return {"ok": True, "script": str(helper), "target": str(target),
                    "backup": str(backup), "args": args}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def one_click_update(self, progress: Progress | None = None,
                         args: str | None = None) -> dict[str, Any]:
        """The whole update in one call: check, verify, stage."""
        check = self.check()
        if not check.get("ok"):
            return check
        if not check.get("update_available"):
            return {"ok": True, "up_to_date": True, "current": self.current_version,
                    "latest": check["latest"]}
        info: UpdateInfo = check["info"]
        target_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(tempfile.gettempdir())
        staged = target_dir / "LIKAcs.exe.new"
        downloaded = self.download_verified(info, staged, progress)
        if not downloaded.get("ok"):
            return downloaded
        result = self.stage_swap(staged, current_args() if args is None else args)
        if not result.get("ok"):
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
            return result
        return {"ok": True, "restarting": True, "version": info.tag,
                "notes": info.notes, "sha256": downloaded["sha256"],
                "size": downloaded["size"], "swap": result}


_ONE_SHOT_FLAGS = {"--update", "--check-update", "--self-test",
                   "--smoke-gui", "--smoke-install", "--version", "--setup",
                   "--uninstall", "--elevated-firewall"}


def current_args() -> str:
    """Command line (without argv[0]) to relaunch with after an update.

    One-shot flags are dropped, otherwise a headless ``--update`` would
    relaunch into another ``--update`` forever.
    """
    kept = [arg for arg in sys.argv[1:]
            if arg not in _ONE_SHOT_FLAGS and not any(
                arg.startswith(flag + "=") for flag in _ONE_SHOT_FLAGS)]
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in kept)
