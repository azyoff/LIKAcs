import unittest

from likacs.agent import redact
from likacs.games import build_client_argv, build_server_argv


class GameLaunchTests(unittest.TestCase):
    INSTALL = {
        "game": "cs2", "client_exe": "C:/Steam/cs2.exe", "server_exe": "C:/Steam/cs2.exe",
        "cfg_dir": "C:/Steam/cfg", "root": "C:/Steam",
    }
    ROOM = {
        "game": "cs2", "map": "de_dust2", "port": 27015, "slots": 10,
        "rcon_password": "secret", "name": "Room 1", "server_mode": "listen",
    }

    def test_cs2_listen_server_is_official_and_vac_enabled(self) -> None:
        argv, workdir = build_server_argv(self.INSTALL, self.ROOM)
        self.assertEqual(argv[0], "C:/Steam/cs2.exe")
        self.assertEqual(workdir, "C:/Steam")
        for flag in ("-usercon", "+sv_lan", "1", "+rcon_password", "+map", "de_dust2",
                     "+maxplayers", "+exec", "lika_match.cfg", "-port", "27015"):
            self.assertIn(flag, argv)
        joined = " ".join(argv).lower()
        for forbidden in ("-insecure", ".dll", "pymem", "writeprocessmemory",
                          "-allow_no_steam_ticket"):
            self.assertNotIn(forbidden, joined)

    def test_cs16_listen_and_dedicated(self) -> None:
        install = {**self.INSTALL, "game": "cs16", "client_exe": "C:/HL/hl.exe",
                   "server_exe": "C:/HL/hlds.exe", "root": "C:/HL"}
        room = {**self.ROOM, "game": "cs16", "map": "fy_snow"}
        argv, _ = build_server_argv(install, room)
        self.assertIn("-game", argv)
        self.assertIn("cstrike", argv)
        self.assertIn("fy_snow", argv)
        dedicated, _ = build_server_argv(install, {**room, "server_mode": "dedicated"})
        self.assertEqual(dedicated[0], "C:/HL/hlds.exe")
        self.assertIn("+ip", dedicated)

    def test_client_launch_uses_official_connect_parameter(self) -> None:
        argv = build_client_argv({"client_exe": "C:/HL/hl.exe"}, "cs16", "192.168.1.5", 27016)
        self.assertEqual(argv[-2:], ["+connect", "192.168.1.5:27016"])

    def test_rcon_password_is_redacted(self) -> None:
        argv = ["cs2.exe", "+rcon_password", "supersecret", "+map", "de_dust2"]
        clean = redact(argv)
        self.assertNotIn("supersecret", clean)
        self.assertIn("********", clean)
        self.assertEqual(clean[-2:], ["+map", "de_dust2"])


if __name__ == "__main__":
    unittest.main()
