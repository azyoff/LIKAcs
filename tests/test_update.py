import base64
import io
import tempfile
import unittest
from pathlib import Path

from likacs.update import (Release, UpdateManager, build_swap_script, parse_release,
                           push_update)
from likacs.util import sha256_bytes, version_is_newer


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.data = bytearray()
        self.completed: list[bytes] = []

    def request(self, host: str, port: int, path: str, payload: dict,
                timeout: float | None = None) -> dict:
        self.calls.append((path, payload))
        if path == "/update-begin":
            self.data = bytearray()
            return {"ok": True, "id": "transfer-1"}
        if path == "/update-chunk":
            chunk = base64.b64decode(payload["data"])
            assert payload["offset"] == len(self.data), "chunks must be in order"
            self.data.extend(chunk)
            return {"ok": True, "received": len(self.data)}
        if path == "/update-finish":
            self.completed.append(bytes(self.data))
            return {"ok": True, "staged": True}
        return {"ok": False, "error": "unexpected path"}


class UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_version_comparison(self) -> None:
        self.assertTrue(version_is_newer("v1.1.0", "v1.0.0"))
        self.assertTrue(version_is_newer("1.0.1", "1.0.0"))
        self.assertFalse(version_is_newer("v1.0.0", "v1.0.0"))
        self.assertFalse(version_is_newer("v0.9.9", "v1.0.0"))

    def test_parse_release_and_digest(self) -> None:
        release = parse_release({
            "tag_name": "v1.2.0", "name": "LIKAcs v1.2.0", "body": "notes",
            "html_url": "https://github.com/azyoff/LIKAcs/releases/tag/v1.2.0",
            "assets": [{"name": "LIKAcs.exe", "size": 10,
                        "browser_download_url": "https://example.invalid/LIKAcs.exe",
                        "digest": "sha256:" + "a" * 64}],
        })
        self.assertEqual(release.tag, "v1.2.0")
        self.assertIsNotNone(release.asset("LIKAcs.exe"))
        manager = UpdateManager("azyoff", "LIKAcs", "v1.0.0")
        self.assertEqual(manager.expected_sha256(release, "LIKAcs.exe"), "a" * 64)

    def test_check_with_fake_github_response(self) -> None:
        payload = b'{"tag_name":"v1.3.0","name":"new","body":"","assets":[]}'
        manager = UpdateManager("azyoff", "LIKAcs", "v1.0.0",
                                opener=lambda _request, timeout=None: io.BytesIO(payload))
        result = manager.check()
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest"], "v1.3.0")

    def test_download_verifies_sha256(self) -> None:
        binary = b"LIKAcs fake exe bytes" * 100
        digest = sha256_bytes(binary)
        release = Release("v1.4.0", assets=[{
            "name": "LIKAcs.exe", "size": len(binary),
            "browser_download_url": "https://example.invalid/LIKAcs.exe",
            "digest": "sha256:" + digest,
        }])
        manager = UpdateManager("azyoff", "LIKAcs", "v1.0.0",
                                opener=lambda _request, timeout=None: io.BytesIO(binary))
        result = manager.download(release, "LIKAcs.exe", dest=str(self.root / "LIKAcs.exe"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["sha256"], digest)
        self.assertEqual(Path(result["path"]).read_bytes(), binary)

        bad = Release("v1.4.1", assets=[{
            "name": "LIKAcs.exe", "size": len(binary),
            "browser_download_url": "https://example.invalid/LIKAcs.exe",
            "digest": "sha256:" + "0" * 64,
        }])
        rejected = manager.download(bad, "LIKAcs.exe", dest=str(self.root / "bad.exe"))
        self.assertFalse(rejected["ok"])
        self.assertIn("SHA-256 mismatch", rejected["error"])

    def test_push_update_chunks_reassemble_exactly(self) -> None:
        binary = bytes(range(256)) * 4096  # ~1 MiB, multiple chunks
        asset = self.root / "LIKAcs.exe"
        asset.write_bytes(binary)
        client = FakeClient()
        result = push_update(client, [
            {"id": "pc1", "label": "PC 1", "ip": "192.168.1.5", "agent_port": 27056},
            {"id": "pc2", "label": "PC 2", "ip": "192.168.1.6", "agent_port": 27056},
        ], str(asset), "v1.5.0")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(client.completed, [binary, binary])
        self.assertEqual(result["sha256"], sha256_bytes(binary))
        paths = [path for path, _ in client.calls]
        self.assertIn("/update-begin", paths)
        self.assertIn("/update-chunk", paths)
        self.assertIn("/update-finish", paths)
        self.assertGreaterEqual(paths.count("/update-chunk"), 4)

    def test_swap_script(self) -> None:
        script = build_swap_script("C:/LIKAcs/LIKAcs.exe", "C:/LIKAcs/LIKAcs.exe.new", 4242)
        self.assertIn('set "PID=4242"', script)
        self.assertIn("move /Y", script)
        self.assertIn("--mode=station --silent", script)
        self.assertIn("tasklist", script)


if __name__ == "__main__":
    unittest.main()
