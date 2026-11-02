"""LIKAcs Setup wizard - a real, friendly Windows installation experience.

Steps: Welcome -> Install options -> Progress -> Done. No administrator rights,
no UAC, no downloads: LIKAcs.exe is embedded in LIKAcs-Setup.exe.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .. import VERSION, WEBSITE, WEBSITE_LABEL
from ..branding import HEADER_SUBTITLE
from ..installer import (APP_EXE, InstallPlan, default_install_dir, install,
                         payload_path)
from .theme import COLORS, FONT, FONT_BOLD, FONT_SMALL, FONT_TITLE, apply_theme
from .widgets import LinkLabel

LICENSE_SUMMARY = (
    "LIKAcs is 100% free and open source (MIT license), for cafe owners worldwide.\n\n"
    "It is 100% VAC-safe: it never reads or writes game process memory, injects "
    "DLLs, or modifies game binaries. It only writes official .cfg files, uses "
    "official sv_lan 1 / -usercon RCON and steam://connect/ links.\n\n"
    "No SteamCMD, no extra 60 GB download, and no Python or Node is required on "
    "any gaming PC. The host PC player can play normally.\n\n"
    "By installing you agree to the MIT license included with the release."
)


class SetupWizard:
    """Four-page installer. ``smoke=True`` builds every widget without running."""

    def __init__(self, root: tk.Tk | None = None, install_dir: str | None = None,
                 smoke: bool = False) -> None:
        self.smoke = smoke
        self.root = root or tk.Tk()
        self.root.title(f"LIKAcs Setup v{VERSION}")
        self.root.geometry("660x470")
        self.root.minsize(620, 450)
        self.root.resizable(False, False)
        apply_theme(self.root)
        self.root.withdraw()

        self.install_dir = tk.StringVar(value=str(Path(install_dir) if install_dir
                                                  else default_install_dir()))
        self.desktop = tk.BooleanVar(value=True)
        self.start_menu = tk.BooleanVar(value=True)
        self.autostart = tk.BooleanVar(value=False)
        self.launch = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready to install")
        self.plan_result: dict[str, Any] = {}
        self._page_index = 0
        self.pages: list[ttk.Frame] = []

        self._build_header()
        self._build_body()
        self._build_footer()
        self._show_page(0)
        self.root.update_idletasks()

    # ------------------------------------------------------------------ chrome
    def _build_header(self) -> None:
        header = ttk.Frame(self.root, style="Panel.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="  LIKAcs", font=FONT_TITLE,
                  foreground=COLORS["accent"], background=COLORS["panel"]).pack(
                      anchor="w", pady=(14, 0), padx=10)
        ttk.Label(header, text=f"  Setup  -  version {VERSION}  -  {HEADER_SUBTITLE}",
                  font=FONT_SMALL, foreground=COLORS["muted"],
                  background=COLORS["panel"]).pack(anchor="w", padx=10)
        LinkLabel(header, url=WEBSITE, text=WEBSITE, font=FONT_BOLD,
                  background=COLORS["panel"]).pack(side="right", padx=14, pady=8)
        ttk.Label(header, text="Free & open-source  |  100% VAC-safe",
                  font=FONT_SMALL, foreground=COLORS["muted"],
                  background=COLORS["panel"]).pack(side="right", padx=4)

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.root, style="Panel.TFrame")
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, textvariable=self.status, font=FONT_SMALL,
                  foreground=COLORS["muted"], background=COLORS["panel"]).pack(
                      side="left", padx=12, pady=10)
        self.back_button = ttk.Button(footer, text="< Back", command=self._back)
        self.back_button.pack(side="right", padx=(4, 12), pady=8)
        self.next_button = ttk.Button(footer, text="Next >", style="Primary.TButton",
                                      command=self._next)
        self.next_button.pack(side="right", padx=4, pady=8)
        ttk.Button(footer, text="Cancel", command=self._cancel).pack(
            side="right", padx=4, pady=8)

    def _build_body(self) -> None:
        self.body = ttk.Frame(self.root, padding=16)
        self.body.pack(fill="both", expand=True)
        self.pages = [self._page_welcome(), self._page_options(),
                      self._page_progress(), self._page_done()]
        for page in self.pages:
            page.pack(fill="both", expand=True)

    # ------------------------------------------------------------------- pages
    def _page_welcome(self) -> ttk.Frame:
        page = ttk.Frame(self.body)
        ttk.Label(page, text="Welcome to LIKAcs", font=FONT_TITLE,
                  foreground=COLORS["accent"]).pack(anchor="w", pady=(4, 10))
        ttk.Label(page, text=(
            "The LAN Server & Match Management Suite for CS2 and CS 1.6 internet cafes.\n\n"
            "Run matches from 2 PCs to 50+ PCs, with simultaneous rooms, automatic\n"
            "PC discovery, one-key joining, live admin controls and one-click updates."),
            justify="left", font=FONT, wraplength=590).pack(anchor="w")
        notes = ttk.LabelFrame(page, text=" Free, open-source and safe ",
                               style="Card.TLabelframe")
        notes.pack(fill="both", expand=True, pady=14)
        ttk.Label(notes, text=LICENSE_SUMMARY, justify="left", wraplength=560,
                  font=FONT_SMALL, style="Panel.TLabel").pack(anchor="w", padx=10, pady=8)
        return page

    def _page_options(self) -> ttk.Frame:
        page = ttk.Frame(self.body)
        ttk.Label(page, text="Installation options", font=FONT_TITLE,
                  foreground=COLORS["accent"]).pack(anchor="w", pady=(4, 12))
        location = ttk.LabelFrame(page, text=" Install location (no administrator rights needed) ",
                                  style="Card.TLabelframe")
        location.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(location, style="Panel.TFrame")
        row.pack(fill="x", padx=10, pady=10)
        ttk.Entry(row, textvariable=self.install_dir, width=58).pack(side="left", fill="x",
                                                                     expand=True, padx=(0, 6))
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="right")

        options = ttk.LabelFrame(page, text=" Shortcuts and startup ",
                                 style="Card.TLabelframe")
        options.pack(fill="both", expand=True)
        ttk.Checkbutton(options, text="Create a Desktop shortcut to LIKAcs",
                        variable=self.desktop).pack(anchor="w", padx=12, pady=(10, 3))
        ttk.Checkbutton(options, text="Add Start Menu shortcuts (LIKAcs, Control Center, Station Agent)",
                        variable=self.start_menu).pack(anchor="w", padx=12, pady=3)
        ttk.Checkbutton(options, text="Start the Station Agent silently with Windows",
                        variable=self.autostart).pack(anchor="w", padx=12, pady=3)
        ttk.Checkbutton(options, text="Launch LIKAcs when setup finishes",
                        variable=self.launch).pack(anchor="w", padx=12, pady=3)
        ttk.Label(options, text="Settings are kept in your user profile and survive updates.",
                  font=FONT_SMALL, foreground=COLORS["muted"],
                  style="Panel.TLabel").pack(anchor="w", padx=12, pady=(8, 10))
        return page

    def _page_progress(self) -> ttk.Frame:
        page = ttk.Frame(self.body)
        ttk.Label(page, text="Installing LIKAcs", font=FONT_TITLE,
                  foreground=COLORS["accent"]).pack(anchor="w", pady=(4, 14))
        self.progress = ttk.Progressbar(page, mode="determinate", maximum=100, length=560)
        self.progress.pack(fill="x", pady=(0, 12))
        self.progress_log = tk.Text(page, height=12, wrap="word", state="disabled",
                                    background=COLORS["panel2"], foreground=COLORS["fg"],
                                    relief="flat", font=("Consolas", 9))
        self.progress_log.pack(fill="both", expand=True)
        ttk.Label(page, text=f"Installing v{VERSION} from {WEBSITE_LABEL}",
                  font=FONT_SMALL, foreground=COLORS["muted"]).pack(anchor="w", pady=(10, 0))
        return page

    def _page_done(self) -> ttk.Frame:
        page = ttk.Frame(self.body)
        ttk.Label(page, text="Installation complete", font=FONT_TITLE,
                  foreground=COLORS["green"]).pack(anchor="w", pady=(10, 12))
        ttk.Label(page, text=(
            "LIKAcs is installed on this PC.\n\n"
            "On the owner's laptop: open LIKAcs and choose 'Open Control Center'.\n"
            "On each gaming PC: open LIKAcs and choose 'Start Station Agent'.\n\n"
            "Future versions install with a single click on 'Update LIKAcs'\n"
            "inside the app - downloaded and verified directly from GitHub."),
            justify="left", font=FONT, wraplength=590).pack(anchor="w")
        self.done_detail = ttk.Label(page, text="", font=FONT_SMALL,
                                     foreground=COLORS["muted"], wraplength=590,
                                     justify="left")
        self.done_detail.pack(anchor="w", pady=14)
        LinkLabel(page, url=WEBSITE, text=WEBSITE, font=FONT_BOLD).pack(anchor="w")
        return page

    # ----------------------------------------------------------------- actions
    def _show_page(self, index: int) -> None:
        self._page_index = max(0, min(index, len(self.pages) - 1))
        for number, page in enumerate(self.pages):
            page.pack_forget()
        self.pages[self._page_index].pack(fill="both", expand=True)
        self.back_button.configure(state="normal" if 0 < self._page_index < 2 else "disabled")
        labels = ["Next >", "Install", "Next >", "Finish"]
        self.next_button.configure(text=labels[self._page_index])
        self.root.update_idletasks()

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.install_dir.get(),
                                         title="Choose install folder")
        if chosen:
            self.install_dir.set(str(Path(chosen) / "LIKAcs"))

    def _log_line(self, text: str) -> None:
        def write() -> None:
            self.progress_log.configure(state="normal")
            self.progress_log.insert("end", text + "\n")
            self.progress_log.see("end")
            self.progress_log.configure(state="disabled")
        self.root.after(0, write)

    def _progress(self, label: str, percent: int) -> None:
        def update() -> None:
            self.progress["value"] = percent
            self.status.set(label)
            self._log_line(f"[{percent:3d}%] {label}")
        self.root.after(0, update)

    def _cancel(self) -> None:
        if self.smoke:
            return
        if messagebox.askyesno("LIKAcs Setup", "Cancel the installation?"):
            self.root.destroy()

    def _back(self) -> None:
        self._show_page(self._page_index - 1)

    def _next(self) -> None:
        if self._page_index == 0:
            self._show_page(1)
        elif self._page_index == 1:
            self._start_install()
        elif self._page_index == 2:
            self._show_page(3)
        else:
            self._finish()

    def _start_install(self) -> None:
        if self.smoke:
            return
        if not payload_path().is_file():
            messagebox.showerror("LIKAcs Setup",
                                 "The embedded LIKAcs.exe was not found in this setup package.")
            return
        self._show_page(2)
        self.next_button.configure(state="disabled")
        self.back_button.configure(state="disabled")

        plan = InstallPlan(
            install_dir=Path(self.install_dir.get()),
            desktop_shortcut=self.desktop.get(),
            start_menu_shortcut=self.start_menu.get(),
            autostart_station=self.autostart.get(),
            launch_after=self.launch.get(),
        )

        def worker() -> None:
            self.plan_result = install(plan, self._progress)
            self.root.after(0, self._install_done)

        threading.Thread(target=worker, name="likacs-setup", daemon=True).start()

    def _install_done(self) -> None:
        result = self.plan_result
        self.next_button.configure(state="normal")
        if not result.get("ok"):
            self.status.set("Installation failed")
            self._log_line(f"ERROR: {result.get('error')}")
            messagebox.showerror("LIKAcs Setup",
                                 f"Installation failed:\n{result.get('error')}")
            self.back_button.configure(state="normal")
            return
        self.done_detail.configure(
            text=f"Installed to: {result.get('install_dir')}\n"
                 f"Shortcuts created: {len(result.get('shortcuts') or [])}\n"
                 f"Version: v{result.get('version')}  -  {WEBSITE}")
        self.status.set("Installation complete")
        self._show_page(3)

    def _finish(self) -> None:
        if self.smoke:
            return
        if self.launch.get():
            from ..installer import launch_app
            launch_app(Path(self.install_dir.get()) / APP_EXE)
        self.root.destroy()

    def run(self) -> int:
        self.root.deiconify()
        self.root.mainloop()
        return 0


def run_wizard(install_dir: str | None = None) -> int:
    """Entry point for the setup executable."""
    wizard = SetupWizard(install_dir=install_dir)
    return wizard.run()


def smoke_wizard(root: tk.Tk) -> None:
    """Construct every wizard page against a real Tk root (CI guard)."""
    wizard = SetupWizard(root=root, smoke=True)
    for index in range(len(wizard.pages)):
        wizard._show_page(index)
        root.update_idletasks()
    wizard.root.withdraw()
