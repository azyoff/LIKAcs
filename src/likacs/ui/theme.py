"""Dark cafe dashboard theme (ttk, no external packages)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

COLORS = {
    "bg": "#0b1220",
    "panel": "#121e33",
    "panel2": "#182742",
    "border": "#24375a",
    "fg": "#e8eef9",
    "muted": "#94a3b8",
    "accent": "#22d3ee",
    "accent_dark": "#0e7490",
    "green": "#34d399",
    "amber": "#fbbf24",
    "red": "#f87171",
    "link": "#67e8f9",
}

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)


def apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(background=COLORS["bg"])
    # option_add needs a single Tcl font string; a Python tuple would be
    # flattened into extra arguments and silently become an option priority.
    root.option_add("*Font", "Segoe UI 10")
    root.option_add("*Background", COLORS["panel"])

    style.configure(".", background=COLORS["bg"], foreground=COLORS["fg"],
                    fieldbackground=COLORS["panel2"], font=FONT)
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Panel.TFrame", background=COLORS["panel"], relief="flat")
    style.configure("Card.TLabelframe", background=COLORS["panel"],
                    foreground=COLORS["accent"], bordercolor=COLORS["border"])
    style.configure("Card.TLabelframe.Label", background=COLORS["panel"],
                    foreground=COLORS["accent"], font=FONT_BOLD)
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["fg"])
    style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["fg"])
    style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["fg"], font=FONT_TITLE)
    style.configure("Sub.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=FONT_SMALL)
    style.configure("Accent.TLabel", background=COLORS["bg"], foreground=COLORS["accent"], font=FONT_BOLD)
    style.configure("TButton", background=COLORS["panel2"], foreground=COLORS["fg"],
                    bordercolor=COLORS["border"], padding=(9, 5), font=FONT)
    style.map("TButton", background=[("active", COLORS["accent_dark"]), ("pressed", COLORS["accent_dark"])])
    style.configure("Primary.TButton", background=COLORS["accent_dark"], foreground="#ffffff",
                    font=FONT_BOLD, padding=(10, 6))
    style.map("Primary.TButton", background=[("active", "#0891b2")])
    style.configure("Danger.TButton", background="#7f1d1d", foreground="#ffffff", padding=(9, 5))
    style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["fg"])
    style.map("TCheckbutton", background=[("active", COLORS["bg"])])
    style.configure("TEntry", fieldbackground=COLORS["panel2"], foreground=COLORS["fg"],
                    insertcolor=COLORS["fg"], bordercolor=COLORS["border"])
    style.configure("TCombobox", fieldbackground=COLORS["panel2"], foreground=COLORS["fg"],
                    background=COLORS["panel2"], arrowcolor=COLORS["accent"])
    style.configure("TNotebook", background=COLORS["bg"], bordercolor=COLORS["border"])
    style.configure("TNotebook.Tab", background=COLORS["panel2"], foreground=COLORS["muted"],
                    padding=(14, 7), font=FONT_BOLD)
    style.map("TNotebook.Tab", background=[("selected", COLORS["panel"])],
              foreground=[("selected", COLORS["accent"])])
    style.configure("Treeview", background=COLORS["panel"], foreground=COLORS["fg"],
                    fieldbackground=COLORS["panel"], bordercolor=COLORS["border"],
                    rowheight=24, font=FONT_SMALL)
    style.configure("Treeview.Heading", background=COLORS["panel2"], foreground=COLORS["accent"],
                    font=FONT_BOLD)
    style.map("Treeview", background=[("selected", COLORS["accent_dark"])],
              foreground=[("selected", "#ffffff")])
    style.configure("TProgressbar", background=COLORS["accent"], troughcolor=COLORS["panel2"])
    style.configure("TSeparator", background=COLORS["border"])
    return style
