import json
import unittest
import urllib.error
import urllib.request

from likacs.http_api import AgentHTTPServer, ApiError, SignedClient
from likacs.security import LanAuth
from tests import free_port


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = LanAuth("test-lan-key")
        self.server = AgentHTTPServer(
            ("127.0.0.1", 0), self.auth,
            lambda path, payload: (200, {"ok": True, "path": path, "echo": payload}),
            logger=lambda _message: None,
        )
        self.server.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.stop()

    def test_signed_request_roundtrip(self) -> None:
        client = SignedClient("test-lan-key")
        result = client.request("127.0.0.1", self.port, "/configure-join",
                                {"primary": {"host": "192.168.1.5", "port": 27015}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "/configure-join")
        self.assertEqual(result["echo"]["primary"]["port"], 27015)
        self.assertTrue(client.status("127.0.0.1", self.port)["ok"])

    def test_wrong_key_returns_401(self) -> None:
        with self.assertRaises(ApiError) as context:
            SignedClient("wrong-key").request("127.0.0.1", self.port, "/status", {})
        self.assertIn("bad signature", str(context.exception))

    def test_replayed_request_returns_401(self) -> None:
        client = SignedClient("test-lan-key")
        body = json.dumps({"x": 1}, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", **client.auth.headers_for(body)}

        def send() -> None:
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/status", data=body,
                headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=3) as response:
                response.read()

        send()
        with self.assertRaises(urllib.error.HTTPError) as context:
            send()
        self.assertEqual(context.exception.code, 401)

    def test_read_only_identity_page(self) -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/ping", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["website"], "http://likaapps.com")
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
