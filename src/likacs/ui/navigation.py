"""Modern sidebar page container (a drop-in, Notebook-compatible shell).

``SidebarBook`` implements the tiny part of ``ttk.Notebook`` that the Control
Center uses — ``add(page, text=...)`` and ``select(page)`` — so every existing
page builder keeps working unchanged while the app gets a real left-hand
navigation rail, quick actions and a permanent VAC-safe badge.

Only ttk widgets and tuple fonts are used: Tk parses option-database strings
only when a widget is created, and an unbraced "Segoe UI" font there was the
v1.0.1 startup crash.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .. import VERSION, WEBSITE
from .theme import COLORS, FONT_SMALL
from .widgets import LinkLabel


class SidebarBook(ttk.Frame):
    """Left sidebar + one visible content page, with Notebook-like API."""

    def __init__(self, parent: tk.Misc, *,
                 on_update: Callable[[], None] | None = None,
                 on_create_room: Callable[[], None] | None = None,
                 on_help: Callable[[], None] | None = None) -> None:
        super().__init__(parent, style="Book.TFrame")
        self._pages: list[dict[str, Any]] = []
        self._current: tk.Widget | None = None

        self.nav = ttk.Frame(self, style="Sidebar.TFrame", width=238)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)

        ttk.Label(self.nav, text="LIKAcs", style="SidebarLogo.TLabel").pack(
            anchor="w", padx=20, pady=(22, 0))
        ttk.Label(self.nav, text="LAN Server & Match Suite",
                  style="SidebarSub.TLabel").pack(anchor="w", padx=20)
        LinkLabel(self.nav, url=WEBSITE, text=WEBSITE, font=FONT_SMALL,
                  background=COLORS["sidebar"]).pack(anchor="w", padx=20, pady=(2, 14))
        ttk.Separator(self.nav, orient="horizontal").pack(fill="x", padx=20, pady=(0, 12))

        ttk.Label(self.nav, text="WORKSPACE", style="SidebarSection.TLabel").pack(
            anchor="w", padx=20, pady=(0, 8))
        self.nav_items = ttk.Frame(self.nav, style="Sidebar.TFrame")
        self.nav_items.pack(fill="x")

        ttk.Separator(self.nav, orient="horizontal").pack(fill="x", padx=20, pady=(16, 12))
        ttk.Label(self.nav, text="QUICK ACTIONS", style="SidebarSection.TLabel").pack(
            anchor="w", padx=20, pady=(0, 8))
        ttk.Button(self.nav, text="↻  Update LIKAcs", style="Primary.TButton",
                   command=on_update or (lambda: None)).pack(fill="x", padx=20, pady=(0, 6))
        ttk.Button(self.nav, text="+  Create a room",
                   command=on_create_room or (lambda: None)).pack(fill="x", padx=20)

        self.vac = ttk.Frame(self.nav, style="Vac.TFrame", padding=(12, 10))
        self.vac.pack(fill="x", padx=20, pady=(24, 0))
        ttk.Label(self.vac, text="◆  100% VAC-safe", style="Vac.TLabel").pack(anchor="w")
        ttk.Label(self.vac, text="No memory access, no DLL", style="VacSub.TLabel").pack(anchor="w")
        ttk.Label(self.vac, text="injection, no game edits.", style="VacSub.TLabel").pack(anchor="w")

        bottom = ttk.Frame(self.nav, style="Sidebar.TFrame")
        bottom.pack(side="bottom", fill="x", pady=(0, 18))
        ttk.Label(bottom, text="Free & open-source", style="SidebarSub.TLabel").pack(
            anchor="w", padx=20)
        ttk.Label(bottom, text=f"v{VERSION}  ·  Windows 10 / 11",
                  style="SidebarSub.TLabel").pack(anchor="w", padx=20)
        if on_help:
            ttk.Button(bottom, text="Help & docs →", style="Link.TButton",
                       command=on_help).pack(anchor="w", padx=18, pady=(8, 0))

    # ------------------------------------------------------------- public API
    def add(self, child: tk.Widget, text: str = "", badge: str = "",
            **_kwargs: Any) -> tk.Widget:
        """Register a page (same signature shape as ``Notebook.add``)."""
        label = text.strip()
        row = ttk.Frame(self.nav_items, style="NavRow.TFrame")
        row.pack(fill="x", padx=10, pady=2)
        button = ttk.Button(row, text=label, style="Nav.TButton",
                            command=lambda: self.select(child))
        button.pack(side="left", fill="x", expand=True)
        badge_label = ttk.Label(row, text=badge, style="NavBadge.TLabel", width=4,
                                anchor="e")
        if badge:
            badge_label.pack(side="right", padx=(2, 8))
        self._pages.append({"page": child, "label": label, "row": row,
                            "button": button, "badge": badge_label})
        if self._current is None:
            self.select(child)
        return child

    def select(self, child: tk.Widget | str | None = None) -> None:
        """Show one page. Accepts a widget (Notebook-style) or ignores None."""
        if child is None or isinstance(child, str):
            return
        for entry in self._pages:
            try:
                entry["page"].pack_forget()
            except tk.TclError:
                pass
            entry["button"].configure(style="Nav.TButton")
            entry["row"].configure(style="NavRow.TFrame")
        child.pack(side="right", fill="both", expand=True, padx=18, pady=14)
        self._current = child
        for entry in self._pages:
            if entry["page"] is child:
                entry["button"].configure(style="NavActive.TButton")
                entry["row"].configure(style="NavActiveRow.TFrame")
                break

    def set_badge(self, child: tk.Widget, value: str) -> None:
        """Update the small counter on a navigation row."""
        for entry in self._pages:
            if entry["page"] is child:
                label: ttk.Label = entry["badge"]
                label.configure(text=value)
                if value:
                    label.pack(side="right", padx=(2, 8))
                else:
                    label.pack_forget()
                break

    def current(self) -> tk.Widget | None:
        return self._current

    def page_count(self) -> int:
        return len(self._pages)

