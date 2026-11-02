"""Control Center orchestration over a real signed LAN API (no GUI, no Steam)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from likacs.agent import StationAgent
from likacs.config import SettingsStore
from likacs.control import ControlCenter
from likacs.http_api import ApiError, SignedClient
from likacs.protocol import MSG_HELLO
from likacs.state import RoomManager
from tests import free_port, free_udp_port


class ControlIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "game" / "csgo" / "cfg"
        self.cfg.mkdir(parents=True)
        self.exe = self.root / "game" / "bin" / "win64" / "cs2.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"fake cs2")
        tcp, udp = free_port(), free_udp_port()
        self.store = SettingsStore(str(self.root / "station-settings.json"))
        self.store.update({
            "agent_port": tcp, "discovery_port": udp, "lan_key": "orch-key",
            "station_label": "PC 1",
            "game_paths": {"cs2": {
                "root": str(self.root), "client_exe": str(self.exe),
                "server_exe": str(self.exe), "cfg_dir": str(self.cfg),
                "autoexec_name": "autoexec.cfg",
            }},
        })
        self.agent = StationAgent(self.store, logger=lambda _m: None)
        self.agent.http.start()
        self.port = int(self.agent.http.server_address[1])

        laptop = SettingsStore(str(self.root / "laptop-settings.json"))
        laptop.update({"agent_port": tcp, "discovery_port": udp, "lan_key": "orch-key"})
        self.control = ControlCenter(laptop, logger=lambda _m: None)
        self.control.rooms = RoomManager(str(self.root / "rooms.json"),
                                         settings=self.control.settings)
        self.control.on_message({
            "kind": MSG_HELLO, "id": self.agent.station_id, "label": "PC 1",
            "ip": "127.0.0.1", "agent_port": self.port, "version": "1.0.0",
            "installs": [], "servers": [], "ips": ["127.0.0.1"],
        }, ("127.0.0.1", udp))

    def tearDown(self) -> None:
        self.agent.http.stop()
        self.tmp.cleanup()

    def test_room_creation_assignment_and_live_routing(self) -> None:
        self.assertEqual(len(self.control.online_stations()), 1)
        room = self.control.create_room(
            game="cs2", preset="2vs2", map="de_mirage",
            host_station_id=self.agent.station_id,
            station_ids=[self.agent.station_id],
        )
        self.assertEqual(room.slots, 4)
        self.assertEqual(room.port, 27015)
        self.assertTrue(room.rcon_password)
        # Idle room -> no stale connect target.
        self.assertIn("no room assigned", (self.cfg / "lika_join.cfg").read_text())

        self.control.rooms.update(room.id, {"state": "live", "host_ip": "127.0.0.1"})
        self.control.refresh_join_configs()
        join = (self.cfg / "lika_join.cfg").read_text()
        self.assertIn("connect 127.0.0.1:27015", join)
        self.assertIn("connect 127.0.0.1:27015", (self.cfg / "lika_room1.cfg").read_text())
        self.assertEqual(self.control.rooms.room_for_station(self.agent.station_id).id, room.id)

        cvars = dict(self.control.cvars_for_room(self.control.rooms.get(room.id)))
        self.assertEqual(cvars["sv_lan"], "1")
        self.assertEqual(cvars["maxplayers"], "4")
        self.assertIn("Room 1", self.control.tray_tooltip())
        self.assertTrue(any(item.get("id") == "website"
                            for item in self.control.tray_menu_items()))

    def test_two_rooms_have_distinct_ports_and_hosts(self) -> None:
        first = self.control.create_room(preset="2vs2", host_station_id=self.agent.station_id)
        second = self.control.create_room(preset="1vs1", host_station_id=self.agent.station_id)
        self.assertEqual(first.name, "Room 1")
        self.assertEqual(second.name, "Room 2")
        self.assertEqual((first.port, second.port), (27015, 27016))
        self.control.assign_stations(second.id, [self.agent.station_id])
        self.assertEqual(self.control.rooms.get(first.id).station_ids, [])  # type: ignore[union-attr]
        self.assertEqual(self.control.rooms.get(second.id).station_ids,  # type: ignore[union-attr]
                         [self.agent.station_id])

    def test_lan_key_rotation_uses_old_key_for_the_sync_request(self) -> None:
        result = self.control.sync_settings({"lan_key": "rotated-key"})
        self.assertTrue(all(item.get("ok") for item in result.values()), result)
        # The station accepted the request (signed with the old key) and rotated.
        self.assertEqual(self.agent.auth.key, "rotated-key")
        self.assertTrue(SignedClient("rotated-key").request(
            "127.0.0.1", self.port, "/status", {})["ok"])
        with self.assertRaises(ApiError):
            SignedClient("orch-key").request("127.0.0.1", self.port, "/status", {})
        self.assertEqual(self.control.client.auth.key, "rotated-key")


if __name__ == "__main__":
    unittest.main()
