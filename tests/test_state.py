import tempfile
import unittest
from pathlib import Path

from likacs.config import Settings
from likacs.state import RoomManager, StationLabels


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "rooms.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_room_creation_names_and_ports(self) -> None:
        manager = RoomManager(self.path, Settings())
        first = manager.create(game="cs2", preset="2vs2", map="de_mirage")
        second = manager.create(game="cs16", preset="1vs1", map="fy_snow")
        self.assertEqual(first.name, "Room 1")
        self.assertEqual(second.name, "Room 2")
        self.assertEqual(first.port, 27015)
        self.assertEqual(second.port, 27016)
        self.assertTrue(first.rcon_password)
        self.assertNotEqual(first.rcon_password, second.rcon_password)
        self.assertEqual(first.slots, 4)
        self.assertEqual(len(manager.statuses()), 2)

    def test_update_delete_and_persistence(self) -> None:
        manager = RoomManager(self.path, Settings())
        room = manager.create(preset="5vs5")
        manager.update(room.id, {"state": "live", "station_ids": ["pc1", "pc2"],
                                 "map": "de_nuke", "host_station_id": "pc1"})
        reloaded = RoomManager(self.path, Settings())
        loaded = reloaded.get(room.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.state, "live")  # type: ignore[union-attr]
        self.assertEqual(loaded.map, "de_nuke")  # type: ignore[union-attr]
        self.assertEqual(reloaded.room_for_station("pc2").id, room.id)  # type: ignore[union-attr]
        self.assertTrue(reloaded.delete(room.id))
        self.assertEqual(RoomManager(self.path, Settings()).list(), [])

    def test_rules_are_merged_with_defaults(self) -> None:
        manager = RoomManager(self.path, Settings())
        room = manager.create(rules={"mp_freezetime": "9"})
        self.assertEqual(room.rules["mp_freezetime"], "9")
        self.assertEqual(room.rules["sv_lan"], "1")

    def test_station_labels(self) -> None:
        path = str(Path(self.tmp.name) / "labels.json")
        labels = StationLabels(path)
        self.assertEqual(labels.get("pc1", "fallback"), "fallback")
        labels.set("pc1", "PC 1")
        self.assertEqual(StationLabels(path).get("pc1"), "PC 1")


if __name__ == "__main__":
    unittest.main()
