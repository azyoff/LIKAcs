import unittest

from likacs.branding import TRAY_PREFIX, fit_tray_tooltip
from likacs.icon import ico_bytes


class TrayTests(unittest.TestCase):
    def test_tooltip_respects_windows_127_char_limit(self) -> None:
        statuses = [f"Room {index}: 5vs5 playing" for index in range(1, 60)]
        tooltip = fit_tray_tooltip(statuses, 127)
        self.assertLessEqual(len(tooltip), 127)
        self.assertTrue(tooltip.startswith(TRAY_PREFIX))
        self.assertIn("more", tooltip)
        self.assertIn("click for full status", tooltip)

    def test_tooltip_idle_and_small_number_of_rooms(self) -> None:
        self.assertIn("idle", fit_tray_tooltip([]))
        short = fit_tray_tooltip(["Room 1: 2vs2 playing", "Room 2: 1vs1 playing"])
        self.assertLessEqual(len(short), 127)
        self.assertIn("Room 1", short)
        self.assertIn("Room 2", short)
        self.assertIn("likaapps.com", short)

    def test_generated_icon_is_a_valid_ico(self) -> None:
        data = ico_bytes()
        self.assertEqual(data[:6], b"\x00\x00\x01\x00\x01\x00")
        self.assertGreater(len(data), 4000)

    def test_windows_ctypes_tray_block_imports_cleanly(self) -> None:
        """Regression for the v1 crash: wintypes.HCURSOR does not exist.

        Simulates Windows on a non-Windows runner by injecting a fake
        ctypes.windll + WINFUNCTYPE, then reloading likacs.tray. Any missing
        wintypes attribute in the Windows-only block raises here, rather than
        only on a real Windows machine.
        """
        import ctypes
        import importlib
        import types

        import likacs.tray as tray
        import likacs.util as util

        class _FakeFunction:
            """Absorbs .argtypes / .restype assignments at import time."""

        class _FakeDll:
            def __getattr__(self, name):
                function = _FakeFunction()
                setattr(self, name, function)
                return function

        had_windll = hasattr(ctypes, "windll")
        old_windll = getattr(ctypes, "windll", None)
        had_winfunctype = hasattr(ctypes, "WINFUNCTYPE")
        old_winfunctype = getattr(ctypes, "WINFUNCTYPE", None)
        old_is_windows = util.IS_WINDOWS
        try:
            ctypes.windll = types.SimpleNamespace(
                user32=_FakeDll(), kernel32=_FakeDll(), shell32=_FakeDll())
            ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
            util.IS_WINDOWS = True
            module = importlib.reload(tray)
            self.assertIsNot(module.WindowsTray, module.NullTray)
            self.assertTrue(hasattr(module, "WNDCLASSW"))
            self.assertTrue(hasattr(module, "NOTIFYICONDATAW"))
            self.assertGreater(ctypes.sizeof(module.NOTIFYICONDATAW), 500)
            self.assertTrue(callable(module.create_tray))
        finally:
            util.IS_WINDOWS = old_is_windows
            if had_windll:
                ctypes.windll = old_windll
            else:
                delattr(ctypes, "windll")
            if had_winfunctype:
                ctypes.WINFUNCTYPE = old_winfunctype
            else:
                delattr(ctypes, "WINFUNCTYPE")
            importlib.reload(tray)


if __name__ == "__main__":
    unittest.main()
