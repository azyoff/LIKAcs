"""Offline test for the release latest.json generator."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_build_module() -> object:
    spec = importlib.util.spec_from_file_location("likacs_build", ROOT / "scripts" / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildManifestTests(unittest.TestCase):
    def test_manifest_only_advertises_release_assets(self) -> None:
        build = load_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "LIKAcs.exe").write_bytes(b"MZ" + b"x" * 1000)
            (dist / "LIKAcs-Setup.exe").write_bytes(b"MZ" + b"y" * 2000)
            checksums = {
                "LIKAcs.exe": "a" * 64,
                "LIKAcs-Setup.exe": "b" * 64,
                "LIKAcs-ControlCenter.exe": "c" * 64,
                "README.md": "d" * 64,
            }
            with mock.patch.object(build, "DIST", dist):
                path = build.write_manifest("v1.1.0", checksums)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["tag"], "v1.1.0")
            self.assertEqual(payload["assets"]["LIKAcs.exe"]["sha256"], "a" * 64)
            # No dead links: the Setup exe is an Actions-only artifact.
            self.assertNotIn("LIKAcs-Setup.exe", payload["assets"])
            self.assertNotIn("LIKAcs-ControlCenter.exe", payload["assets"])
            self.assertIn("v1.1.0/LIKAcs.exe", payload["download_url"])
            self.assertEqual(payload["download_name"], "LIKAcs.exe")


if __name__ == "__main__":
    unittest.main()
