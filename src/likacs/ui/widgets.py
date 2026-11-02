"""Reusable Tkinter widgets: website links, log panel, scroll frame, PC checklist."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable

from .. import WEBSITE, WEBSITE_LABEL
from ..util import format_duration, open_url
from .theme import COLORS, FONT_MONO, FONT_SMALL


class LinkLabel(ttk.Label):
    """Clickable likaapps.com label used in header, footer, About and menus."""

    def __init__(self, parent: tk.Misc, url: str = WEBSITE,
                 text: str | None = None, **kwargs: Any) -> None:
        super().__init__(parent, text=text or WEBSITE, foreground=COLORS["link"],
                         background=kwargs.pop("background", COLORS["bg"]),
                         font=kwargs.pop("font", ("Segoe UI", 10, "bold underline")),
                         cursor="hand2", **kwargs)
        self.url = url
        self.bind("<Button-1>", lambda _event: open_url(self.url))


class LogPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, height: int = 9, **kwargs: Any) -> None:
        super().__init__(parent, style="Panel.TFrame", **kwargs)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled",
                            background=COLORS["panel2"], foreground=COLORS["fg"],
                            insertbackground=COLORS["fg"], relief="flat", font=FONT_MONO)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scroll.pack(side="right", fill="y", pady=6, padx=(0, 6))

    def write(self, message: str) -> None:
        import time
        stamp = time.strftime("%H:%M:%S")
        self.text.configure(state="normal")
        self.text.insert("end", f"[{stamp}] {message}\n")
        self.text.see("end")
        # Keep the log bounded.
        if int(self.text.index("end-1c").split(".")[0]) > 400:
            self.text.delete("1.0", "80.0")
        self.text.configure(state="disabled")


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame with an `inner` container."""

    def __init__(self, parent: tk.Misc, height: int = 220, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0,
                                background=COLORS["panel"], borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Panel.TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_inner_configure(self, _event: Any) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: Any) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event: Any) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()


class StationChecklist(ScrollFrame):
    """[x] PC 1  [x] PC 2 ... selection used by several tabs."""

    def __init__(self, parent: tk.Misc, on_change: Callable[[], None] | None = None,
                 height: int = 190, **kwargs: Any) -> None:
        super().__init__(parent, height=height, **kwargs)
        self.on_change = on_change
        self.selected: set[str] = set()
        self.vars: dict[str, tk.BooleanVar] = {}
        self._stations: list[dict[str, Any]] = []

    def set_stations(self, stations: Iterable[dict[str, Any]]) -> None:
        self._stations = list(stations)
        ids = {str(item.get("id")) for item in self._stations}
        self.selected.intersection_update(ids)
        self.clear()
        self.vars.clear()
        if not self._stations:
            ttk.Label(self.inner, text="No Station PCs discovered yet. Install/start the "
                      "LIKAcs Station Agent on each gaming PC.",
                      style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w", padx=8, pady=8)
            return
        for station in self._stations:
            station_id = str(station.get("id"))
            var = tk.BooleanVar(value=station_id in self.selected)
            self.vars[station_id] = var
            label = str(station.get("label") or station.get("hostname") or station_id)
            ip = str(station.get("ip") or "?")
            game_info = ", ".join(str(item.get("game", "")).upper()
                                 for item in (station.get("installs") or []) if item.get("exists"))
            text = f"{label}  ({ip})" + (f"  [{game_info}]" if game_info else "")
            ttk.Checkbutton(
                self.inner, text=text, variable=var, style="TCheckbutton",
                command=lambda sid=station_id, v=var: self._toggle(sid, v),
            ).pack(anchor="w", padx=8, pady=2)

    def _toggle(self, station_id: str, var: tk.BooleanVar) -> None:
        if var.get():
            self.selected.add(station_id)
        else:
            self.selected.discard(station_id)
        if self.on_change:
            self.on_change()

    def get_selected(self) -> list[str]:
        return sorted(self.selected)

    def set_selected(self, ids: Iterable[str]) -> None:
        self.selected = {str(item) for item in ids}
        for station_id, var in self.vars.items():
            var.set(station_id in self.selected)


def labeled_entry(parent: tk.Misc, label: str, variable: tk.Variable,
                  row: int, width: int = 22, column: int = 0) -> ttk.Entry:
    ttk.Label(parent, text=label, style="Panel.TLabel").grid(
        row=row, column=column, sticky="w", padx=(8, 6), pady=3)
    entry = ttk.Entry(parent, textvariable=variable, width=width)
    entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 10), pady=3)
    return entry


def status_bar_text(stations: int, rooms: int, error: str = "") -> str:
    base = f"{stations} Station PC(s) online   |   {rooms} active room(s)"
    if error:
        base += f"   |   last: {error[:90]}"
    return base


def website_line() -> str:
    return f"Official website: {WEBSITE_LABEL}  ->  {WEBSITE}"
