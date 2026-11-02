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


if __name__ == "__main__":
    unittest.main()
