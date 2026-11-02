import tempfile
import unittest
from pathlib import Path

from likacs.cfgs import (CfgManager, HOOK_LINE, LIKA_AUTOEXEC, LIKA_JOIN,
                         JoinTarget, install_autoexec_hook, render_lika_autoexec,
                         render_join_cfg)


class CfgManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_dir = Path(self.tmp.name) / "cfg"
        self.cfg_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hook_is_idempotent_and_preserves_player_settings(self) -> None:
        autoexec = self.cfg_dir / "autoexec.cfg"
        player_settings = (
            'bind "MOUSE1" "+attack"\r\n'
            'sensitivity "2.35"\r\n'
            'crosshair "1"\r\n'
            'bind "F10" "quit prompt"\r\n'
        )
        autoexec.write_text(player_settings)
        first = install_autoexec_hook(self.cfg_dir, "autoexec.cfg")
        self.assertTrue(first["backup"], "first edit must create a backup")
        for _ in range(3):
            install_autoexec_hook(self.cfg_dir, "autoexec.cfg")
        text = autoexec.read_text()
        self.assertEqual(text.count(HOOK_LINE), 1)
        for line in ('bind "MOUSE1" "+attack"', 'sensitivity "2.35"', 'crosshair "1"'):
            self.assertIn(line, text)
        self.assertIn("LIKAcs (likaapps.com) managed block - START", text)
        self.assertIn("LIKAcs (likaapps.com) managed block - END", text)

    def test_hook_created_when_autoexec_missing(self) -> None:
        result = install_autoexec_hook(self.cfg_dir, "userconfig.cfg")
        self.assertTrue(result["created"])
        self.assertIn(HOOK_LINE, (self.cfg_dir / "userconfig.cfg").read_text())

    def test_autoexec_aliases_and_f10_override(self) -> None:
        text = render_lika_autoexec("joinnow", "F10", True, "cs16")
        self.assertIn('alias "lika" "exec lika_join.cfg"', text)
        self.assertIn('alias "joinnow" "exec lika_join.cfg"', text)
        for index in (1, 2, 3):
            self.assertIn(f'alias "lika{index}" "exec lika_room{index}.cfg"', text)
        self.assertIn('unbind "F10"', text)
        self.assertIn('bind "F10" "lika"', text)
        self.assertIn("console 1", text)
        self.assertNotIn('bind "F10" "quit prompt"', text)

    def test_f10_can_be_disabled_and_custom_key_used(self) -> None:
        text = render_lika_autoexec("lika", "F9", True, "cs2")
        self.assertIn('bind "F9" "lika"', text)
        self.assertIn("con_enable 1", text)
        text_off = render_lika_autoexec("lika", "F10", False, "cs2")
        self.assertNotIn('bind "F10"', text_off)

    def test_realtime_join_retarget(self) -> None:
        manager = CfgManager(self.cfg_dir, "cs2")
        manager.install("lika", "F10", True)
        autoexec_snapshot = (self.cfg_dir / LIKA_AUTOEXEC).read_text()
        manager.set_target(JoinTarget("192.168.1.5", 27016, room_name="Room 2"))
        self.assertIn("connect 192.168.1.5:27016", (self.cfg_dir / LIKA_JOIN).read_text())
        manager.set_target(JoinTarget("192.168.1.10", 27015, room_name="Room 1"))
        self.assertIn("connect 192.168.1.10:27015", (self.cfg_dir / LIKA_JOIN).read_text())
        self.assertEqual((self.cfg_dir / LIKA_AUTOEXEC).read_text(), autoexec_snapshot,
                         "aliases must not change; only the tiny exec target is rewritten")

    def test_room_alias_files_and_unassigned_state(self) -> None:
        manager = CfgManager(self.cfg_dir, "cs16")
        manager.install("lika", "F10", True)
        targets = [
            JoinTarget("10.0.0.1", 27015, room_name="Room 1", room_number=1),
            JoinTarget("10.0.0.5", 27016, room_name="Room 2", room_number=2),
        ]
        manager.set_room_targets(targets)
        self.assertIn("connect 10.0.0.1:27015", (self.cfg_dir / "lika_room1.cfg").read_text())
        self.assertIn("connect 10.0.0.5:27016", (self.cfg_dir / "lika_room2.cfg").read_text())
        self.assertIn("no room assigned", (self.cfg_dir / "lika_room3.cfg").read_text())
        self.assertIn("no room assigned", render_join_cfg(None))
        self.assertIn('password "abc"', render_join_cfg(JoinTarget("1.2.3.4", 27015, password="abc")))

    def test_match_cfg_contains_official_cvars(self) -> None:
        manager = CfgManager(self.cfg_dir, "cs2")
        manager.write_match([("sv_lan", "1"), ("mp_autokick", "0")], ["bot_kick"])
        text = (self.cfg_dir / "lika_match.cfg").read_text()
        self.assertIn("sv_lan 1", text)
        self.assertIn("mp_autokick 0", text)
        self.assertIn("bot_kick", text)
        self.assertIn("mp_warmup_end", text)
        self.assertIn("likaapps.com", text)


if __name__ == "__main__":
    unittest.main()
