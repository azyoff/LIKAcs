import unittest
from unittest.mock import patch

from likacs.rcon import (GoldSrcRcon, SERVERDATA_EXECCOMMAND, decode_packets,
                         encode_packet, execute_commands, parse_status)


class RconTests(unittest.TestCase):
    def test_source_packet_codec(self) -> None:
        data = encode_packet(42, SERVERDATA_EXECCOMMAND, "mp_warmup_end")
        packets = decode_packets(data)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].request_id, 42)
        self.assertEqual(packets[0].body, "mp_warmup_end")
        self.assertEqual(len(decode_packets(data + data)), 2)
        self.assertEqual(decode_packets(b"\x00\x00"), [])

    def test_status_parser(self) -> None:
        output = (
            "hostname: LIKAcs Room 1\n"
            '#     12 1 "PlayerOne" STEAM_1:0:123 00:31 42 0 active 786432 192.168.1.22:27005\n'
            '#     13 2 "PlayerTwo" STEAM_1:1:456 00:12 31 0 active 786432 192.168.1.23:27006\n'
        )
        players = parse_status(output)
        self.assertEqual(len(players), 2)
        self.assertEqual(players[0]["userid"], "12")
        self.assertEqual(players[0]["name"], "PlayerOne")
        self.assertEqual(players[0]["ip"], "192.168.1.22")
        self.assertEqual(players[1]["port"], 27006)

    @patch.object(GoldSrcRcon, "command", return_value="ok")
    def test_goldsrc_execute_uses_challenge_rcon(self, _mock: object) -> None:
        results = execute_commands("cs16", "127.0.0.1", 27015, "pw", ["status"])
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["command"], "status")
        self.assertEqual(results[0]["response"], "ok")

    def test_goldsrc_challenge_parser(self) -> None:
        client = GoldSrcRcon("127.0.0.1", 27015, "pw")
        with patch.object(GoldSrcRcon, "_exchange", return_value=b"\xff\xff\xff\xffchallenge rcon 1234567890\n"):
            self.assertEqual(client.challenge(), "1234567890")


if __name__ == "__main__":
    unittest.main()
