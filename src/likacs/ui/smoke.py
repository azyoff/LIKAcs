"""Construct every LIKAcs window against a real Tk interpreter.

Importing the GUI modules is NOT enough. Tk parses option-database font
strings only when the first widget is actually created. Release v1.0.1 shipped
``option add *Font "Segoe UI 10"`` (unbraced family name), which crashed all
three exes on the very first ``ttk.Label`` while every import-only CI check
stayed green.

This module builds the mode chooser, the About dialog, the full Control Center
and the full Station Agent against a hidden Tk root, forces Tk to lay them out,
and tears everything down. It is used by ``--smoke-gui``, by
``scripts/smoke_gui.py`` and by ``--self-test`` whenever Tk is available.
No network services, tray icon or ``mainloop`` are started.

All failures are caught and reported as a non-zero return code: PyInstaller's
--windowed builds show a blocking modal dialog on an unhandled exception,
which would hang a CI runner instead of failing the check.
"""

from __future__ import annotations

import os
import tempfile
import traceback


def _clear(root: object) -> None:
    """Destroy all children of a root window and hide it again."""
    for child in list(root.winfo_children()):  # type: ignore[attr-defined]
        try:
            child.destroy()
        except Exception:
            pass
    root.withdraw()  # type: ignore[attr-defined]


def run_gui_smoke() -> int:
    """Build every window. Returns 0 on success, 1 on any Tk error."""
    try:
        return _build_all_windows()
    except Exception as exc:  # never let a --windowed exe show a modal dialog
        print(f"GUI SMOKE FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


def _build_all_windows() -> int:
    import sys

    try:
        import tkinter as tk
    except ModuleNotFoundError:
        # Headless Linux CI / dev boxes have no Tk. The AST-based tests in
        # tests/test_theme.py still guard the font bug there; the real render
        # runs on windows-latest (and inside the frozen exe, which bundles Tk).
        # On Windows a missing tkinter is a genuine build failure.
        if sys.platform != "win32":
            print("GUI SMOKE SKIPPED: tkinter not installed on this non-Windows runner")
            return 0
        raise

    from .theme import apply_theme
    from .about import show_about
    from .mode_chooser import choose_mode

    saved = {key: os.environ.get(key) for key in ("APPDATA", "XDG_CONFIG_HOME")}
    with tempfile.TemporaryDirectory(prefix="likacs-gui-smoke-") as tmp:
        # Keep settings.json / station identity out of the real user profile.
        os.environ["APPDATA"] = tmp
        os.environ["XDG_CONFIG_HOME"] = tmp
        try:
            try:
                root = tk.Tk()
            except tk.TclError as exc:
                if "display" in str(exc).lower() or "connect" in str(exc).lower():
                    print("GUI SMOKE SKIPPED: no Tk display available on this runner")
                    return 0
                raise
            root.withdraw()
            try:
                apply_theme(root)
                built: list[str] = []

                def stage(name: str, builder: object) -> None:
                    builder()  # type: ignore[operator]
                    root.update_idletasks()
                    root.withdraw()
                    built.append(name)

                # 1. Unified exe first-run chooser (the exact v1.0.1 crash site).
                stage("mode chooser", lambda: choose_mode(root, lambda: None, lambda: None))
                _clear(root)

                # 2. About dialog (Toplevel + tk.Text + ttk buttons).
                stage("about dialog", lambda: show_about(root))
                _clear(root)

                # 3. Full Control Center: notebook, five tabs, Treeview,
                #    Combobox, Progressbar, ScrollFrame, LogPanel...
                from ..control import ControlCenter
                from .control_center import ControlCenterApp

                stage("control center",
                      lambda: ControlCenterApp(control=ControlCenter(), root=root, smoke=True))
                _clear(root)

                # 4. Full Station Agent window.
                from ..agent import StationAgent
                from .station_agent import StationAgentApp

                stage("station agent",
                      lambda: StationAgentApp(agent=StationAgent(), root=root, smoke=True))
                _clear(root)

                print("GUI SMOKE OK: " + ", ".join(built))
                return 0
            finally:
                root.destroy()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
