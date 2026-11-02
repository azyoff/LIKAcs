import unittest

from likacs.rules import (COMMAND_SETS, MAPS_CS16, MAPS_CS2, PRESETS,
                          build_match_cvars, change_map_commands, commands_for,
                          maps_for, normalize_map, preset_slots)


class RuleTests(unittest.TestCase):
    def test_default_cafe_rules(self) -> None:
        cvars = dict(build_match_cvars({}, "cs2", "5vs5", 10, True))
        for key, value in {
            "sv_lan": "1", "mp_freezetime": "3", "mp_friendlyfire": "1",
            "mp_autokick": "0", "mp_autoteambalance": "0", "mp_limitteams": "0",
            "mp_forcecamera": "1", "bot_quota": "0",
        }.items():
            self.assertEqual(cvars.get(key), value, key)
        self.assertEqual(cvars["maxplayers"], "10")
        self.assertEqual(cvars["mp_overtime_enable"], "1")

    def test_uneven_teams_and_custom_rules(self) -> None:
        cvars = dict(build_match_cvars({"mp_freezetime": "7"}, "cs2", "2vs3", 5, False))
        self.assertEqual(cvars["mp_freezetime"], "7")
        self.assertEqual(cvars["maxplayers"], "5")
        self.assertEqual(cvars["mp_limitteams"], "0")
        self.assertEqual(cvars["mp_overtime_enable"], "0")
        self.assertEqual(preset_slots("2vs3"), 5)

    def test_cs16_translation(self) -> None:
        cvars = dict(build_match_cvars({}, "cs16", "5vs5", 10, True))
        self.assertEqual(cvars.get("mp_forcechasecam"), "2")
        self.assertEqual(cvars.get("mp_tkpunish"), "0")
        self.assertEqual(cvars.get("pausable"), "1")
        self.assertIn("mp_overtime", cvars)

    def test_wingman_and_deathmatch(self) -> None:
        wingman = dict(build_match_cvars({}, "cs2", "wingman", 4, True))
        self.assertEqual(wingman["game_mode"], "2")
        deathmatch = dict(build_match_cvars({}, "cs2", "deathmatch", 20, False))
        self.assertEqual(deathmatch["mp_teammates_are_enemies"], "1")
        self.assertEqual(deathmatch["mp_respawn_on_death_ct"], "1")
        self.assertEqual(deathmatch["maxplayers"], "20")

    def test_maps_and_custom_map_sanitising(self) -> None:
        self.assertEqual(MAPS_CS2[0], "de_dust2")
        self.assertIn("fy_snow", maps_for("cs2"))
        self.assertIn("aim_map", maps_for("cs16"))
        self.assertEqual(normalize_map("de_mirage"), "de_mirage")
        self.assertEqual(normalize_map("../evil; map"), "evilmap")
        self.assertEqual(normalize_map(""), "de_dust2")
        self.assertEqual(set(PRESETS), {"1vs1", "2vs2", "2vs3", "3vs3", "4vs4",
                                        "5vs5", "wingman", "deathmatch", "custom"})

    def test_live_command_sets(self) -> None:
        for action in COMMAND_SETS:
            for game in ("cs2", "cs16"):
                commands = commands_for(action, game)
                self.assertTrue(commands, f"{action}/{game} has no commands")
                self.assertTrue(all(isinstance(item, str) and item.strip() for item in commands))
        self.assertEqual(change_map_commands("cs2", "de_nuke"), ["changelevel de_nuke"])
        self.assertIn("mp_warmup_end", commands_for("end_warmup", "cs2"))
        self.assertIn("sv_restart 1", commands_for("end_warmup", "cs16"))


if __name__ == "__main__":
    unittest.main()
