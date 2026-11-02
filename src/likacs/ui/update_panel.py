"""Reusable 'Update LIKAcs' panel: one button does everything.

Shared by the Control Center and the Station Agent so every PC in the cafe can
be updated with a single click, straight from GitHub Releases.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import VERSION
from ..selfupdate import SelfUpdater
from ..util import open_url
from .theme import COLORS, FONT, FONT_BOLD, FONT_SMALL

AsyncRunner = Callable[[Callable[[], Any], Callable[[Any], None], str], None]


class UpdateBar(ttk.Frame):
    """Compact one-click update bar for the small Station Agent window."""

    def __init__(self, parent: tk.Misc, *, on_restart: Callable[[], None],
                 log: Callable[[str], None] | None = None, auto_check: bool = True,
                 updater: SelfUpdater | None = None) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self.on_restart = on_restart
        self.log = log or (lambda _message: None)
        self.updater = updater or SelfUpdater()
        self.status = tk.StringVar(value=f"v{VERSION} installed - updates come from GitHub")
        self.button_text = tk.StringVar(value="Update LIKAcs")
        ttk.Label(self, text="Stay up to date:", font=FONT_BOLD,
                  style="Panel.TLabel").pack(side="left", padx=(8, 6), pady=8)
        ttk.Label(self, textvariable=self.status, font=FONT_SMALL,
                  style="Panel.TLabel", width=44).pack(side="left", padx=4)
        self.button = ttk.Button(self, textvariable=self.button_text,
                                 style="Primary.TButton", command=self.one_click)
        self.button.pack(side="left", padx=8, pady=6)
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100, length=130)
        self.progress.pack(side="right", padx=8)
        if auto_check:
            self.after(1500, self.check_silently)

    def _progress(self, label: str, done: int, total: int, extra: str = "") -> None:
        def update() -> None:
            if total:
                self.progress["value"] = min(100, int(done * 100 / total))
            self.status.set(f"{label}: {done // 1024}/{total // 1024 if total else 0} KiB")
        self.after(0, update)

    def check_silently(self) -> None:
        def worker() -> None:
            try:
                result = self.updater.check()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.after(0, lambda: self._check_done(result))

        threading.Thread(target=worker, name="likacs-update-check", daemon=True).start()

    def _check_done(self, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            self.status.set(f"v{VERSION} installed - GitHub unavailable (offline)")
            return
        latest = result.get("latest", "?")
        if result.get("update_available"):
            self.status.set(f"v{latest} available - one click to install")
            self.button_text.set(f"Update to {latest}")
        else:
            self.status.set(f"v{VERSION} installed - already up to date")

    def one_click(self) -> None:
        self.button.configure(state="disabled")
        self.button_text.set("Working...")

        def worker() -> None:
            try:
                result = self.updater.one_click_update(self._progress)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.after(0, lambda: self._done(result))

        threading.Thread(target=worker, name="likacs-self-update", daemon=True).start()

    def _done(self, result: dict[str, Any]) -> None:
        self.button.configure(state="normal")
        if not result.get("ok"):
            self.button_text.set("Update LIKAcs")
            self.status.set("Nothing changed - " + str(result.get("error") or "try again"))
            self.log(f"Update failed: {result.get('error')}")
            messagebox.showerror("LIKAcs update", f"Update failed:\n{result.get('error')}")
            return
        if result.get("up_to_date"):
            self.button_text.set("Update LIKAcs")
            self.status.set(f"v{VERSION} installed - already up to date")
            return
        self.status.set(f"v{result.get('version')} verified - restarting automatically...")
        # No extra dialog: clicking Update once is the whole flow.
        self.after(1200, self.on_restart)


class UpdatePanel(ttk.Frame):
    """Status, one-click update, progress and optional LAN push controls."""

    def __init__(self, parent: tk.Misc, *, run_async: AsyncRunner,
                 on_restart: Callable[[], None], log: Callable[[str], None] | None = None,
                 on_push: Callable[[Callable[..., None], bool], dict[str, Any]] | None = None,
                 auto_check: bool = True, updater: SelfUpdater | None = None) -> None:
        super().__init__(parent, padding=4)
        self.run_async = run_async
        self.on_restart = on_restart
        self.log = log or (lambda _message: None)
        self.on_push = on_push
        self.updater = updater or SelfUpdater()
        self.latest: dict[str, Any] = {}
        self.update_asset_path = ""

        self.current_var = tk.StringVar(value=f"Installed: v{VERSION}")
        self.latest_var = tk.StringVar(value="Latest on GitHub: not checked yet")
        self.button_text = tk.StringVar(value="Check & Update")
        self.hint_var = tk.StringVar(
            value="One click: check GitHub, verify the download, install and restart.")

        head = ttk.LabelFrame(self, text=" Keep LIKAcs up to date ",
                              style="Card.TLabelframe")
        head.pack(fill="x", padx=4, pady=(4, 8))
        ttk.Label(head, textvariable=self.current_var, font=FONT_BOLD,
                  style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        ttk.Label(head, textvariable=self.latest_var, font=FONT,
                  style="Panel.TLabel").grid(row=0, column=1, sticky="w", padx=12, pady=(10, 4))
        ttk.Label(head, textvariable=self.hint_var, font=FONT_SMALL,
                  foreground=COLORS["muted"], style="Panel.TLabel").grid(
                      row=1, column=0, columnspan=3, sticky="w", padx=12)

        self.update_button = ttk.Button(head, textvariable=self.button_text,
                                        style="Primary.TButton",
                                        command=self.one_click, width=22)
        self.update_button.grid(row=2, column=0, padx=12, pady=12, sticky="w")
        ttk.Button(head, text="View releases on GitHub",
                   command=lambda: open_url("https://github.com/azyoff/LIKAcs/releases/latest")).grid(
                       row=2, column=1, padx=6, pady=12, sticky="w")
        self.progress = ttk.Progressbar(head, mode="determinate", maximum=100, length=320)
        self.progress.grid(row=2, column=2, padx=12, pady=12, sticky="ew")
        head.columnconfigure(2, weight=1)

        notes = ttk.LabelFrame(self, text=" Release notes ", style="Card.TLabelframe")
        notes.pack(fill="both", expand=True, padx=4, pady=4)
        self.notes = tk.Text(notes, wrap="word", height=9, state="disabled",
                             background=COLORS["panel2"], foreground=COLORS["fg"],
                             relief="flat", font=FONT)
        self.notes.pack(fill="both", expand=True, padx=8, pady=8)

        if self.on_push:
            advanced = ttk.LabelFrame(self, text=" Cafe-wide rollout (optional) ",
                                      style="Card.TLabelframe")
            advanced.pack(fill="x", padx=4, pady=8)
            self.restart_agents = tk.BooleanVar(value=False)
            ttk.Checkbutton(advanced, text="Restart Station Agents after pushing",
                            variable=self.restart_agents).pack(anchor="w", padx=12, pady=(8, 2))
            ttk.Label(advanced, text=(
                "Push the newest verified LIKAcs.exe to every connected gaming PC over the LAN."),
                font=FONT_SMALL, foreground=COLORS["muted"], style="Panel.TLabel").pack(
                    anchor="w", padx=12)
            self.push_button = ttk.Button(advanced, text="Push update to ALL Station PCs",
                                          command=self.push)
            self.push_button.pack(anchor="w", padx=12, pady=10)

        if auto_check:
            self.after(1200, self.check_silently)

    # ------------------------------------------------------------------ helpers
    def _set_notes(self, text: str) -> None:
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text or "(no release notes)")
        self.notes.configure(state="disabled")

    def _progress(self, label: str, done: int, total: int, extra: str = "") -> None:
        def update() -> None:
            if total:
                self.progress["value"] = min(100, int(done * 100 / total))
            self.hint_var.set(f"{label}: {done}/{total} bytes {extra}".strip())
        self.after(0, update)

    # ------------------------------------------------------------------- checks
    def check_silently(self) -> None:
        """Background startup check: no popups, just a status line."""
        def done(result: Any) -> None:
            if not isinstance(result, dict) or not result.get("ok"):
                self.latest_var.set("Latest on GitHub: unavailable (offline)")
                return
            self.latest = result
            latest = result.get("latest", "?")
            available = bool(result.get("update_available"))
            self.latest_var.set(f"Latest on GitHub: {latest}" +
                                ("  -  UPDATE AVAILABLE" if available else "  -  up to date"))
            info = result.get("info")
            notes = getattr(info, "notes", "") if info else ""
            self._set_notes(f"v{latest}\n\n{notes}")
            if available:
                self.button_text.set(f"Update to {latest}")
                self.hint_var.set("One click installs the verified release and restarts LIKAcs.")
            else:
                self.button_text.set("Check again")
        try:
            self.run_async(self.updater.check, done, "Checking GitHub Releases...")
        except Exception:
            pass

    # --------------------------------------------------------------- one click
    def one_click(self) -> None:
        """Check + download + verify + stage + restart, in ONE click."""
        self.update_button.configure(state="disabled")
        self.button_text.set("Working...")
        self.hint_var.set("Checking GitHub for a newer version...")

        def done(result: Any) -> None:
            self.update_button.configure(state="normal")
            if not isinstance(result, dict):
                self._fail("unexpected result")
                return
            if not result.get("ok"):
                self._fail(str(result.get("error") or "update failed"))
                return
            if result.get("up_to_date"):
                self.button_text.set("Check again")
                self.latest_var.set(f"Latest on GitHub: {result.get('latest')}  -  up to date")
                self.hint_var.set(f"You are already on the latest version (v{VERSION}).")
                self.log(f"Update check: already up to date (v{VERSION})")
                return
            self.latest_var.set(f"Installing {result.get('version')}...")
            self.hint_var.set("Verified. LIKAcs will restart now to finish the update.")
            self._set_notes(f"v{result.get('version')}\n\n{result.get('notes') or ''}")
            self.log(f"Update {result.get('version')} staged (sha256 {str(result.get('sha256'))[:12]}...)")
            # No confirmation dialog: ONE click checks, verifies and installs.
            self.after(1200, self.on_restart)

        self.run_async(lambda: self.updater.one_click_update(
            self._progress), done, "Checking & downloading update...")

    def _fail(self, message: str) -> None:
        self.button_text.set("Check & Update")
        self.hint_var.set("Nothing was changed. You can try again.")
        self.log(f"Update failed: {message}")
        messagebox.showerror("LIKAcs update", f"Update failed:\n{message}")

    # ---------------------------------------------------------------- LAN push
    def push(self) -> None:
        """Advanced cafe-wide rollout: download once, verify, push over the LAN."""
        if not self.on_push:
            return
        if not messagebox.askyesno(
                "LIKAcs", "Download the verified latest release and push it to "
                          "every online Station PC?"):
            return
        restart = bool(getattr(self, "restart_agents", None) and
                       self.restart_agents.get())
        self.push_button.configure(state="disabled")

        def done(result: Any) -> None:
            self.push_button.configure(state="normal")
            items = (result or {}).get("results") or []
            ok = sum(1 for item in items if item.get("ok"))
            self.log(f"Update push: {ok}/{len(items)} Station PC(s)")
            messagebox.showinfo("LIKAcs",
                                f"Pushed the verified update to {ok}/{len(items)} PC(s).")
        self.run_async(lambda: self.on_push(self._progress, restart), done,
                       "Pushing verified update to all Station PCs...")
