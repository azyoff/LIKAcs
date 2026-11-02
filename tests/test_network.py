import time
import unittest

from likacs.network import DiscoveryService, StationTable
from likacs.security import AuthError, sign_packet, verify_packet
from tests import free_udp_port


class NetworkTests(unittest.TestCase):
    def test_station_table_expiry(self) -> None:
        table = StationTable(timeout=10)
        table.update({"id": "pc1", "label": "PC 1", "ip": "192.168.1.5"})
        table.update({"id": "pc2", "label": "PC 2", "ip": "192.168.1.6"})
        self.assertEqual(len(table.all()), 2)
        self.assertEqual(table.get("pc1")["label"], "PC 1")
        table.timeout = -1
        self.assertEqual(set(table.expire()), {"pc1", "pc2"})
        self.assertEqual(table.all(), [])
        table.remove("missing")

    def test_signed_discovery_packet(self) -> None:
        packet = sign_packet({"kind": "probe", "id": "controller"}, "lan-key")
        self.assertEqual(verify_packet(packet, "lan-key")["kind"], "probe")
        with self.assertRaises(AuthError):
            verify_packet({"kind": "probe", "magic": "WRONG"}, "lan-key")

    def test_udp_heartbeat_self_delivery(self) -> None:
        port = free_udp_port()
        received: list[dict] = []
        service = DiscoveryService(
            port, "lan-key",
            heartbeat_factory=lambda: {"kind": "hello", "id": "pc1", "label": "PC 1"},
            on_message=lambda body, addr: received.append(body),
            broadcast_targets=["127.0.0.1"],
            logger=lambda _message: None,
        )
        service.start()
        try:
            service.announce_now()
            deadline = time.time() + 3.0
            while not received and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(received, "signed heartbeat was not received")
            self.assertEqual(received[0]["id"], "pc1")
            self.assertEqual(received[0]["kind"], "hello")
        finally:
            service.stop()
        self.assertFalse(service.running)

    def test_unsigned_packets_are_ignored_by_verifier(self) -> None:
        port = free_udp_port()
        service = DiscoveryService(port, "lan-key", logger=lambda _m: None)
        with self.assertRaises(AuthError):
            verify_packet({"magic": "LIKACS/1", "kind": "hello"}, "lan-key")


if __name__ == "__main__":
    unittest.main()
