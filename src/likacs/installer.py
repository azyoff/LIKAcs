"""LIKAcs Windows installer and uninstaller (Python stdlib only).

The setup wizard (``LIKAcs-Setup.exe``) embeds ``LIKAcs.exe`` and installs it
into a per-user folder -- no administrator rights, no UAC, no extra runtime.
It creates real Start Menu / Desktop shortcuts, registers a proper
"Apps & features" uninstall entry, offers auto-start with Windows, and can
launch the app when finished. Uninstalling removes all of that and the running
executable itself (via a small delayed helper, since Windows locks a running
.exe).

All Windows-only work is isolated behind ``IS_WINDOWS`` so the whole module is
importable and unit-testable on Linux CI.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import GITHUB_URL, VERSION, WEBSITE, WEBSITE_LABEL
from .util import CREATE_NO_WINDOW, IS_WINDOWS, atomic_write_text, utc_now_iso

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = "LIKAcs"
PUBLISHER = "LIKAcs / likaapps.com"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LIKAcs"
INSTALL_MANIFEST = "install.json"
APP_EXE = "LIKAcs.exe"

Progress = Callable[[str, int], None]


def default_install_dir() -> Path:
    """Per-user install folder: writable without elevation, survives updates."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = tempfile.gettempdir()
    return Path(base) / PRODUCT


