"""Regression guards for Tk font/option strings (run on Linux, no tkinter needed).

Release v1.0.1 shipped ``root.option_add("*Font", "Segoe UI 10")``. Tk stores
that string in the option database and parses it only when the first widget is
created: family="Segoe", then it expects an integer size and reads "UI" ->
``TclError: expected integer but got "UI"``. A font family containing spaces
must be braced, or passed as a Python tuple (tkinter converts tuples into
braced Tcl lists), or set through ttk styles.

These tests read the source with ``ast`` so they run on headless Linux CI too.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "src" / "likacs" / "ui" / "theme.py"
UI_DIR = THEME.parent


class ThemeFontSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = ast.parse(THEME.read_text(encoding="utf-8"), filename=str(THEME))

    def _option_add_calls(self, tree: ast.Module) -> list[ast.Call]:
        return [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "option_add"
            and node.args
        ]

    def test_no_font_is_put_in_tk_option_database(self) -> None:
        """The *Font option entry was the exact v1.0.1 crash."""
        for call in self._option_add_calls(self.tree):
            pattern = call.args[0]
            if isinstance(pattern, ast.Constant) and isinstance(pattern.value, str):
                self.assertNotEqual(
                    pattern.value, "*Font",
                    "Do not set *Font via option_add: an unbraced multi-word family "
                    "is parsed as family + integer size and crashes on the first widget.",
                )

    def test_option_add_values_have_no_unbraced_spaces(self) -> None:
        for call in self._option_add_calls(self.tree):
            for value in call.args[1:]:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    text = value.value
                    self.assertFalse(
                        " " in text and not text.lstrip().startswith("{"),
                        f"option_add value {text!r} has an unbraced space",
                    )

    def test_every_ui_file_has_braced_or_tuple_fonts(self) -> None:
        """No plain string literals containing spaces may be used as fonts."""
        for path in sorted(UI_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                keywords = [kw for kw in node.keywords if kw.arg == "font"]
                for kw in keywords:
                    value = kw.value
                    if isinstance(value, ast.Tuple):
                        continue  # tkinter braces each element -> safe
                    if isinstance(value, ast.Name):
                        continue  # FONT_* constants are tuples
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        text = value.value
                        self.assertFalse(
                            " " in text and not text.lstrip().startswith("{"),
                            f"{path.name}: unbraced font string {text!r}",
                        )

    def test_font_constants_are_tuples(self) -> None:
        expected = {"FONT", "FONT_BOLD", "FONT_TITLE", "FONT_SMALL", "FONT_MONO"}
        found: set[str] = set()
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in expected:
                        found.add(target.id)
        self.assertEqual(found, expected)

    def test_apply_theme_sets_default_font_through_style(self) -> None:
        source = THEME.read_text(encoding="utf-8")
        self.assertIn('style.configure(".",', source)
        self.assertIn("font=FONT)", source)

    def test_no_segoe_ui_10_string_anywhere(self) -> None:
        """Literal that caused 'expected integer but got "UI"'.

        Checks real call arguments via AST, so documentation that merely
        *mentions* the old bad string does not produce a false positive.
        """
        for path in sorted(UI_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                values = list(node.args) + [kw.value for kw in node.keywords]
                for value in values:
                    if isinstance(value, ast.Constant) and value.value == "Segoe UI 10":
                        self.fail(f"{path.name}: unbraced font string 'Segoe UI 10'")

    def test_theme_module_documents_the_regression(self) -> None:
        source = THEME.read_text(encoding="utf-8")
        self.assertIn("v1.0.1", source)


if __name__ == "__main__":
    unittest.main()
