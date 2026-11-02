"""About dialog with clickable likaapps.com branding and update check."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import GITHUB_URL, LICENSE_NAME, VERSION, WEBSITE
from ..branding import ABOUT_TEXT
from ..util import open_url
from .theme import COLORS, FONT_BOLD, FONT_SMALL, FONT_TITLE
from .widgets import LinkLabel


def show_about(parent: tk.Misc, on_check_updates: Callable[[], None] | None = None) -> None:
    window = tk.Toplevel(parent)
    window.title("About LIKAcs")
    window.configure(background=COLORS["bg"])
    window.geometry("600x480")
    window.resizable(False, False)
    window.transient(parent)

    ttk.Label(window, text="LIKAcs", font=FONT_TITLE,
              foreground=COLORS["accent"], background=COLORS["bg"]).pack(pady=(18, 2))
    LinkLabel(window, url=WEBSITE, text=WEBSITE,
              font=FONT_BOLD, background=COLORS["bg"]).pack(pady=(0, 12))

    frame = ttk.LabelFrame(window, text=" About this project ", style="Card.TLabelframe")
    frame.pack(fill="both", expand=True, padx=18, pady=6)
    text = tk.Text(frame, wrap="word", background=COLORS["panel2"], foreground=COLORS["fg"],
                   relief="flat", font=("Segoe UI", 10), height=13)
    text.insert("1.0", ABOUT_TEXT + f"\n\nSource code: {GITHUB_URL}\nLicense: {LICENSE_NAME}")
    text.configure(state="disabled")
    text.pack(fill="both", expand=True, padx=8, pady=8)

    buttons = ttk.Frame(window, style="Panel.TFrame")
    buttons.pack(fill="x", padx=18, pady=12)
    ttk.Button(buttons, text="Open likaapps.com", command=lambda: open_url(WEBSITE)).pack(side="left")
    ttk.Button(buttons, text="View source on GitHub", command=lambda: open_url(GITHUB_URL)).pack(side="left", padx=6)
    if on_check_updates:
        ttk.Button(buttons, text="Check for Updates",
                   command=lambda: (on_check_updates(), window.destroy())).pack(side="left", padx=6)
    ttk.Button(buttons, text="Close", command=window.destroy,
               style="Primary.TButton").pack(side="right")
    ttk.Label(window, text=f"v{VERSION}  -  free & open-source for every internet cafe",
              font=FONT_SMALL, foreground=COLORS["muted"],
              background=COLORS["bg"]).pack(pady=(0, 10))