def payload_path() -> Path:
    """Location of the embedded LIKAcs.exe (or a dev checkout build)."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle and (Path(bundle) / APP_EXE).is_file():
        return Path(bundle) / APP_EXE
    override = os.environ.get("LIKACS_PAYLOAD")
    if override:
        return Path(override)
    # LIKAcs.exe downloaded straight from GitHub Releases has no embedded
    # payload: it installs ITSELF (copying a running .exe is legal on Windows).
    if getattr(sys, "frozen", False) and Path(sys.executable).name.lower() == APP_EXE.lower():
        return Path(sys.executable)
    return ROOT / "dist" / APP_EXE


def start_menu_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = tempfile.gettempdir()
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / PRODUCT


def desktop_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("USERPROFILE") or str(Path.home())
        return Path(base) / "Desktop"
    return Path(tempfile.gettempdir())


@dataclass
class InstallPlan:
    install_dir: Path = field(default_factory=default_install_dir)
    desktop_shortcut: bool = True
    start_menu_shortcut: bool = True
    autostart_station: bool = False
    launch_after: bool = True
    register_uninstall: bool = True
    keep_settings: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "install_dir": str(self.install_dir),
            "desktop_shortcut": self.desktop_shortcut,
            "start_menu_shortcut": self.start_menu_shortcut,
            "autostart_station": self.autostart_station,
            "launch_after": self.launch_after,
            "register_uninstall": self.register_uninstall,
            "keep_settings": self.keep_settings,
        }


def shortcut_paths(plan: InstallPlan) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if plan.start_menu_shortcut:
        paths["start_menu"] = start_menu_dir() / f"{PRODUCT}.lnk"
        paths["start_menu_control"] = start_menu_dir() / f"{PRODUCT} Control Center.lnk"
        paths["start_menu_station"] = start_menu_dir() / f"{PRODUCT} Station Agent.lnk"
        paths["start_menu_website"] = start_menu_dir() / f"{PRODUCT} Website.url"
    if plan.desktop_shortcut:
        paths["desktop"] = desktop_dir() / f"{PRODUCT}.lnk"
    return paths


def registry_values(plan: InstallPlan, exe: Path) -> dict[str, Any]:
    """Values written under HKCU\\...\\Uninstall\\LIKAcs."""
    return {
        "DisplayName": PRODUCT,
        "DisplayVersion": VERSION,
        "Publisher": PUBLISHER,
        "DisplayIcon": f"{exe},0",
        "InstallLocation": str(plan.install_dir),
        "UninstallString": f'"{exe}" --mode=uninstall',
        "QuietUninstallString": f'"{exe}" --mode=uninstall --silent',
        "URLInfoAbout": WEBSITE,
        "URLUpdateInfo": f"{GITHUB_URL}/releases/latest",
        "HelpLink": WEBSITE,
        "Comments": f"100% free, open-source and VAC-safe LAN match manager - {WEBSITE_LABEL}",
        "NoModify": 1,
        "NoRepair": 1,
        "EstimatedSize": 13_000,  # KiB, refreshed from the real payload at install time
    }


def _ps_quote(text: str) -> str:
    """Escape a string for a PowerShell single-quoted literal."""
    return "'" + str(text).replace("'", "''") + "'"


def _run_powershell(script: str) -> tuple[bool, str]:
    """Execute a short PowerShell script without flashing a console window."""
    if not IS_WINDOWS:
        return False, "PowerShell is only available on Windows"
    tmp = Path(tempfile.gettempdir()) / "LIKAcs" / "setup-shortcuts.ps1"
    try:
        atomic_write_text(tmp, script)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(tmp)],
            creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45,
        )
        output = (result.stdout or b"").decode("utf-8", "replace").strip()
        return result.returncode == 0, output
    except Exception as exc:  # pragma: no cover - Windows-only path
        return False, str(exc)


def create_shortcuts(plan: InstallPlan, exe: Path) -> dict[str, Any]:
    """Create .lnk shortcuts (WScript.Shell COM) and a website .url file."""
    paths = shortcut_paths(plan)
    if not paths:
        return {"ok": True, "created": [], "skipped": True}
    if not IS_WINDOWS:
        return {"ok": True, "created": [], "skipped": True,
                "reason": "shortcut creation requires Windows"}
    lines = ["$ErrorActionPreference = 'Stop'",
             "$shell = New-Object -ComObject WScript.Shell"]
    for key, path in paths.items():
        if path.suffix.lower() == ".url":
            continue
        args = ("--mode=station" if key == "start_menu_station"
                else "--mode=control" if key == "start_menu_control" else "")
        lines += [
            f"$shortcut = $shell.CreateShortcut({_ps_quote(str(path))})",
            f"$shortcut.TargetPath = {_ps_quote(str(exe))}",
            f"$shortcut.Arguments = {_ps_quote(args)}",
            f"$shortcut.WorkingDirectory = {_ps_quote(str(exe.parent))}",
            f"$shortcut.IconLocation = {_ps_quote(str(exe) + ',0')}",
            f"$shortcut.Description = {_ps_quote(f'{PRODUCT} - {WEBSITE_LABEL}')}",
            "$shortcut.Save()",
        ]
    ok, detail = _run_powershell("\r\n".join(lines) + "\r\n")
    created: list[str] = []
    if ok:
        for key, path in paths.items():
            if path.suffix.lower() == ".url":
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"[InternetShortcut]\r\nURL={WEBSITE}\r\n", encoding="utf-8")
                    created.append(str(path))
                except OSError:
                    pass
            elif path.is_file():
                created.append(str(path))
    return {"ok": ok, "created": created, "detail": detail}


def register_uninstall(plan: InstallPlan, exe: Path) -> dict[str, Any]:
    """Appear in Windows Settings > Apps > Installed apps, with a real uninstaller."""
    if not plan.register_uninstall or not IS_WINDOWS:
        return {"ok": True, "skipped": True}
    try:
        import winreg

        values = registry_values(plan, exe)
        values["EstimatedSize"] = max(1, exe.stat().st_size // 1024)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_WRITE) as key:
            for name, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, kind, value)
        return {"ok": True, "key": REG_KEY}
    except Exception as exc:  # pragma: no cover - Windows-only path
        return {"ok": False, "error": str(exc)}


def _write_install_manifest(plan: InstallPlan, exe: Path,
                            shortcuts: list[str]) -> None:
    payload = {
        "product": PRODUCT, "version": VERSION, "website": WEBSITE,
        "publisher": PUBLISHER, "installed_at": utc_now_iso(),
        "install_dir": str(plan.install_dir), "exe": str(exe),
        "shortcuts": shortcuts, "keep_settings": plan.keep_settings,
    }
    (plan.install_dir / INSTALL_MANIFEST).write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


def install(plan: InstallPlan, progress: Progress | None = None) -> dict[str, Any]:
    """Copy the payload and perform all requested Windows integration."""
    def step(label: str, percent: int) -> None:
        if progress:
            progress(label, percent)

    source = payload_path()
    if not source.is_file():
        return {"ok": False, "error": f"embedded payload not found: {source}"}
    report: dict[str, Any] = {"ok": True, "version": VERSION,
                              "install_dir": str(plan.install_dir), "steps": []}
    try:
        step("Preparing install folder", 5)
        plan.install_dir.mkdir(parents=True, exist_ok=True)
        target = plan.install_dir / APP_EXE
        step("Installing LIKAcs.exe", 25)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        if not target.is_file() or target.stat().st_size < 1000:
            raise OSError("installed executable is missing or truncated")
        report["exe"] = str(target)
        report["size"] = target.stat().st_size

        step("Creating shortcuts", 55)
        links = create_shortcuts(plan, target)
        report["steps"].append({"shortcuts": links})
        if not links.get("ok"):
            report["warnings"] = [f"shortcuts: {links.get('detail') or links.get('error')}"]

        step("Registering with Windows", 75)
        registration = register_uninstall(plan, target)
        report["steps"].append({"uninstall_entry": registration})

        if plan.autostart_station:
            step("Enabling start with Windows", 88)
            try:
                from .setup_windows import set_autostart
                report["steps"].append(
                    {"autostart": set_autostart(True, str(target), mode="station")})
            except Exception as exc:
                report["steps"].append({"autostart": {"ok": False, "error": str(exc)}})

        step("Finishing", 95)
        _write_install_manifest(plan, target, links.get("created", []))
        step("Done", 100)
        report["shortcuts"] = links.get("created", [])
    except Exception as exc:
        return {"ok": False, "error": str(exc), "install_dir": str(plan.install_dir)}
    return report


def build_remove_script(install_dir: Path, pid: int) -> str:
    """Delayed helper: Windows cannot delete the uninstaller while it runs."""
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "DIR={install_dir}"\r\n'
        f'set "PID={int(pid)}"\r\n'
        ":wait\r\n"
        'tasklist /FI "PID eq %PID%" /NH | find "%PID%" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'rmdir /S /Q "%DIR%" 2>nul\r\n'
        'start /b cmd /c del "%~f0"\r\n'
        "endlocal\r\n"
    )


def build_website_cleanup(shortcuts: list[str]) -> str:
    return "\r\n".join(f'del /F /Q "{path}" 2>nul' for path in shortcuts)


def uninstall(install_dir: Path | None = None,
              keep_settings: bool = True) -> dict[str, Any]:
    """Remove shortcuts, registry entry, autostart and the install folder."""
    folder = Path(install_dir) if install_dir else default_install_dir()
    manifest_path = folder / INSTALL_MANIFEST
    shortcuts: list[str] = []
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            shortcuts = [str(item) for item in data.get("shortcuts", [])]
            keep_settings = bool(data.get("keep_settings", keep_settings))
        except (OSError, ValueError):
            pass
    report: dict[str, Any] = {"ok": True, "install_dir": str(folder),
                              "removed_shortcuts": [], "keep_settings": keep_settings}

    for path in shortcuts:
        try:
            Path(path).unlink(missing_ok=True)
            report["removed_shortcuts"].append(path)
        except OSError:
            pass
    # Also remove the standard shortcut locations (covers older/manual installs).
    for path in (start_menu_dir() / f"{PRODUCT}.lnk",
                 start_menu_dir() / f"{PRODUCT} Control Center.lnk",
                 start_menu_dir() / f"{PRODUCT} Station Agent.lnk",
                 start_menu_dir() / f"{PRODUCT} Website.url",
                 desktop_dir() / f"{PRODUCT}.lnk"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    if IS_WINDOWS:
        try:
            import winreg
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
            report["uninstall_entry"] = "removed"
        except FileNotFoundError:
            report["uninstall_entry"] = "absent"
        except Exception as exc:
            report["uninstall_entry"] = f"error: {exc}"
        try:
            from .setup_windows import set_autostart
            report["autostart"] = set_autostart(False)
        except Exception as exc:
            report["autostart"] = {"ok": False, "error": str(exc)}
    else:
        report["uninstall_entry"] = "skipped (non-Windows)"

    if IS_WINDOWS:
        helper = Path(tempfile.gettempdir()) / PRODUCT / f"likacs-uninstall-{os.getpid()}.cmd"
        script = build_remove_script(folder, os.getpid())
        # Remove leftover shortcut files before the folder deletion.
        script = script.replace('rmdir /S /Q "%DIR%" 2>nul',
                                build_website_cleanup(shortcuts) +
                                '\r\nrmdir /S /Q "%DIR%" 2>nul')
        try:
            atomic_write_text(helper, script)
            subprocess.Popen(["cmd", "/c", str(helper)], creationflags=CREATE_NO_WINDOW,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            report["cleanup"] = str(helper)
        except OSError as exc:
            report["cleanup_error"] = str(exc)
    else:
        shutil.rmtree(folder, ignore_errors=True)
        report["cleanup"] = "removed synchronously (non-Windows test host)"
    return report


def launch_app(exe: Path, mode: str = "") -> bool:
    """Open the installed app (optionally straight into Control Center / Agent)."""
    if not exe.is_file():
        return False
    command = [str(exe)]
    if mode:
        command.append(f"--mode={mode}")
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def smoke_install() -> int:
    """Headless end-to-end install test used by CI. Returns a process exit code."""
    base = Path(tempfile.mkdtemp(prefix="likacs-smoke-install-"))
    plan = InstallPlan(install_dir=base / PRODUCT, desktop_shortcut=False,
                       start_menu_shortcut=False, autostart_station=False,
                       launch_after=False, register_uninstall=False)
    report = install(plan)
    if not report.get("ok"):
        print(f"SMOKE INSTALL FAILED: {report.get('error')}")
        return 1
    installed = Path(report["exe"])
    source = payload_path()
    if installed.read_bytes() != source.read_bytes():
        print("SMOKE INSTALL FAILED: installed payload differs from source")
        return 1
    if IS_WINDOWS:
        try:
            check = subprocess.run([str(installed), "--self-test"],
                                   creationflags=CREATE_NO_WINDOW, timeout=90,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            if check.returncode != 0:
                print(f"SMOKE INSTALL FAILED: installed exe self-test returned {check.returncode}")
                return 1
        except Exception as exc:
            print(f"SMOKE INSTALL FAILED: could not run installed exe: {exc}")
            return 1
    removed = uninstall(plan.install_dir, keep_settings=True)
    if not removed.get("ok"):
        print(f"SMOKE UNINSTALL FAILED: {removed}")
        return 1
    print(f"SMOKE INSTALL OK: v{VERSION} installed, verified and removed cleanly")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="LIKAcs-Setup",
        description=f"{PRODUCT} setup wizard - free & open-source ({WEBSITE})")
    parser.add_argument("--silent", action="store_true",
                        help="install without showing the wizard (uses defaults)")
    parser.add_argument("--install-dir", default="", help="destination folder")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--no-register", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--autostart", action="store_true",
                        help="start the Station Agent silently with Windows")
    parser.add_argument("--smoke-install", action="store_true",
                        help="CI: install to a temp folder, verify, uninstall, exit")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"{PRODUCT} Setup v{VERSION} - {WEBSITE}")
        return 0
    if args.smoke_install:
        return smoke_install()
    if args.uninstall:
        report = uninstall()
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1
    if args.silent:
        plan = InstallPlan(
            install_dir=Path(args.install_dir) if args.install_dir else default_install_dir(),
            desktop_shortcut=not args.no_shortcuts,
            start_menu_shortcut=not args.no_shortcuts,
            autostart_station=args.autostart,
            launch_after=not args.no_launch,
            register_uninstall=not args.no_register,
        )
        report = install(plan)
        if report.get("ok") and plan.launch_after:
            launch_app(Path(report["exe"]))
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1

    from .ui.setup_wizard import run_wizard  # lazy: wizard imports tkinter
    return run_wizard(install_dir=args.install_dir or None)


if __name__ == "__main__":
    sys.exit(main())
