"""LIKAcs command line entry point.

Usage:
    LIKAcs.exe                          Friendly first-run mode chooser
    LIKAcs.exe --mode=control           Control Center (laptop / any gaming PC)
    LIKAcs.exe --mode=station           Station Agent (each gaming PC)
    LIKAcs.exe --mode=station --silent  Tray-only auto-start with Windows
    LIKAcs.exe --mode=setup             Headless 1-click station setup
    LIKAcs.exe --mode=uninstall         Remove shortcuts / registry / app
    LIKAcs.exe --check-update           Headless JSON update check
    LIKAcs.exe --update                 Headless one-click self-update
    LIKAcs.exe --self-test              Headless safety/protocol smoke test
    LIKAcs.exe --smoke-gui             Construct every window against real Tk
    LIKAcs.exe --version

The desktop app itself needs none of these flags: install with
LIKAcs-Setup.exe and click "Update LIKAcs" inside the window.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python src/likacs/__main__.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from . import VERSION, WEBSITE  # noqa: E402
from .config import SettingsStore  # noqa: E402
from .util import data_path, save_json  # noqa: E402

GUI_MODES = {"control", "station", "chooser"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="LIKAcs", description=f"LIKAcs - LAN Server & Match Management Suite ({WEBSITE})")
    parser.add_argument("--mode", choices=["control", "station", "setup", "chooser", "uninstall"],
                        default=None, help="which role to run")
    parser.add_argument("--silent", action="store_true",
                        help="start hidden in the Windows system tray / no dialogs")
    parser.add_argument("--self-test", action="store_true",
                        help="run headless protocol/safety smoke tests and exit")
    parser.add_argument("--smoke-gui", action="store_true",
                        help="construct every window against a real Tk root and exit")
    parser.add_argument("--setup", action="store_true",
                        help="open the Setup wizard (install / repair / reinstall)")
    parser.add_argument("--check-update", action="store_true",
                        help="check GitHub Releases and print JSON without installing")
    parser.add_argument("--update", action="store_true",
                        help="one-click self-update (headless), then exit for the swap helper")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--elevated-firewall", action="store_true",
                        help=argparse.SUPPRESS)  # internal UAC helper
    return parser


def elevated_firewall() -> int:
    from .paths import detect_installs
    from .setup_windows import apply_firewall_rules
    settings = SettingsStore().get()
    report = apply_firewall_rules(settings, {k: v.to_dict() for k, v in detect_installs().items()})
    save_json(data_path("firewall-report.json"), report)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def headless_setup() -> int:
    from .setup_windows import one_click_setup
    report = one_click_setup(SettingsStore().get())
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def headless_uninstall(silent: bool) -> int:
    from .installer import uninstall
    report = uninstall()
    if not silent:
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "LIKAcs uninstalled",
                "LIKAcs was removed from this PC.\n\n"
                "Your cafe settings were kept. Thank you for using LIKAcs.\n"
                f"{WEBSITE}")
        except Exception:
            pass
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def headless_update_check() -> int:
    from .selfupdate import SelfUpdater
    result = SelfUpdater().check()
    info = result.get("info")
    printable = {key: value for key, value in result.items() if key != "info"}
    if info is not None:
        printable["asset"] = info.to_dict()
    print(json.dumps(printable, indent=2, default=str))
    return 0 if result.get("ok") else 1


def headless_update() -> int:
    """One-click update from the command line (used by automation/advanced users)."""
    from .selfupdate import SelfUpdater
    result = SelfUpdater().one_click_update()
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("swap", "info")}, indent=2, default=str))
    if not result.get("ok"):
        return 1
    if result.get("restarting"):
        # The .cmd helper is waiting for this PID. Exit hard so no lingering
        # non-daemon network thread can keep the executable locked.
        try:
            sys.stdout.flush()
        except Exception:
            pass
        import os
        os._exit(0)
    return 0


def already_running() -> int:
    """Friendly message instead of a second, invisible copy of the app."""
    message = ("LIKAcs is already running. Look for the LIKAcs icon in the "
               "Windows system tray near the clock.\n\n"
               f"{WEBSITE}")
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("LIKAcs is already running", message)
        root.destroy()
    except Exception:
        print(message)
    return 0


def needs_first_run_install() -> bool:
    """A downloaded LIKAcs.exe shows the Setup wizard before the app.

    The installed copy always has install.json next to it, so it goes straight
    to the app. One single .exe on the Releases page therefore serves as BOTH
    the installer and the product - no confusing choice of downloads.
    """
    if not getattr(sys, "frozen", False):
        return False
    from .installer import INSTALL_MANIFEST
    return not (Path(sys.executable).parent / INSTALL_MANIFEST).is_file()


def run_gui(mode: str | None, silent: bool, force_setup: bool = False) -> int:
    try:
        import tkinter as tk  # noqa: F401
    except ImportError as exc:
        print(f"Tkinter is required for the GUI: {exc}", file=sys.stderr)
        print("Use --self-test or --mode=setup for headless operation.", file=sys.stderr)
        return 2

    if force_setup or (mode is None and needs_first_run_install()):
        from .ui.setup_wizard import run_wizard
        return run_wizard()

    if mode == "control":
        from .control import ControlCenter
        from .ui.control_center import ControlCenterApp
        ControlCenterApp(ControlCenter(), start_hidden=silent)
        return 0
    if mode == "station":
        from .agent import StationAgent
        from .ui.station_agent import StationAgentApp
        StationAgentApp(StationAgent(), start_hidden=silent)
        return 0

    # Unified exe with no --mode: show the one-time chooser.
    from .ui.mode_chooser import choose_mode
    from .ui.theme import apply_theme
    root = tk.Tk()
    root.withdraw()
    apply_theme(root)

    def open_control() -> None:
        root.destroy()
        from .control import ControlCenter
        from .ui.control_center import ControlCenterApp
        ControlCenterApp(ControlCenter(), start_hidden=silent)

    def open_station() -> None:
        root.destroy()
        from .agent import StationAgent
        from .ui.station_agent import StationAgentApp
        StationAgentApp(StationAgent(), start_hidden=silent)

    choose_mode(root, open_control, open_station)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"LIKAcs v{VERSION} - {WEBSITE}")
        return 0
    if args.self_test:
        from .selftest import run
        return run()
    if args.smoke_gui:
        from .ui.smoke import run_gui_smoke
        return run_gui_smoke()
    if args.elevated_firewall:
        return elevated_firewall()
    if args.check_update:
        return headless_update_check()
    if args.update:
        return headless_update()
    if args.mode == "setup":
        return headless_setup()
    if args.mode == "uninstall":
        return headless_uninstall(args.silent)

    # GUI modes get crisp DPI, friendly logged errors and one running copy.
    from .runtime import enable_dpi_awareness, install_error_handlers, single_instance_guard
    enable_dpi_awareness()
    install_error_handlers()
    if not single_instance_guard():
        return already_running()
    return run_gui(args.mode, args.silent, force_setup=args.setup)


if __name__ == "__main__":
    sys.exit(main())
