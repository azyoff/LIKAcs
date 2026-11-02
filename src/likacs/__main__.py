"""LIKAcs command line entry point.

Usage:
    LIKAcs.exe --mode=control            Control Center (laptop / any gaming PC)
    LIKAcs.exe --mode=station            Station Agent (each gaming PC)
    LIKAcs.exe --mode=station --silent   Tray-only auto-start with Windows
    LIKAcs.exe --mode=setup               Headless 1-click station setup
    LIKAcs.exe --self-test               Headless safety/protocol smoke test
    LIKAcs.exe --smoke-gui              Construct every window against real Tk
    LIKAcs.exe --version
    LIKAcs.exe                          Friendly first-run mode chooser
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="LIKAcs", description=f"LIKAcs - LAN Server & Match Management Suite ({WEBSITE})")
    parser.add_argument("--mode", choices=["control", "station", "setup", "chooser"],
                        default=None, help="which role to run")
    parser.add_argument("--silent", action="store_true",
                        help="start hidden in the Windows system tray")
    parser.add_argument("--self-test", action="store_true",
                        help="run headless protocol/safety smoke tests and exit")
    parser.add_argument("--smoke-gui", action="store_true",
                        help="construct every window against a real Tk root and exit")
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


def run_gui(mode: str | None, silent: bool) -> int:
    try:
        import tkinter as tk  # noqa: F401
    except ImportError as exc:
        print(f"Tkinter is required for the GUI: {exc}", file=sys.stderr)
        print("Use --self-test or --mode=setup for headless operation.", file=sys.stderr)
        return 2

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
    if args.mode == "setup":
        return headless_setup()
    return run_gui(args.mode, args.silent)


if __name__ == "__main__":
    sys.exit(main())
