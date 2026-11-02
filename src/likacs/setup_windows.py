"""1-click first-time station setup (Windows 10 / 11).

* Auto-detect Steam libraries across C:, D:, E:, ... and both games' cfg paths.
* Enable the developer console and safely hook autoexec.cfg / userconfig.cfg.
* Allow LAN ports through Windows Defender Firewall (admin required).
* Optional silent auto-start with Windows boot.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from . import VERSION, WEBSITE
from .cfgs import CfgManager
from .config import Settings
from .paths import detect_installs, install_summary
from .rules import build_match_cvars, preset_slots
from .util import (CREATE_NO_WINDOW, IS_WINDOWS, atomic_write_text, data_path,
                   run_quiet, save_json, utc_now_iso)

RULE_PREFIX = "LIKAcs"
AUTOSTART_VALUE = "LIKAcs Station Agent"


def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def current_executable() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    return str(Path(sys.argv[0]).resolve())


def elevate(argv: list[str]) -> dict[str, Any]:
    """Re-launch one helper elevated through the standard UAC prompt."""
    if not IS_WINDOWS:
        return {"ok": False, "error": "Windows only"}
    try:
        import ctypes
        arguments = " ".join(f'"{arg}"' for arg in argv)
        if getattr(sys, "frozen", False):
            executable, params = current_executable(), arguments
        else:
            # Running from a source checkout: elevate `python -m likacs ...`.
            executable = sys.executable
            params = "-m likacs " + arguments
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, None, 1,
        )
        return {"ok": int(result) > 32, "shell_execute_result": int(result)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def firewall_rule_commands(ports: dict[str, int], programs: list[str],
                           exe_path: str = "") -> list[tuple[str, list[str]]]:
    """Build idempotent netsh commands (testable without actually applying)."""
    udp_ports = f"{ports['discovery']},{ports['agent']},{ports['game_port_base']}-{ports['game_port_base'] + 20}"
    tcp_ports = f"{ports['agent']},{ports['game_port_base']}-{ports['game_port_base'] + 20}"
    names = [
        (f"{RULE_PREFIX} - LAN Discovery + Control (UDP)",
         ["dir=in", "action=allow", "protocol=UDP", f"localport={udp_ports}",
          "remoteip=localsubnet", "profile=any"]),
        (f"{RULE_PREFIX} - Control + RCON (TCP)",
         ["dir=in", "action=allow", "protocol=TCP", f"localport={tcp_ports}",
          "remoteip=localsubnet", "profile=any"]),
        (f"{RULE_PREFIX} - Outbound to LAN",
         ["dir=out", "action=allow", "protocol=any", "remoteip=localsubnet", "profile=any"]),
    ]
    unique_programs: list[str] = []
    for program in [*programs, exe_path]:
        if program and program not in unique_programs:
            unique_programs.append(program)
    for program in unique_programs:
        label = Path(program).name or "Program"
        names.append((
            f"{RULE_PREFIX} - {label} (LAN only)",
            ["dir=in", "action=allow", f'program="{program}"', "enable=yes",
             "remoteip=localsubnet", "profile=any"],
        ))
    commands: list[tuple[str, list[str]]] = []
    for name, options in names:
        commands.append((name, ["netsh", "advfirewall", "firewall", "delete", "rule", f'name="{name}"']))
        commands.append((name, ["netsh", "advfirewall", "firewall", "add", "rule",
                                f'name="{name}"', *options]))
    return commands


def apply_firewall_rules(settings: Settings, installs: dict[str, Any],
                         exe_path: str = "") -> dict[str, Any]:
    """Add LAN-only Defender Firewall allow rules for LIKAcs and both games."""
    if not IS_WINDOWS:
        return {"ok": False, "error": "Windows Defender Firewall rules require Windows"}
    if not is_admin():
        return {
            "ok": False, "needs_admin": True,
            "error": "Firewall rules need administrator rights - use 'Run as admin' once, "
                     "or click 'Apply Firewall Rules (UAC)'.",
        }
    programs = []
    for install in installs.values():
        for key in ("client_exe", "server_exe"):
            value = install.get(key) if isinstance(install, dict) else getattr(install, key, "")
            if value and Path(value).exists():
                programs.append(str(value))
    commands = firewall_rule_commands(
        {"discovery": settings.discovery_port, "agent": settings.agent_port,
         "game_port_base": settings.game_port_base},
        programs, exe_path or current_executable(),
    )
    results = []
    for name, argv in commands:
        try:
            proc = run_quiet(["netsh", *argv[1:]], timeout=20)
            results.append({"rule": name, "code": proc.returncode,
                            "output": (proc.stdout or proc.stderr or "").strip()[:200]})
        except Exception as exc:
            results.append({"rule": name, "code": -1, "output": str(exc)})
    return {"ok": True, "results": results}


def set_autostart(enabled: bool, exe_path: str = "", mode: str = "station") -> dict[str, Any]:
    if not IS_WINDOWS:
        return {"ok": False, "error": "Auto-start with Windows requires Windows"}
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE | winreg.KEY_READ)
        with key:
            if enabled:
                path = exe_path or current_executable()
                winreg.SetValueEx(key, AUTOSTART_VALUE, 0, winreg.REG_SZ,
                                  f'"{path}" --mode={mode} --silent')
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_VALUE)
                except FileNotFoundError:
                    pass
        return {"ok": True, "enabled": enabled}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def autostart_status() -> dict[str, Any]:
    if not IS_WINDOWS:
        return {"enabled": False, "command": ""}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE)
        return {"enabled": True, "command": str(value)}
    except Exception:
        return {"enabled": False, "command": ""}


def one_click_setup(settings: Settings, overrides: dict[str, dict[str, str]] | None = None,
                    firewall: bool = False, autostart: bool = False,
                    state_dir: str | None = None) -> dict[str, Any]:
    """Run the entire first-time station setup and return a readable report."""
    report: dict[str, Any] = {
        "ok": True, "at": utc_now_iso(), "version": VERSION, "website": WEBSITE,
        "steps": [], "installs": [], "generated": [], "backups": [],
    }
    installs = detect_installs(overrides if overrides is not None else settings.game_paths)
    report["installs"] = install_summary(installs)
    if not installs:
        report["steps"].append(
            "No CS2 / CS 1.6 installation found. Add the paths manually in Settings "
            "(Steam > right-click game > Manage > Browse local files)."
        )
        report["ok"] = False
        return report

    for game in sorted(installs):
        install = installs[game]
        manager = CfgManager(install.cfg_dir, game)
        try:
            hook = manager.install(settings.join_word, settings.f10_key, settings.enable_f10_bind)
            cvars = build_match_cvars(settings.rules, game, settings.default_preset,
                                      preset_slots(settings.default_preset), settings.overtime)
            manager.write_match(cvars)
            report["generated"].append(manager.describe())
            if hook.get("backup"):
                report["backups"].append(hook["backup"])
            report["steps"].append(
                f"{game.upper()}: hooked {install.autoexec_name} safely -> exec lika_autoexec.cfg "
                f"({install.cfg_dir})"
            )
        except Exception as exc:
            report["ok"] = False
            report["steps"].append(f"{game.upper()}: setup failed: {exc}")

    if firewall:
        firewall_result = apply_firewall_rules(settings, {k: v.to_dict() for k, v in installs.items()})
        report["firewall"] = firewall_result
        report["steps"].append(
            "Firewall rules applied (LAN only)." if firewall_result.get("ok")
            else f"Firewall: {firewall_result.get('error', 'skipped')}"
        )
    if autostart:
        auto = set_autostart(True, mode="station")
        report["autostart"] = auto
        report["steps"].append(
            "Auto-start with Windows enabled (silent tray mode)." if auto.get("ok")
            else f"Auto-start: {auto.get('error', 'failed')}"
        )
    report["steps"].append(
        "Developer console enabled via official cvar (con_enable 1 / console 1). "
        "Player crosshair, sensitivity and all other binds were left untouched."
    )
    report["steps"].append(
        "Ready: press ` then type lika, or press F10, or use Start & Connect Selected PCs."
    )
    try:
        save_json(state_dir or str(data_path("setup-report.json")), report)
    except OSError:
        pass
    return report
