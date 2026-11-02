"""Windows runtime niceties: DPI awareness, single instance, friendly errors.

Everything here is stdlib-only and degrades gracefully on non-Windows hosts
and headless CI runners. Nothing touches game processes or game memory.
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import VERSION, WEBSITE
from .util import IS_WINDOWS, data_path

_MUTEX_HANDLES: list[Any] = []
_ERROR_HOOK_INSTALLED = False


def enable_dpi_awareness() -> bool:
    """Make the UI crisp on 4K / scaled Windows displays."""
    if not IS_WINDOWS:
        return False
    try:
        # Per-monitor v2 when available, then system-aware, then legacy.
        shcore = ctypes.windll.shcore
        if shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except Exception:
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except Exception:
        return False


def single_instance_guard(name: str = "LIKAcs-SingleInstance") -> bool:
    """Return False when another LIKAcs GUI is already running.

    Waits for nothing and never steals focus: the caller simply shows a
    friendly "already running" message and exits.
    """
    if not IS_WINDOWS:
        return True
    try:
        # Use plain ctypes types, NOT ctypes.wintypes: wintypes.HCURSOR is
        # missing on Python 3.11 and caused the v1 startup crash.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True  # could not create a mutex - do not block the app
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            return False
        _MUTEX_HANDLES.append(handle)  # keep it alive for process lifetime
        return True
    except Exception:
        return True


def log_path() -> Path:
    return data_path("logs") / "LIKAcs.log"


def _safe_print(message: str) -> None:
    """Never raise when sys.stdout is None (PyInstaller --windowed)."""
    try:
        print(message)
    except Exception:
        pass


def write_error_log(kind: str, details: str) -> str:
    """Append a timestamped error entry. Returns the log file path."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"\n===== {stamp} | LIKAcs v{VERSION} | {kind} =====\n{details}\n")
    except Exception:
        return ""
    return str(path)


def _friendly_message(exc: BaseException) -> str:
    """Convert a raw exception into something a cafe owner can act on."""
    name = type(exc).__name__
    text = str(exc).strip()
    if "Permission" in name or "denied" in text.lower():
        return ("LIKAcs could not write one of its files. "
                "Close any other LIKAcs window and try again.")
    if "TclError" in name:
        return "The Windows display subsystem returned an error while drawing the interface."
    if "URLError" in name or "HTTPError" in name or "Timeout" in name:
        return "LIKAcs could not reach GitHub. Check the internet connection and try again."
    if "SHA-256" in text or "mismatch" in text.lower():
        return "A downloaded file failed its integrity check. Nothing was changed."
    return "LIKAcs hit an unexpected problem. The details were saved to the log file."


def install_error_handlers() -> None:
    """Replace raw Python traceback dialogs with a friendly, logged dialog.

    PyInstaller --windowed builds pop up an "Unhandled exception in script"
    window with a raw traceback. Installing ``sys.excepthook`` and overriding
    ``Tk.report_callback_exception`` prevents that from ever reaching a user.
    """
    global _ERROR_HOOK_INSTALLED
    if _ERROR_HOOK_INSTALLED:
        return
    _ERROR_HOOK_INSTALLED = True

    def handler(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        path = write_error_log("unhandled", details)
        _safe_print(details)
        # A blocking Tk mainloop would hang headless CI runners; only the
        # installed windowed build gets the friendly modal dialog.
        if not (IS_WINDOWS and getattr(sys, "frozen", False)):
            return
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Tk()
            root.withdraw()
            root.title("LIKAcs - unexpected problem")
            dialog = tk.Toplevel(root)
            dialog.title("LIKAcs")
            dialog.resizable(False, False)
            dialog.geometry("520x260")
            try:
                dialog.iconbitmap(str(Path(sys.executable).with_name("lika.ico")))
            except Exception:
                pass
            frame = ttk.Frame(dialog, padding=18)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="LIKAcs hit an unexpected problem",
                      font=("Segoe UI", 12, "bold")).pack(anchor="w")
            ttk.Label(frame, text=_friendly_message(exc), wraplength=470,
                      justify="left").pack(anchor="w", pady=(10, 6))
            ttk.Label(frame, text=f"Version v{VERSION}  -  {WEBSITE}",
                      foreground="#64748b").pack(anchor="w", pady=(0, 12))
            if path:
                ttk.Label(frame, text=f"Details: {path}", wraplength=470,
                          justify="left", foreground="#64748b").pack(anchor="w")

            def copy_details() -> None:
                try:
                    dialog.clipboard_clear()
                    dialog.clipboard_append(details)
                except Exception:
                    pass

            bar = ttk.Frame(frame)
            bar.pack(fill="x", pady=(14, 0))
            ttk.Button(bar, text="Copy details", command=copy_details).pack(side="left")
            if path and IS_WINDOWS:
                ttk.Button(bar, text="Open log",
                           command=lambda: os.startfile(str(Path(path).parent))).pack(side="left", padx=6)
            ttk.Button(bar, text="Close", command=root.destroy).pack(side="right")
            dialog.transient(root)
            dialog.grab_set()
            root.mainloop()
        except Exception:
            pass  # headless runner: the log file is enough

    sys.excepthook = handler
    try:
        import tkinter as tk

        def tk_hook(self: Any, exc: Any, val: Any, tb: Any) -> None:
            details = "".join(traceback.format_exception(type(val), val, tb))
            path = write_error_log("tk callback", details)
            _safe_print(details)
            # Use the EXISTING root: creating a second Tk root and a nested
            # mainloop from inside a Tk callback is unsafe.
            try:
                from tkinter import messagebox
                message = _friendly_message(val)
                if path:
                    message += f"\n\nDetails: {path}"
                messagebox.showerror("LIKAcs", message, parent=self)
            except Exception:
                pass

        tk.Tk.report_callback_exception = tk_hook
    except (ImportError, Exception):
        pass
