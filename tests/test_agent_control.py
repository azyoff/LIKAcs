"""End-to-end LAN test: a real signed HTTP API driving a real StationAgent."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from likacs import VERSION
from likacs.agent import StationAgent
from likacs.config import SettingsStore
from likacs.http_api import SignedClient
from likacs.protocol import (EP_CONFIGURE_JOIN, EP_STATUS, EP_WRITE_CONFIG,
                             EP_UPDATE_STATUS)
from tests import free_port, free_udp_port


class AgentIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "game" / "csgo" / "cfg"
        self.cfg.mkdir(parents=True)
        self.exe = self.root / "game" / "bin" / "win64" / "cs2.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"fake cs2")

        tcp, udp = free_port(), free_udp_port()
        self.store = SettingsStore(str(self.root / "settings.json"))
        self.store.update({
            "agent_port": tcp, "discovery_port": udp, "lan_key": "integration-key",
            "station_label": "PC 1",
            "game_paths": {
                "cs2": {
                    "root": str(self.root), "client_exe": str(self.exe),
                    "server_exe": str(self.exe), "cfg_dir": str(self.cfg),
                    "autoexec_name": "autoexec.cfg",
                }
            },
        })
        self.agent = StationAgent(self.store, logger=lambda _message: None)
        self.agent.http.start()
        self.port = int(self.agent.http.server_address[1])
        self.client = SignedClient("integration-key")

    def tearDown(self) -> None:
        self.agent.http.stop()
        self.tmp.cleanup()

    def test_status_reports_branding_and_detected_games(self) -> None:
        status = self.client.request("127.0.0.1", self.port, EP_STATUS, {})
        self.assertEqual(status["website"], "http://likaapps.com")
        self.assertEqual(status["version"], VERSION)
        self.assertEqual(status["label"], "PC 1")
        self.assertEqual(status["agent_port"], self.port)
        self.assertTrue(any(item["game"] == "cs2" and item["exists"]
                            for item in status["installs"]))
        self.assertIn("autostart", status)

    def test_configure_join_writes_live_cfg_files(self) -> None:
        result = self.client.request("127.0.0.1", self.port, EP_CONFIGURE_JOIN, {
            "all_games": True, "room_id": "room-1",
            "primary": {"host": "192.168.1.5", "port": 27015,
                        "room_name": "Room 1", "room_number": 1},
            "rooms": [
                {"host": "192.168.1.5", "port": 27015, "room_name": "Room 1", "room_number": 1},
                {"host": "192.168.1.9", "port": 27016, "room_name": "Room 2", "room_number": 2},
            ],
        })
        self.assertTrue(result["ok"], result)
        self.assertIn("connect 192.168.1.5:27015", (self.cfg / "lika_join.cfg").read_text())
        self.assertIn("connect 192.168.1.9:27016", (self.cfg / "lika_room2.cfg").read_text())
        self.assertIn("exec lika_autoexec.cfg", (self.cfg / "autoexec.cfg").read_text())
        self.assertEqual(self.agent.assignment["room_id"], "room-1")

        # Real-time retarget: only the tiny file changes, aliases stay put.
        autoexec_before = (self.cfg / "lika_autoexec.cfg").read_text()
        self.client.request("127.0.0.1", self.port, EP_CONFIGURE_JOIN, {
            "all_games": True, "room_id": "room-2",
            "primary": {"host": "192.168.1.9", "port": 27016, "room_name": "Room 2"},
            "rooms": [],
        })
        self.assertIn("connect 192.168.1.9:27016", (self.cfg / "lika_join.cfg").read_text())
        self.assertEqual((self.cfg / "lika_autoexec.cfg").read_text(), autoexec_before)

    def test_write_config_and_update_status(self) -> None:
        written = self.client.request("127.0.0.1", self.port, EP_WRITE_CONFIG, {
            "filename": "lika_match.cfg",
            "cvars": [["sv_lan", "1"], ["mp_autokick", "0"]],
            "commands": ["bot_kick"],
        })
        self.assertTrue(written["ok"])
        text = (self.cfg / "lika_match.cfg").read_text()
        self.assertIn("sv_lan 1", text)
        self.assertIn("bot_kick", text)
        status = self.client.request("127.0.0.1", self.port, EP_UPDATE_STATUS, {})
        self.assertEqual(status["version"], VERSION)

    def test_wrong_key_cannot_control_agent(self) -> None:
        from likacs.http_api import ApiError
        with self.assertRaises(ApiError):
            SignedClient("wrong").request("127.0.0.1", self.port, EP_STATUS, {})


if __name__ == "__main__":
    unittest.main()
