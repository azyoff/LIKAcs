"""Offline tests for DPI / single-instance / friendly-error runtime helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from likacs import runtime


class RuntimeTests(unittest.TestCase):
    def test_non_windows_hosts_degrade_gracefully(self) -> None:
        with mock.patch.object(runtime, "IS_WINDOWS", False):
            self.assertFalse(runtime.enable_dpi_awareness())
            self.assertTrue(runtime.single_instance_guard())

    def test_error_log_is_written_and_contains_the_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp, "XDG_CONFIG_HOME": tmp}):
                path = runtime.write_error_log("unhandled", "Traceback: test detail")
                self.assertTrue(path)
                self.assertTrue(Path(path).is_file())
                text = Path(path).read_text(encoding="utf-8")
                self.assertIn("test detail", text)
                self.assertIn("LIKAcs", text)

    def test_friendly_messages_are_actionable_not_tracebacks(self) -> None:
        self.assertIn("could not reach GitHub",
                      runtime._friendly_message(TimeoutError("timed out")))
        self.assertIn("log file",
                      runtime._friendly_message(RuntimeError("something odd")))
        self.assertNotIn("Traceback", runtime._friendly_message(ValueError("x")))

    def test_error_handler_installs_without_tk_on_headless_hosts(self) -> None:
        original = runtime._ERROR_HOOK_INSTALLED
        original_hook = __import__("sys").excepthook
        try:
            runtime._ERROR_HOOK_INSTALLED = False
            with mock.patch.object(runtime, "IS_WINDOWS", False):
                runtime.install_error_handlers()
            self.assertTrue(runtime._ERROR_HOOK_INSTALLED)
            self.assertIsNot(__import__("sys").excepthook, original_hook)
        finally:
            __import__("sys").excepthook = original_hook
            runtime._ERROR_HOOK_INSTALLED = original


if __name__ == "__main__":
    unittest.main()
