import time
import unittest

from likacs.security import (AuthError, LanAuth, NonceCache, canonical_json,
                             sign_packet, verify_packet)


class SecurityTests(unittest.TestCase):
    def test_sign_and_verify_headers(self) -> None:
        auth = LanAuth("cafe-key")
        body = b'{"commands":["mp_warmup_end"]}'
        headers = auth.headers_for(body)
        auth.verify({key.lower(): value for key, value in headers.items()}, body)
        self.assertEqual(len(headers["X-LIKACS-Signature"]), 64)

    def test_replay_rejected(self) -> None:
        auth = LanAuth("cafe-key")
        body = b"{}"
        headers = {key.lower(): value for key, value in auth.headers_for(body).items()}
        auth.verify(headers, body)
        with self.assertRaises(AuthError):
            auth.verify(headers, body)

    def test_tampered_body_or_signature_rejected(self) -> None:
        auth = LanAuth("cafe-key")
        body = b'{"room":1}'
        headers = {key.lower(): value for key, value in auth.headers_for(body).items()}
        with self.assertRaises(AuthError):
            auth.verify(headers, b'{"room":2}')
        bad = dict(headers)
        bad["x-likacs-signature"] = "0" * 64
        with self.assertRaises(AuthError):
            auth.verify(bad, body)

    def test_wrong_key_and_stale_timestamp(self) -> None:
        auth = LanAuth("cafe-key")
        body = b"{}"
        headers = {key.lower(): value for key, value in auth.headers_for(body).items()}
        with self.assertRaises(AuthError):
            LanAuth("different-key").verify(headers, body)
        stale = dict(headers)
        stale["x-likacs-timestamp"] = str(int(time.time()) - 10000)
        with self.assertRaises(AuthError):
            auth.verify(stale, body)

    def test_discovery_packets(self) -> None:
        packet = sign_packet({"kind": "hello", "id": "pc1", "port": 27056}, "lan")
        body = verify_packet(packet, "lan")
        self.assertEqual(body["id"], "pc1")
        with self.assertRaises(AuthError):
            verify_packet(packet, "wrong")
        tampered = dict(packet)
        tampered["port"] = 9999
        with self.assertRaises(AuthError):
            verify_packet(tampered, "lan")
        cache = NonceCache()
        verify_packet(packet, "lan", cache)
        with self.assertRaises(AuthError):
            verify_packet(packet, "lan", cache)

    def test_canonical_json_is_order_independent(self) -> None:
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))


if __name__ == "__main__":
    unittest.main()
