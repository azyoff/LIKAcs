"""LIKAcs Station Agent desktop app: tiny tray-first window for gaming PCs."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import VERSION, WEBSITE
from ..agent import StationAgent
from ..branding import FOOTER, TRAY_PREFIX, fit_tray_tooltip
from ..protocol import EP_SETUP, EP_FIREWALL, EP_AUTOSTART, EP_SYNC_SETTINGS
from ..setup_windows import autostart_status, one_click_setup
from ..tray import create_tray
from ..util import open_url, primary_ipv4
from .about import show_about
from .theme import COLORS, FONT_BOLD, FONT_SMALL, FONT_TITLE, apply_theme
from .widgets import LinkLabel, LogPanel


class StationAgentApp:
    def __init__(self, agent: StationAgent | None = None, start_hidden: bool = False,
                 *, root: tk.Tk | None = None, smoke: bool = False) -> None:
        """Build the agent window.

        ``smoke=True`` constructs every widget but skips the API server,
        discovery, tray icon and ``mainloop`` (used by the GUI smoke test).
        """
        self.agent = agent or StationAgent()
        self.root = root or tk.Tk()
        self.root.title(f"LIKAcs v{VERSION} - Station Agent  |  {self.agent.label}")
        self.root.geometry("780x600")
        self.root.minsize(700, 520)
        apply_theme(self.root)
        self._closing = False

        self.status_vars = {key: tk.StringVar(value="...") for key in
                            ("label", "ip", "port", "assignment", "installs", "servers", "version", "autostart")}
        self._build_layout()
        if smoke:
            self.root.update_idletasks()
            return

        self.tray = create_tray(
            get_tooltip=self._tooltip,
            get_menu_items=self._menu_items,
            on_command=lambda command: self._post(lambda: self._tray_command(command)),
            on_show=lambda: self._post(self.show_window),
            logger=self._log,
        )
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.agent.logger = lambda message: self._post(lambda: self._log(message))
        self.agent.on_restart_requested = lambda: self._post(self.quit_app)

        self.agent.start()
        self.tray.start()
        self._refresh()
        self.root.after(2000, self._periodic)
        if start_hidden:
            self.root.withdraw()
            self.tray.notify("LIKAcs Station Agent", f"{self.agent.label} is running in the tray - {WEBSITE}")
        self.root.mainloop()

    # ---------------------------------------------------------------- helpers
    def _post(self, function: Callable[[], None]) -> None:
        try:
            self.root.after(0, function)
        except tk.TclError:
            pass

    def _log(self, message: str) -> None:
        self.log_panel.write(message)

    def _async(self, function: Callable[[], Any], label: str) -> None:
        def worker() -> None:
            try:
                result = function()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self._post(lambda: self._log(f"{label}: {result.get('ok', True)} "
                                         + ("" if result.get("ok", True) else str(result.get("error")))))
            self._post(self._refresh)
        threading.Thread(target=worker, name="likacs-station-task", daemon=True).start()

    # ---------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        header = ttk.Frame(self.root, style="Panel.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="  LIKAcs Station Agent", font=FONT_TITLE,
                  foreground=COLORS["accent"], background=COLORS["panel"]).pack(anchor="w", pady=(12, 0), padx=8)
        sub = ttk.Frame(header, style="Panel.TFrame")
        sub.pack(fill="x", padx=8, pady=(0, 10))
        ttk.Label(sub, text="  Lightweight LAN agent - minimizes to the Windows system tray",
                  font=FONT_SMALL, foreground=COLORS["muted"], background=COLORS["panel"]).pack(side="left")
        LinkLabel(sub, url=WEBSITE, text=WEBSITE, background=COLORS["panel"],
                  font=FONT_BOLD).pack(side="right", padx=12)

        from .update_panel import UpdateBar
        self.update_bar = UpdateBar(self.root, on_restart=self.quit_for_update,
                                    log=self._log, auto_check=not smoke)
        self.update_bar.pack(fill="x", padx=12, pady=(8, 0))

        info = ttk.LabelFrame(self.root, text=" This gaming PC ", style="Card.TLabelframe")
        info.pack(fill="x", padx=12, pady=10)
        rows = [
            ("label", "PC label"), ("ip", "LAN IP (DHCP-proof)"), ("port", "Control API"),
            ("assignment", "Assigned room (lika / F10)"), ("installs", "Detected games"),
            ("servers", "Hosting"), ("version", "LIKAcs version"), ("autostart", "Auto-start with Windows"),
        ]
        for index, (key, label) in enumerate(rows):
            ttk.Label(info, text=label, style="Panel.TLabel", width=28).grid(
                row=index, column=0, sticky="w", padx=10, pady=3)
            ttk.Label(info, textvariable=self.status_vars[key], style="Panel.TLabel").grid(
                row=index, column=1, sticky="w", padx=10, pady=3)

        setup = ttk.LabelFrame(self.root, text=" 1-Click first-time station setup ", style="Card.TLabelframe")
        setup.pack(fill="x", padx=12, pady=6)
        ttk.Label(setup, text="Auto-detects Steam libraries on C:, D:, E: ... , enables the developer console,\n"
                  "safely appends exec lika_autoexec.cfg to autoexec.cfg / userconfig.cfg, generates\n"
                  "lika / lika1..3 aliases, binds F10 and leaves all other player binds untouched.",
                  style="Panel.TLabel", justify="left").pack(anchor="w", padx=10, pady=8)
        bar = ttk.Frame(setup, style="Panel.TFrame")
        bar.pack(fill="x", padx=8, pady=(0, 10))
        for text, command in [
            ("1-Click Station Setup", self._setup),
            ("Firewall Rules (UAC)", self._firewall),
            ("Auto-start ON / OFF", self._toggle_autostart),
            ("Reinstall lika aliases", self._reinstall),
        ]:
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=4)

        actions = ttk.Frame(self.root, style="Panel.TFrame")
        actions.pack(fill="x", padx=12, pady=4)
        ttk.Button(actions, text="Minimize to tray", command=self.hide_to_tray).pack(side="left", padx=4)
        ttk.Button(actions, text="Update LIKAcs", style="Primary.TButton",
                   command=lambda: self.update_bar.one_click()).pack(side="left", padx=4)
        ttk.Button(actions, text="About / likaapps.com",
                   command=lambda: show_about(self.root, lambda: self.update_bar.one_click())).pack(side="left", padx=4)
        ttk.Button(actions, text="Exit", command=self.quit_app).pack(side="right", padx=4)

        log_frame = ttk.LabelFrame(self.root, text=" Agent log ", style="Card.TLabelframe")
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.log_panel = LogPanel(log_frame, height=11)
        self.log_panel.pack(fill="both", expand=True, padx=4, pady=4)

        footer = ttk.Frame(self.root, style="Panel.TFrame")
        footer.pack(fill="x", side="bottom")
        LinkLabel(footer, url=WEBSITE, text=WEBSITE, background=COLORS["panel"],
                  font=FONT_BOLD).pack(side="left", padx=10, pady=6)
        ttk.Label(footer, text=FOOTER, font=FONT_SMALL, foreground=COLORS["muted"],
                  background=COLORS["panel"]).pack(side="left", padx=4)
        self._log(f"LIKAcs Station Agent ready - {WEBSITE}")

    # --------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        status = self.agent.status_report()
        assignment = status.get("assignment") or {}
        primary = assignment.get("primary") or {}
        assigned = (f"{primary.get('room_name', 'Room')} -> {primary.get('host')}:{primary.get('port')}"
                    if primary else "not assigned")
        installs = ", ".join(f"{item.get('game')} ({'OK' if item.get('exists') else 'missing'})"
                             for item in status.get("installs", [])) or "not detected yet"
        servers = ", ".join(f"{item.get('room_name')} :{item.get('port')}"
                            for item in status.get("servers", [])) or "none"
        self.status_vars["label"].set(str(status.get("label")))
        self.status_vars["ip"].set(str(status.get("ip")) + f"  (UDP {status.get('discovery_port')})")
        self.status_vars["port"].set(f"TCP {status.get('agent_port')}  (signed LAN API)")
        self.status_vars["assignment"].set(assigned)
        self.status_vars["installs"].set(installs)
        self.status_vars["servers"].set(servers)
        self.status_vars["version"].set(str(status.get("version")))
        self.status_vars["autostart"].set("ON" if (status.get("autostart") or {}).get("enabled") else "OFF")

    def _periodic(self) -> None:
        if self._closing:
            return
        self._refresh()
        self.agent.registry.prune_dead()
        self.root.after(2000, self._periodic)

    # --------------------------------------------------------------- actions
    def _setup(self) -> None:
        self._async(lambda: one_click_setup(self.agent.settings), "1-Click Station Setup")
        self._log("Detecting Steam libraries and writing official cfg files...")

    def _firewall(self) -> None:
        self._async(lambda: self.agent.dispatch(EP_FIREWALL, {"elevate": True})[1],
                    "Firewall UAC request")

    def _toggle_autostart(self) -> None:
        enabled = not autostart_status().get("enabled", False)
        self._async(lambda: self.agent.dispatch(EP_AUTOSTART, {"enabled": enabled})[1],
                    f"Auto-start {'ON' if enabled else 'OFF'}")

    def _reinstall(self) -> None:
        self._async(lambda: self.agent.dispatch(EP_SYNC_SETTINGS, {})[1], "Reinstall lika aliases")

    # ------------------------------------------------------------------ tray
    def _tooltip(self) -> str:
        status = self.agent.status_report()
        assignment = status.get("assignment") or {}
        primary = assignment.get("primary") or {}
        items = []
        if primary:
            items.append(f"{primary.get('room_name', 'Room')}: {primary.get('host')}:{primary.get('port')}")
        for server in status.get("servers", []):
            items.append(f"{server.get('room_name')}: {server.get('preset')} playing")
        return fit_tray_tooltip(items or ["idle"], 127)

    def _menu_items(self) -> list[dict[str, Any]]:
        status = self.agent.status_report()
        items: list[dict[str, Any]] = [
            {"label": f"LIKAcs | {WEBSITE}", "id": "website"},
            {"separator": True},
            {"label": f"  {status.get('label')} - {status.get('ip')}", "id": None, "disabled": True},
        ]
        assignment = status.get("assignment") or {}
        primary = assignment.get("primary") or {}
        items.append({"label": ("  Assigned: " + str(primary.get("room_name", "?")))
                      if primary else "  No room assigned", "id": None, "disabled": True})
        for server in status.get("servers", []):
            items.append({"label": f"  {server.get('room_name')}: {server.get('preset')} playing",
                          "id": None, "disabled": True})
        items.append({"label": f"  {len(status.get('installs') or [])} game(s) detected",
                      "id": None, "disabled": True})
        items += [
            {"separator": True},
            {"label": "Open Station Agent", "id": "show"},
            {"label": "1-Click Station Setup", "id": "setup"},
            {"label": "Update LIKAcs from GitHub", "id": "update"},
            {"label": "About LIKAcs / likaapps.com", "id": "about"},
            {"separator": True},
            {"label": "Exit Station Agent", "id": "exit"},
        ]
        return items

    def _tray_command(self, command: str) -> None:
        if command == "website":
            open_url(WEBSITE)
        elif command == "show":
            self.show_window()
        elif command == "setup":
            self._setup()
        elif command == "update":
            self.show_window()
            self.update_bar.one_click()
        elif command == "about":
            show_about(self.root, lambda: self.update_bar.one_click())
        elif command == "exit":
            self.quit_app()

    def hide_to_tray(self) -> None:
        self.root.withdraw()
        self.tray.notify("LIKAcs", f"Station Agent minimized to tray - {WEBSITE}")

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def quit_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.agent.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def quit_for_update(self) -> None:
        """Exit immediately so the verified update can replace LIKAcs.exe."""
        try:
            self.quit_app()
        except Exception:
            pass
        os._exit(0)
