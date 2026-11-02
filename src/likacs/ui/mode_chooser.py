"""First-run chooser for the unified LIKAcs.exe."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .. import VERSION, WEBSITE
from ..util import open_url
from .theme import COLORS, FONT_SMALL, FONT_TITLE
from .widgets import LinkLabel


def choose_mode(parent: tk.Tk, on_control: Callable[[], None],
                on_station: Callable[[], None]) -> None:
    """Render the chooser inside an existing hidden Tk root."""
    parent.title(f"LIKAcs v{VERSION} - choose mode")
    parent.geometry("620x360")
    parent.resizable(False, False)
    parent.deiconify()
    for child in parent.winfo_children():
        child.destroy()

    ttk.Label(parent, text="LIKAcs", font=FONT_TITLE,
              foreground=COLORS["accent"]).pack(pady=(22, 0))
    ttk.Label(parent, text="LAN Server & Match Management Suite  -  CS2 + CS 1.6 cafes",
              style="Sub.TLabel").pack(pady=(2, 2))
    LinkLabel(parent, url=WEBSITE, text=WEBSITE, font=("Segoe UI", 10, "bold underline")).pack(pady=(0, 18))

    cards = ttk.Frame(parent, style="Panel.TFrame")
    cards.pack(fill="both", expand=True, padx=24, pady=6)

    left = ttk.LabelFrame(cards, text=" Control Center (dashboard) ", style="Card.TLabelframe")
    left.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=6)
    ttk.Label(left, text="Run this on the cafe owner's workspace laptop\n"
              "(or directly on PC 1 / any gaming PC).\n\n"
              "Create rooms, assign PCs, live RCON controls,\n"
              "steam://connect/ launch and one-click updates.\n\n"
              "No Steam / CS2 installation needed here.",
              style="Panel.TLabel", justify="left", wraplength=250).pack(padx=10, pady=10)
    ttk.Button(left, text="Open Control Center", style="Primary.TButton",
               command=on_control).pack(padx=10, pady=(0, 16))

    right = ttk.LabelFrame(cards, text=" Station Agent (this gaming PC) ", style="Card.TLabelframe")
    right.pack(side="right", fill="both", expand=True, padx=(8, 0), pady=6)
    ttk.Label(right, text="Run this on every gaming PC.\n\n"
              "A few MB, sits in the system tray, discovers\n"
              "the LAN, hosts matches with the already\n"
              "installed CS2 / CS 1.6 and writes lika_join.cfg.\n\n"
              "1-Click Station Setup + firewall rules.",
              style="Panel.TLabel", justify="left", wraplength=250).pack(padx=10, pady=10)
    ttk.Button(right, text="Start Station Agent", style="Primary.TButton",
               command=on_station).pack(padx=10, pady=(0, 16))

    ttk.Label(parent, text="100% free & open-source  -  100% VAC-safe  -  no SteamCMD, no extra 60 GB",
              font=FONT_SMALL, foreground=COLORS["muted"]).pack(pady=(4, 12))
