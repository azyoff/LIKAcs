"""LIKAcs Control Center desktop application (Tkinter + system tray)."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from .. import VERSION, WEBSITE, WEBSITE_LABEL
from ..branding import FOOTER, HEADER_SUBTITLE, HEADER_TITLE
from ..control import ControlCenter
from ..rules import (DEFAULT_RULES, MAPS_CS16, MAPS_CS2, PRESET_ORDER, RULE_HELP,
                     maps_for, normalize_map)
from ..setup_windows import apply_firewall_rules, elevate, one_click_setup
from ..tray import create_tray
from ..util import open_url, utc_now_iso
from .about import show_about
from .theme import COLORS, FONT_BOLD, FONT_SMALL, FONT_TITLE, apply_theme
from .widgets import (LinkLabel, LogPanel, StationChecklist, labeled_entry,
                      status_bar_text)


class ControlCenterApp:
    """The laptop dashboard: rooms, PCs, rules, updates, settings, tray."""

    def __init__(self, control: ControlCenter | None = None, start_hidden: bool = False,
                 *, root: tk.Tk | None = None, smoke: bool = False) -> None:
        """Build the dashboard.

        ``smoke=True`` is used by the GUI smoke test: it constructs every
        widget but skips network services, the tray icon and ``mainloop``.
        """
        self.control = control or ControlCenter()
        self.root = root or tk.Tk()
        self.root.title(f"LIKAcs v{VERSION} - Control Center  |  {WEBSITE_LABEL}")
        self.root.geometry("1320x860")
        self.root.minsize(1120, 720)
        apply_theme(self.root)

        self.smoke = smoke
        self.selected_room_id: str | None = None
        self.shared_selected: set[str] = set()
        self.update_release: Any = None
        self.update_asset_path = ""
        self.update_version = ""
        self._need_refresh = True
        self._station_signature = ""
        self._room_signature = ""
        self._closing = False

        self._build_layout()
        self._bind_logging()
        if smoke:
            self.root.update_idletasks()
            return

        self.tray = create_tray(
            get_tooltip=self.control.tray_tooltip,
            get_menu_items=self.control.tray_menu_items,
            on_command=lambda command: self._post(lambda: self._tray_command(command)),
            on_show=lambda: self._post(self.show_window),
            logger=self._log,
        )
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.control.on_change = lambda: self._post(self._mark_refresh)

        self.control.start()
        self.tray.start()
        self._refresh_all()
        self.root.after(1500, self._periodic)
        if start_hidden:
            self.root.withdraw()
            self.tray.notify("LIKAcs", f"Control Center is running in the tray - {WEBSITE}")
        self.root.mainloop()

    # ---------------------------------------------------------------- helpers
    def _post(self, function: Callable[[], None]) -> None:
        """Marshal a callback from network/tray threads onto the Tk thread."""
        try:
            self.root.after(0, function)
        except tk.TclError:
            pass

    def _bind_logging(self) -> None:
        self.control.logger = lambda message: self._post(lambda: self._log(message))

    def _log(self, message: str) -> None:
        self.log_panel.write(message)
        if "error" in message.lower() or "unreachable" in message.lower():
            self.control.last_error = message

    def _mark_refresh(self) -> None:
        self._need_refresh = True

    def _async(self, function: Callable[[], Any],
               done: Callable[[Any], None] | None = None,
               busy: str = "Working...") -> None:
        self.status_var.set(busy)

        def worker() -> None:
            try:
                result = function()
            except Exception as exc:  # never let a worker die silently
                result = {"ok": False, "error": str(exc)}
            self._post(lambda: self._async_done(result, done))

        threading.Thread(target=worker, name="likacs-ui-task", daemon=True).start()

    def _async_done(self, result: Any, done: Callable[[Any], None] | None) -> None:
        if isinstance(result, dict) and result.get("ok") is False:
            self._log(f"ERROR: {result.get('error')}")
        if done:
            done(result)
        self._mark_refresh()
        self._refresh_all()

    def _periodic(self) -> None:
        if self._closing:
            return
        try:
            self._refresh_all()
        finally:
            self.root.after(1500, self._periodic)

    # ---------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        header = ttk.Frame(self.root, style="Panel.TFrame")
        header.pack(fill="x", padx=0, pady=0)
        ttk.Label(header, text=f"  {HEADER_TITLE}", font=FONT_TITLE,
                  foreground=COLORS["accent"], background=COLORS["panel"]).pack(anchor="w", pady=(10, 0), padx=8)
        sub = ttk.Frame(header, style="Panel.TFrame")
        sub.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(sub, text=f"  {HEADER_SUBTITLE}", font=FONT_SMALL,
                  foreground=COLORS["muted"], background=COLORS["panel"]).pack(side="left")
        LinkLabel(sub, url=WEBSITE, text=WEBSITE,
                  background=COLORS["panel"], font=FONT_BOLD).pack(side="right", padx=12)
        ttk.Button(sub, text="Update LIKAcs", style="Primary.TButton",
                   command=self._one_click_update).pack(side="right", padx=6)
        ttk.Button(sub, text="About", command=lambda: show_about(self.root, self._one_click_update)).pack(side="right")
        ttk.Button(sub, text="Minimize to tray", command=self.hide_to_tray).pack(side="right", padx=6)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self._tab_rooms()
        self._tab_stations()
        self._tab_rules()
        self._tab_updates()
        self._tab_settings()
        self._tab_about()

        footer = ttk.Frame(self.root, style="Panel.TFrame")
        footer.pack(fill="x", side="bottom")
        LinkLabel(footer, url=WEBSITE, text=WEBSITE, background=COLORS["panel"],
                  font=FONT_BOLD).pack(side="left", padx=10, pady=6)
        ttk.Label(footer, text=FOOTER, font=FONT_SMALL,
                  foreground=COLORS["muted"], background=COLORS["panel"]).pack(side="left", padx=4)
        ttk.Button(footer, text="Exit", command=self.quit_app).pack(side="right", padx=8)

        self.status_var = tk.StringVar(value=status_bar_text(0, 0))
        status = ttk.Label(self.root, textvariable=self.status_var, style="Muted.TLabel",
                           anchor="w", padding=(8, 4))
        status.pack(fill="x", side="bottom")

    # ------------------------------------------------------------------ rooms
    def _tab_rooms(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Rooms & Matches  ")

        create = ttk.LabelFrame(tab, text=" Create a new room ", style="Card.TLabelframe")
        create.pack(fill="x", padx=8, pady=(8, 4))
        self.new_name = tk.StringVar()
        self.new_game = tk.StringVar(value=self.control.settings.default_game)
        self.new_preset = tk.StringVar(value=self.control.settings.default_preset)
        self.new_map = tk.StringVar(value=self.control.settings.default_map)
        self.new_custom_map = tk.StringVar()
        self.new_host = tk.StringVar()
        self.new_overtime = tk.BooleanVar(value=True)
        self.new_mode = tk.StringVar(value=self.control.settings.server_mode)

        row = ttk.Frame(create, style="Panel.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Name", style="Panel.TLabel").grid(row=0, column=0, padx=(10, 4))
        ttk.Entry(row, textvariable=self.new_name, width=14).grid(row=0, column=1, padx=4)
        ttk.Label(row, text="Game", style="Panel.TLabel").grid(row=0, column=2, padx=(12, 4))
        ttk.Combobox(row, textvariable=self.new_game, width=20, state="readonly",
                     values=["cs2", "cs16"]).grid(row=0, column=3, padx=4)
        ttk.Label(row, text="Preset", style="Panel.TLabel").grid(row=0, column=4, padx=(12, 4))
        ttk.Combobox(row, textvariable=self.new_preset, width=24, state="readonly",
                     values=PRESET_ORDER).grid(row=0, column=5, padx=4)
        ttk.Label(row, text="Map", style="Panel.TLabel").grid(row=0, column=6, padx=(12, 4))
        self.map_combo = ttk.Combobox(row, textvariable=self.new_map, width=18,
                                      values=maps_for("cs2"))
        self.map_combo.grid(row=0, column=7, padx=4)
        ttk.Button(row, text="Create Room", style="Primary.TButton",
                   command=self._create_room).grid(row=0, column=8, padx=14)

        row2 = ttk.Frame(create, style="Panel.TFrame")
        row2.pack(fill="x", pady=(0, 6))
        ttk.Label(row2, text="Host PC", style="Panel.TLabel").grid(row=0, column=0, padx=(10, 4))
        self.host_combo = ttk.Combobox(row2, textvariable=self.new_host, width=26, state="readonly")
        self.host_combo.grid(row=0, column=1, padx=4)
        ttk.Label(row2, text="Server mode", style="Panel.TLabel").grid(row=0, column=2, padx=(12, 4))
        ttk.Combobox(row2, textvariable=self.new_mode, width=14, state="readonly",
                     values=["listen", "dedicated"]).grid(row=0, column=3, padx=4)
        ttk.Checkbutton(row2, text="Overtime ON", variable=self.new_overtime).grid(row=0, column=4, padx=12)
        ttk.Label(row2, text="Custom map", style="Panel.TLabel").grid(row=0, column=5, padx=(12, 4))
        ttk.Entry(row2, textvariable=self.new_custom_map, width=18).grid(row=0, column=6, padx=4)
        ttk.Label(row2, text="(leave Name blank for Room N)", font=FONT_SMALL,
                  foreground=COLORS["muted"], background=COLORS["panel"]).grid(row=0, column=7, padx=12)

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.LabelFrame(body, text=" Rooms (simultaneous matches on one LAN switch) ",
                              style="Card.TLabelframe")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        columns = ("room", "game", "preset", "map", "pcs", "state", "host")
        self.room_tree = ttk.Treeview(left, columns=columns, show="headings", height=12)
        for name, label, width in zip(columns,
                                      ("Room", "Game", "Preset", "Map", "PCs", "State", "Host"),
                                      (100, 70, 100, 120, 60, 80, 130)):
            self.room_tree.heading(name, text=label)
            self.room_tree.column(name, width=width, anchor="w")
        room_scroll = ttk.Scrollbar(left, orient="vertical", command=self.room_tree.yview)
        self.room_tree.configure(yscrollcommand=room_scroll.set)
        self.room_tree.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        room_scroll.pack(side="right", fill="y", pady=6)
        self.room_tree.bind("<<TreeviewSelect>>", self._on_room_select)

        right = ttk.LabelFrame(body, text=" Selected room: settings, PCs & LIVE controls ",
                               style="Card.TLabelframe")
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        detail = ttk.Frame(right, style="Panel.TFrame")
        detail.pack(fill="x", padx=6, pady=6)
        self.detail_game = tk.StringVar()
        self.detail_preset = tk.StringVar()
        self.detail_map = tk.StringVar()
        self.detail_host = tk.StringVar()
        self.detail_overtime = tk.BooleanVar()
        self.detail_mode = tk.StringVar()
        self.detail_slots = tk.StringVar(value="10")
        labeled_entry(detail, "Game", self.detail_game, 0, width=14)
        labeled_entry(detail, "Preset", self.detail_preset, 1, width=14)
        labeled_entry(detail, "Map", self.detail_map, 2, width=14)
        labeled_entry(detail, "Host PC", self.detail_host, 3, width=14)
        labeled_entry(detail, "Custom slots", self.detail_slots, 4, width=14)
        ttk.Checkbutton(detail, text="Overtime", variable=self.detail_overtime).grid(
            row=0, column=2, sticky="w", padx=8)
        ttk.Label(detail, text="Server mode", style="Panel.TLabel").grid(row=1, column=2, sticky="w", padx=8)
        ttk.Combobox(detail, textvariable=self.detail_mode, width=12, state="readonly",
                     values=["listen", "dedicated"]).grid(row=1, column=3, sticky="w")
        ttk.Button(detail, text="Save room settings", command=self._save_room_details).grid(
            row=2, column=2, rowspan=2, padx=8, pady=4, sticky="nsew")

        assign = ttk.LabelFrame(right, text=" Assign PCs to this room  (lika + F10 auto-routes each PC) ",
                                style="Card.TLabelframe")
        assign.pack(fill="both", expand=True, padx=6, pady=4)
        self.assign_checklist = StationChecklist(assign, on_change=self._sync_selection, height=118)
        self.assign_checklist.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Button(assign, text="Apply PC assignment", style="Primary.TButton",
                   command=self._apply_assignment).pack(anchor="w", padx=8, pady=(0, 8))

        controls = ttk.LabelFrame(right, text=" Live cafe admin controls (official RCON / Agent) ",
                                  style="Card.TLabelframe")
        controls.pack(fill="x", padx=6, pady=4)
        grid = ttk.Frame(controls, style="Panel.TFrame")
        grid.pack(fill="x", padx=4, pady=4)
        buttons = [
            ("Start Room", lambda: self._room_action("start"), 0, 0),
            ("Stop Room", lambda: self._room_action("stop"), 0, 1),
            ("Delete Room", lambda: self._room_action("delete"), 0, 2),
            ("Knife Round", lambda: self._live("knife_round"), 1, 0),
            ("Swap Teams", lambda: self._live("swap_teams"), 1, 1),
            ("LIVE! Restart Match (0-0)", lambda: self._live("live_restart"), 1, 2),
            ("Pause Match", lambda: self._live("pause"), 2, 0),
            ("Unpause Match", lambda: self._live("unpause"), 2, 1),
            ("End Warmup", lambda: self._live("end_warmup"), 2, 2),
            ("Kick Bots", lambda: self._live("kick_bots"), 3, 0),
            ("Re-apply Rules", lambda: self._live("apply_rules"), 3, 1),
            ("Restart Round", lambda: self._live("restart_match"), 3, 2),
        ]
        for text, command, row_index, column in buttons:
            ttk.Button(grid, text=text, command=command).grid(
                row=row_index, column=column, sticky="ew", padx=3, pady=3)
        for column in range(3):
            grid.columnconfigure(column, weight=1)
        self.map_live_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.map_live_var, width=18).grid(row=4, column=0, padx=3, pady=3, sticky="ew")
        ttk.Button(grid, text="Change Map Live", command=self._change_map).grid(row=4, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(grid, text="Start & Connect Selected PCs", style="Primary.TButton",
                   command=self._start_connect).grid(row=4, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(grid, text="Disconnect / Return Selected PCs", command=self._disconnect).grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(grid, text="Close Game on Selected PCs", style="Danger.TButton",
                   command=self._close_games).grid(row=5, column=2, sticky="ew", padx=3, pady=3)

        self.log_panel = LogPanel(tab, height=8)
        self.log_panel.pack(fill="x", padx=8, pady=(4, 8))
        self._log(f"LIKAcs Control Center ready - {WEBSITE} - free & open-source")

    # --------------------------------------------------------------- stations
    def _tab_stations(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Station PCs  ")
        top = ttk.LabelFrame(tab, text=" Discovered gaming PCs (automatic LAN IP discovery, no static IPs) ",
                             style="Card.TLabelframe")
        top.pack(fill="both", expand=True, padx=8, pady=8)
        columns = ("pc", "ip", "agent", "games", "assigned", "version", "servers")
        self.station_tree = ttk.Treeview(top, columns=columns, show="headings", height=10)
        for name, label, width in zip(columns,
                                      ("PC", "LAN IP", "Agent", "Games installed", "Assigned room", "Version", "Hosting"),
                                      (150, 130, 80, 180, 150, 80, 120)):
            self.station_tree.heading(name, text=label)
            self.station_tree.column(name, width=width, anchor="w")
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.station_tree.yview)
        self.station_tree.configure(yscrollcommand=scroll.set)
        self.station_tree.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        scroll.pack(side="right", fill="y", pady=6)

        self.station_checklist = StationChecklist(tab, on_change=self._sync_selection, height=120)
        self.station_checklist.pack(fill="x", padx=8, pady=4)

        bar = ttk.Frame(tab, style="Panel.TFrame")
        bar.pack(fill="x", padx=8, pady=(0, 10))
        for text, command in [
            ("1-Click Setup Selected", lambda: self._setup_stations(all_stations=False)),
            ("1-Click Setup ALL PCs", lambda: self._setup_stations(all_stations=True)),
            ("Firewall Rules (UAC)", lambda: self._firewall_stations()),
            ("Auto-start ON", lambda: self._autostart(True)),
            ("Auto-start OFF", lambda: self._autostart(False)),
            ("Rename PC", self._rename_station),
            ("Station status", self._station_status),
            ("Refresh", self._refresh_all),
        ]:
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=3, pady=3)

    # ------------------------------------------------------------------ rules
    def _tab_rules(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Cafe Rules  ")
        head = ttk.Frame(tab, style="Panel.TFrame")
        head.pack(fill="x", padx=10, pady=8)
        ttk.Label(head, text="Pre-loaded cafe rules - editable per room", font=FONT_BOLD,
                  foreground=COLORS["accent"], background=COLORS["panel"]).pack(side="left", padx=6)
        self.rules_room_label = tk.StringVar(value="Select a room in the Rooms tab")
        ttk.Label(head, textvariable=self.rules_room_label, style="Panel.TLabel").pack(side="right", padx=8)

        self.rules_frame = ttk.LabelFrame(tab, text=" Official server cvars (applied via lika_match.cfg + RCON) ",
                                          style="Card.TLabelframe")
        self.rules_frame.pack(fill="both", expand=True, padx=10, pady=4)
        self.rule_vars: dict[str, tk.StringVar] = {}

        bottom = ttk.Frame(tab, style="Panel.TFrame")
        bottom.pack(fill="x", padx=10, pady=8)
        self.rule_overtime = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Overtime ON / OFF", variable=self.rule_overtime).pack(side="left", padx=6)
        ttk.Button(bottom, text="Save Rules to Room", style="Primary.TButton",
                   command=self._save_rules).pack(side="left", padx=8)
        ttk.Button(bottom, text="Restore Cafe Defaults", command=self._restore_rules).pack(side="left", padx=4)
        self.custom_cvar_name = tk.StringVar()
        self.custom_cvar_value = tk.StringVar()
        ttk.Entry(bottom, textvariable=self.custom_cvar_name, width=18).pack(side="left", padx=(18, 3))
        ttk.Entry(bottom, textvariable=self.custom_cvar_value, width=12).pack(side="left", padx=3)
        ttk.Button(bottom, text="Add custom cvar", command=self._add_custom_cvar).pack(side="left", padx=4)

    # ---------------------------------------------------------------- updates
    def _tab_updates(self) -> None:
        """One-click self-update, verified directly from GitHub Releases."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Updates  ")
        self.updates_tab = tab
        from .update_panel import UpdatePanel
        self.update_panel = UpdatePanel(
            tab,
            run_async=self._async,
            on_restart=self.quit_for_update,
            log=self._log,
            on_push=self._push_latest_update,
            auto_check=bool(self.control.settings.auto_check_updates) and not self.smoke,
        )
        self.update_panel.pack(fill="both", expand=True)

    # --------------------------------------------------------------- settings
    def _tab_settings(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  Settings  ")
        frame = ttk.LabelFrame(tab, text=" LAN, join word, F10 key, paths & auto-start ",
                               style="Card.TLabelframe")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        settings = self.control.settings
        self.setting_vars: dict[str, tk.Variable] = {}
        fields = [
            ("lan_key", "LAN shared key", str(settings.lan_key)),
            ("discovery_port", "UDP discovery port", str(settings.discovery_port)),
            ("agent_port", "Agent TCP port", str(settings.agent_port)),
            ("game_port_base", "First game port", str(settings.game_port_base)),
            ("join_word", "Custom join word (lika default)", str(settings.join_word)),
            ("f10_key", "1-key join key", str(settings.f10_key)),
            ("github_owner", "GitHub owner", str(settings.github_owner)),
            ("github_repo", "GitHub repo", str(settings.github_repo)),
            ("default_map", "Default map", str(settings.default_map)),
        ]
        for index, (key, label, value) in enumerate(fields):
            variable = tk.StringVar(value=value)
            self.setting_vars[key] = variable
            labeled_entry(frame, label, variable, index, width=30)
        self.setting_vars["enable_f10_bind"] = tk.BooleanVar(value=settings.enable_f10_bind)
        self.setting_vars["auto_check_updates"] = tk.BooleanVar(value=settings.auto_check_updates)
        self.setting_vars["minimize_to_tray"] = tk.BooleanVar(value=settings.minimize_to_tray)
        self.setting_vars["autostart"] = tk.BooleanVar(value=settings.autostart)
        ttk.Checkbutton(frame, text="Bind F10 to lika (overrides CS 1.6 quit prompt)",
                        variable=self.setting_vars["enable_f10_bind"]).grid(row=9, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(frame, text="Check for updates at startup",
                        variable=self.setting_vars["auto_check_updates"]).grid(row=10, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(frame, text="Minimize to system tray",
                        variable=self.setting_vars["minimize_to_tray"]).grid(row=11, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(frame, text="Auto-start silently with Windows (this PC)",
                        variable=self.setting_vars["autostart"]).grid(row=12, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(frame, text="Manual game paths can be pasted as JSON in settings.json "
                  "(Steam > Manage > Browse local files).", font=FONT_SMALL,
                  foreground=COLORS["muted"], background=COLORS["panel"], wraplength=420,
                  justify="left").grid(row=9, column=2, rowspan=4, sticky="nw", padx=8, pady=6)
        bar = ttk.Frame(tab, style="Panel.TFrame")
        bar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bar, text="Save & Sync to All Station PCs", style="Primary.TButton",
                   command=self._save_settings).pack(side="left", padx=4)
        ttk.Button(bar, text="1-Click Setup on this PC", command=self._setup_local).pack(side="left", padx=4)
        ttk.Button(bar, text="Firewall Rules on this PC (UAC)",
                   command=self._firewall_local).pack(side="left", padx=4)
        ttk.Button(bar, text="Open likaapps.com", command=lambda: open_url(WEBSITE)).pack(side="left", padx=4)
        ttk.Button(bar, text="About", command=lambda: show_about(self.root, self._one_click_update)).pack(side="left", padx=4)

    def _tab_about(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  About  ")
        frame = ttk.LabelFrame(tab, text=" Free & open-source for internet cafes worldwide ",
                               style="Card.TLabelframe")
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(frame, text="LIKAcs", font=FONT_TITLE, foreground=COLORS["accent"],
                  background=COLORS["panel"]).pack(pady=(20, 4))
        LinkLabel(frame, url=WEBSITE, text=WEBSITE,
                  font=FONT_BOLD, background=COLORS["panel"]).pack(pady=4)
        text = tk.Text(frame, wrap="word", background=COLORS["panel2"], foreground=COLORS["fg"],
                       relief="flat", height=18)
        from ..branding import ABOUT_TEXT
        text.insert("1.0", ABOUT_TEXT)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=16, pady=16)
        ttk.Button(frame, text="Open About dialog", command=lambda: show_about(self.root, self._one_click_update)).pack(pady=(0, 16))

    # --------------------------------------------------------------- refresh
    def _refresh_all(self) -> None:
        stations = self.control.online_stations()
        rooms = self.control.rooms.list()
        station_sig = "|".join(
            f"{s.get('id')}:{s.get('label')}:{s.get('ip')}:{s.get('version')}:{len(s.get('servers') or [])}"
            for s in stations
        )
        if station_sig != self._station_signature:
            self._station_signature = station_sig
            self._refresh_station_tree(stations)
            self.assign_checklist.set_stations(stations)
            self.station_checklist.set_stations(stations)
            host_values = [f"{s.get('label')} ({s.get('ip')})" for s in stations]
            self.host_combo.configure(values=host_values)
        room_sig = "|".join(
            f"{r.id}:{r.name}:{r.game}:{r.preset}:{r.map}:{r.state}:{len(r.station_ids)}:{r.port}"
            for r in rooms
        )
        if room_sig != self._room_signature or self._need_refresh:
            self._room_signature = room_sig
            self._refresh_room_tree(rooms)
        self._need_refresh = False
        self.status_var.set(status_bar_text(len(stations),
                                            sum(1 for r in rooms if r.state == "live"),
                                            self.control.last_error))

    def _refresh_station_tree(self, stations: list[dict[str, Any]]) -> None:
        self.station_tree.delete(*self.station_tree.get_children())
        for station in stations:
            station_id = str(station.get("id"))
            room = self.control.rooms.room_for_station(station_id)
            games = ", ".join(str(item.get("game", "")).upper()
                              for item in (station.get("installs") or []) if item.get("exists"))
            servers = ", ".join(str(item.get("room_name", "Room")) for item in (station.get("servers") or []))
            self.station_tree.insert("", "end", iid=station_id, values=(
                station.get("label"), station.get("ip"), station.get("agent_port"),
                games or "-", room.name if room else "-", station.get("version"), servers or "-",
            ))

    def _refresh_room_tree(self, rooms: list[Any]) -> None:
        selected = self.selected_room_id
        self.room_tree.delete(*self.room_tree.get_children())
        for room in rooms:
            host = self.control.station(room.host_station_id) or {}
            self.room_tree.insert("", "end", iid=room.id, values=(
                room.name, room.game.upper(), room.preset, room.map,
                len(room.station_ids), room.state,
                host.get("label") or room.host_ip or room.host_station_id or "-",
            ))
        if selected and self.room_tree.exists(selected):
            self.room_tree.selection_set(selected)
        elif rooms and not selected:
            self.selected_room_id = rooms[0].id
            self.room_tree.selection_set(rooms[0].id)
            self._load_selected_room()

    def _sync_selection(self, source: StationChecklist | None = None) -> None:
        if source is not None:
            self.shared_selected = set(source.get_selected())
            for checklist in (self.assign_checklist, self.station_checklist):
                if checklist is not source:
                    checklist.selected = set(self.shared_selected)
                    for station_id, variable in checklist.vars.items():
                        variable.set(station_id in self.shared_selected)
        else:
            for checklist in (self.assign_checklist, self.station_checklist):
                checklist.selected = set(self.shared_selected)

    # ----------------------------------------------------------- room actions
    def _room(self) -> Any | None:
        return self.control.rooms.get(self.selected_room_id) if self.selected_room_id else None

    def _require_room(self) -> Any | None:
        room = self._room()
        if not room:
            messagebox.showinfo("LIKAcs", "Select or create a room first.")
        return room

    def _on_room_select(self, _event: Any) -> None:
        selection = self.room_tree.selection()
        if not selection:
            return
        self.selected_room_id = selection[0]
        self._load_selected_room()

    def _load_selected_room(self) -> None:
        room = self._room()
        if not room:
            return
        self.detail_game.set(room.game)
        self.detail_preset.set(room.preset)
        self.detail_map.set(room.map)
        host = self.control.station(room.host_station_id) or {}
        self.detail_host.set(str(host.get("label") or room.host_station_id or ""))
        self.detail_overtime.set(room.overtime)
        self.detail_mode.set(room.server_mode)
        self.detail_slots.set(str(room.custom_slots))
        self.map_live_var.set(room.map)
        self.assign_checklist.set_selected(room.station_ids)
        self.shared_selected = set(room.station_ids)
        self._sync_selection()
        self.rules_room_label.set(f"Editing: {room.name} ({room.game.upper()}, {room.preset})")
        self._build_rules_rows(room.rules, room.overtime)

    def _create_room(self) -> None:
        custom_map = self.new_custom_map.get().strip()
        map_name = normalize_map(custom_map) if custom_map else self.new_map.get()
        host_text = self.new_host.get()
        host_id = ""
        for station in self.control.online_stations():
            if f"{station.get('label')} ({station.get('ip')})" == host_text:
                host_id = str(station.get("id"))
                break
        room = self.control.create_room(
            name=self.new_name.get().strip(), game=self.new_game.get(),
            preset=self.new_preset.get(), map=map_name,
            overtime=self.new_overtime.get(), server_mode=self.new_mode.get(),
            host_station_id=host_id,
            station_ids=[host_id] if host_id else [],
        )
        self._log(f"Created {room.name} - {room.preset} on {room.map} ({room.game})")
        self.selected_room_id = room.id
        self._need_refresh = True

    def _save_room_details(self) -> None:
        room = self._require_room()
        if not room:
            return
        host_text = self.detail_host.get()
        host_id = room.host_station_id
        for station in self.control.online_stations():
            if station.get("label") == host_text or f"{station.get('label')} ({station.get('ip')})" == host_text:
                host_id = str(station.get("id"))
                break
        try:
            slots = max(2, min(64, int(self.detail_slots.get())))
        except ValueError:
            slots = 10
        updated = self.control.update_room(room.id, {
            "game": self.detail_game.get(), "preset": self.detail_preset.get(),
            "map": normalize_map(self.detail_map.get()),
            "overtime": self.detail_overtime.get(),
            "server_mode": self.detail_mode.get(), "custom_slots": slots,
        })
        if updated:
            self.control.set_host(room.id, host_id)
        self._log(f"Saved settings for {room.name}")

    def _room_action(self, action: str) -> None:
        room = self._require_room()
        if not room:
            return
        if action == "delete":
            if messagebox.askyesno("LIKAcs", f"Delete {room.name}?"):
                self.control.delete_room(room.id)
                self.selected_room_id = None
                self._log(f"Deleted {room.name}")
            return
        if action == "start":
            self._async(lambda: self.control.start_room(room.id),
                        lambda result: self._log(f"{room.name} started: {result.get('ok')}"),
                        busy=f"Starting {room.name}...")
        else:
            self._async(lambda: self.control.stop_room(room.id),
                        lambda result: self._log(f"{room.name} stopped: {result.get('ok')}"),
                        busy=f"Stopping {room.name}...")

    def _apply_assignment(self) -> None:
        room = self._require_room()
        if not room:
            return
        ids = self.assign_checklist.get_selected()
        self._async(lambda: {"ok": bool(self.control.assign_stations(room.id, ids))},
                    lambda _r: self._log(f"{room.name}: assigned {len(ids)} PC(s); lika_join.cfg updated live"),
                    busy="Routing PCs to their room...")

    def _live(self, action: str) -> None:
        room = self._require_room()
        if not room:
            return
        self._async(lambda: self.control.live_control(room.id, action),
                    lambda result: self._log(
                        f"{room.name} / {action}: " + ("OK" if result.get("ok") else str(result.get("error")))),
                    busy=f"{room.name}: {action}...")

    def _change_map(self) -> None:
        room = self._require_room()
        if not room:
            return
        map_name = normalize_map(self.map_live_var.get())
        self._async(lambda: self.control.live_control(room.id, "change_map", map=map_name),
                    lambda result: self._log(f"{room.name}: change map -> {map_name} ({result.get('ok')})"),
                    busy="Changing map live...")

    def _start_connect(self) -> None:
        room = self._require_room()
        if not room:
            return
        ids = self.shared_selected or set(self.assign_checklist.get_selected())
        if not ids:
            messagebox.showinfo("LIKAcs", "Tick the PCs you want to start & connect first.")
            return
        self._async(lambda: self.control.start_connect_selected(room.id, list(ids)),
                    lambda result: self._log(
                        f"Start & Connect: {sum(1 for value in result.values() if value.get('ok'))}/{len(result)} PC(s)"),
                    busy="Launching Steam clients on selected PCs...")

    def _disconnect(self) -> None:
        room = self._require_room()
        if not room:
            return
        ids = list(self.shared_selected)
        if not ids:
            messagebox.showinfo("LIKAcs", "Select PCs first.")
            return
        self._async(lambda: self.control.disconnect_stations(room.id, ids),
                    lambda result: self._log(f"Disconnect selected PCs: {result.get('ok')}"),
                    busy="Returning selected PCs to main menu...")

    def _close_games(self) -> None:
        ids = list(self.shared_selected)
        if not ids:
            messagebox.showinfo("LIKAcs", "Select PCs first.")
            return
        if not messagebox.askyesno("LIKAcs", f"Close CS2 / CS 1.6 on {len(ids)} selected PC(s)?"):
            return
        self._async(lambda: self.control.close_games(ids),
                    lambda result: self._log(f"Close Game: {result.get('ok')}"),
                    busy="Closing games on selected PCs...")

    # ------------------------------------------------------------ rules editor
    def _build_rules_rows(self, rules: dict[str, str], overtime: bool) -> None:
        for child in self.rules_frame.winfo_children():
            child.destroy()
        self.rule_vars = {}
        ttk.Label(self.rules_frame, text="cvar", font=FONT_BOLD,
                  foreground=COLORS["accent"], background=COLORS["panel"]).grid(row=0, column=0, padx=10, pady=4, sticky="w")
        ttk.Label(self.rules_frame, text="value", font=FONT_BOLD,
                  foreground=COLORS["accent"], background=COLORS["panel"]).grid(row=0, column=1, padx=10, pady=4, sticky="w")
        ttk.Label(self.rules_frame, text="meaning", font=FONT_BOLD,
                  foreground=COLORS["accent"], background=COLORS["panel"]).grid(row=0, column=2, padx=10, pady=4, sticky="w")
        for index, (key, value) in enumerate(sorted(rules.items()), start=1):
            variable = tk.StringVar(value=str(value))
            self.rule_vars[key] = variable
            ttk.Label(self.rules_frame, text=key, style="Panel.TLabel").grid(
                row=index, column=0, sticky="w", padx=10, pady=2)
            ttk.Entry(self.rules_frame, textvariable=variable, width=14).grid(
                row=index, column=1, sticky="w", padx=10, pady=2)
            ttk.Label(self.rules_frame, text=RULE_HELP.get(key, "Custom official server cvar"),
                      font=FONT_SMALL, foreground=COLORS["muted"],
                      background=COLORS["panel"]).grid(row=index, column=2, sticky="w", padx=10, pady=2)
        self.rule_overtime.set(overtime)

    def _save_rules(self) -> None:
        room = self._require_room()
        if not room:
            return
        rules = {key: variable.get() for key, variable in self.rule_vars.items()}
        self.control.update_room(room.id, {"rules": rules, "overtime": self.rule_overtime.get()})
        self._log(f"Saved {len(rules)} cafe rules for {room.name}")

    def _restore_rules(self) -> None:
        room = self._room()
        self._build_rules_rows(dict(DEFAULT_RULES), bool(room.overtime) if room else True)
        self._log("Restored pre-loaded cafe defaults (not saved yet)")

    def _add_custom_cvar(self) -> None:
        name = self.custom_cvar_name.get().strip().replace(" ", "_")
        value = self.custom_cvar_value.get().strip()
        room = self._room()
        if not room or not name or not value:
            return
        rules = dict(room.rules)
        rules[name] = value
        self.control.update_room(room.id, {"rules": rules})
        self._build_rules_rows(rules, room.overtime)
        self.custom_cvar_name.set("")
        self.custom_cvar_value.set("")
        self._log(f"Added custom cvar {name} = {value}")

    # ---------------------------------------------------------- station admin
    def _selected_station_ids(self, all_stations: bool = False) -> list[str]:
        if all_stations:
            return [str(station.get("id")) for station in self.control.online_stations()]
        return list(self.shared_selected)

    def _setup_stations(self, all_stations: bool) -> None:
        ids = self._selected_station_ids(all_stations)
        if not ids:
            messagebox.showinfo("LIKAcs", "No Station PCs selected / discovered.")
            return
        def work() -> dict[str, Any]:
            results = {}
            for station_id in ids:
                results[station_id] = self.control.setup_station(station_id, firewall=False, autostart=False)
            return {"ok": True, "results": results}
        self._async(work, lambda result: self._log(f"1-Click Setup sent to {len(ids)} PC(s)"),
                    busy="Running 1-Click Station Setup over LAN...")

    def _firewall_stations(self) -> None:
        ids = self._selected_station_ids() or self._selected_station_ids(all_stations=True)
        def work() -> dict[str, Any]:
            return {"ok": True, "results": {sid: self.control.firewall_station(sid, elevate=True) for sid in ids}}
        self._async(work, lambda _r: self._log(f"Firewall UAC request sent to {len(ids)} PC(s)"),
                    busy="Requesting Windows Defender Firewall allow rules...")

    def _autostart(self, enabled: bool) -> None:
        ids = self._selected_station_ids()
        if not ids:
            messagebox.showinfo("LIKAcs", "Select Station PCs first.")
            return
        def work() -> dict[str, Any]:
            return {"ok": True, "results": {sid: self.control.autostart_station(sid, enabled) for sid in ids}}
        self._async(work, lambda _r: self._log(f"Auto-start {'ON' if enabled else 'OFF'} for {len(ids)} PC(s)"))

    def _rename_station(self) -> None:
        ids = self._selected_station_ids()
        if len(ids) != 1:
            messagebox.showinfo("LIKAcs", "Select exactly one Station PC in the checklist.")
            return
        label = simpledialog.askstring("Rename PC", "Cafe PC label (e.g. PC 1):", parent=self.root)
        if label:
            self.control.rename_station(ids[0], label)
            self._log(f"Renamed station to {label}")

    def _station_status(self) -> None:
        ids = self._selected_station_ids()
        if len(ids) != 1:
            messagebox.showinfo("LIKAcs", "Select exactly one Station PC.")
            return
        self._async(lambda: self.control.station_status(ids[0]),
                    lambda result: messagebox.showinfo(
                        "Station status",
                        f"Version: {result.get('version')}\nLabel: {result.get('label')}\n"
                        f"IP: {result.get('ip')}\nJoin word: {result.get('join_word')}\n"
                        f"F10: {result.get('f10_key')}\nInstalls: {len(result.get('installs') or [])}\n"
                        f"Auto-start: {result.get('autostart', {}).get('enabled')}"))

    # --------------------------------------------------------------- updates
    def _one_click_update(self) -> None:
        """Header / About / tray entry point: show the Updates tab and update."""
        self.show_window()
        try:
            self.notebook.select(self.updates_tab)
        except tk.TclError:
            pass
        self.update_panel.one_click()

    def _push_latest_update(self, progress: Callable[..., None],
                            restart_agents: bool = False) -> dict[str, Any]:
        """Advanced rollout: check GitHub, verify one exe, push to all stations."""
        checked = self.control.check_updates()
        if not checked.get("ok"):
            return {"ok": False, "results": [], "error": str(checked.get("error"))}
        release = checked.get("release")
        if release is None:
            return {"ok": False, "results": [], "error": "no release metadata"}
        downloaded = self.control.download_update(release, progress)
        if not downloaded.get("ok"):
            return {"ok": False, "results": [], "error": str(downloaded.get("error"))}
        return self.control.push_update(
            str(downloaded["path"]), str(downloaded.get("version") or checked.get("latest")),
            progress=progress, restart_agents=restart_agents)

    # --------------------------------------------------------------- settings
    def _save_settings(self) -> None:
        changes: dict[str, Any] = {}
        for key, variable in self.setting_vars.items():
            value = variable.get()
            if key in ("discovery_port", "agent_port", "game_port_base"):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    messagebox.showerror("LIKAcs", f"{key} must be a number")
                    return
            changes[key] = value
        self._async(lambda: {"ok": True, "results": self.control.sync_settings(changes)},
                    lambda _r: (self._log("Settings saved & synced to all online Station PCs"),
                                messagebox.showinfo("LIKAcs", "Settings saved and pushed to all online Station PCs.")),
                    busy="Saving settings & syncing LAN key to stations...")

    def _setup_local(self) -> None:
        self._async(lambda: one_click_setup(self.control.settings),
                    lambda report: self._log(
                        f"Local 1-Click Setup: {'OK' if report.get('ok') else 'no game installs found'} - "
                        + "; ".join(report.get("steps", [])[:2])),
                    busy="Detecting Steam libraries and writing official cfg files...")

    def _firewall_local(self) -> None:
        result = apply_firewall_rules(self.control.settings, {})
        if result.get("needs_admin"):
            elevated = elevate(["--elevated-firewall"])
            self._log(f"Firewall: launched elevated helper ({elevated.get('ok')})")
        else:
            self._log(f"Firewall rules: {'OK' if result.get('ok') else result.get('error')}")

    # ------------------------------------------------------------------- tray
    def _tray_command(self, command: str) -> None:
        if command == "website":
            open_url(WEBSITE)
        elif command == "show":
            self.show_window()
        elif command == "about":
            show_about(self.root, self._one_click_update)
        elif command == "updates":
            self._one_click_update()
        elif command == "exit":
            self.quit_app()

    def hide_to_tray(self) -> None:
        if self.control.settings.minimize_to_tray:
            self.root.withdraw()
            self.tray.notify("LIKAcs", f"Minimized to tray - right-click for live room status - {WEBSITE}")
        else:
            self.quit_app()

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def quit_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.control.stop()
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
