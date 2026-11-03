"""Headless guards for the v1.2.0 sidebar workspace + dashboard.

These run on Linux without tkinter: they parse the source with ``ast`` so a
missing ttk style, a broken Notebook shim or a lost Dashboard page fails CI
before a Windows build is published.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "likacs" / "ui"
THEME = UI / "theme.py"
NAV = UI / "navigation.py"
CONTROL = UI / "control_center.py"

BUILTIN_STYLES = {
    "TFrame", "TLabel", "TButton", "TLabelframe", "TNotebook", "Treeview",
    "TCheckbutton", "TEntry", "TCombobox", "TProgressbar", "TSeparator",
    "Horizontal.TProgressbar", "Vertical.TScrollbar",
}


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


class DashboardShellTests(unittest.TestCase):
    def test_every_style_used_in_the_ui_is_configured(self) -> None:
        used: set[str] = set()
        for path in UI.glob("*.py"):
            for call in _calls(ast.parse(path.read_text(encoding="utf-8"))):
                for keyword in call.keywords:
                    value = keyword.value
                    if (keyword.arg == "style" and isinstance(value, ast.Constant)
                            and isinstance(value.value, str)):
                        used.add(value.value)
        configured: set[str] = set()
        for call in _calls(ast.parse(THEME.read_text(encoding="utf-8"))):
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr == "configure" and call.args):
                first = call.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    configured.add(first.value)
        self.assertEqual(set(), used - configured - BUILTIN_STYLES,
                         "a widget uses a ttk style that apply_theme never defines")

    def test_sidebar_book_exposes_the_notebook_api(self) -> None:
        tree = ast.parse(NAV.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertIn("SidebarBook", classes)
        methods = {node.name for node in classes["SidebarBook"].body
                   if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"add", "select", "set_badge"}.issubset(methods))
        bases = " ".join(ast.unparse(base) for base in classes["SidebarBook"].bases)
        self.assertIn("ttk.Frame", bases)

    def test_control_center_uses_the_sidebar_and_a_dashboard_first(self) -> None:
        source = CONTROL.read_text(encoding="utf-8")
        self.assertIn("from .navigation import SidebarBook", source)
        self.assertIn("self.notebook = SidebarBook(", source)
        self.assertNotIn("ttk.Notebook(self.root)", source)
        self.assertIn("def _tab_dashboard(self)", source)
        self.assertIn("def _refresh_dashboard(self", source)
        self.assertIn("self._refresh_dashboard(stations, rooms)", source)
        # Dashboard is registered before the Rooms page, so it is the default.
        self.assertLess(source.index("self._tab_dashboard()"),
                        source.index("self._tab_rooms()"))

    def test_dashboard_has_guided_setup_kpis_rooms_and_stations(self) -> None:
        source = CONTROL.read_text(encoding="utf-8")
        for token in ("Cafe overview", "Quick start", "Live rooms",
                      "Station PCs", "Recent activity", "self.kpi_vars",
                      "self.quick_steps", "self.pc_tiles", "self.room_cards"):
            self.assertIn(token, source, f"dashboard is missing {token}")

    def test_no_unbraced_string_font_in_the_new_files(self) -> None:
        """The v1.0.1 crash came from a raw 'Segoe UI 10' font string."""
        for path in (NAV, CONTROL, THEME):
            for call in _calls(ast.parse(path.read_text(encoding="utf-8"))):
                for keyword in call.keywords:
                    value = keyword.value
                    if (keyword.arg == "font" and isinstance(value, ast.Constant)
                            and isinstance(value.value, str)):
                        self.assertNotIn(" ", value.value.strip(),
                                         f"{path.name}: unbraced font family in Tk string")

    def test_preview_image_is_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("preview-v1.2.0.png", readme)
        self.assertTrue((ROOT / "preview-v1.2.0.png").is_file())


if __name__ == "__main__":
    unittest.main()
