"""Offline tests for the one-click GitHub self-update flow."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from likacs import VERSION
from likacs.selfupdate import (SelfUpdater, UpdateInfo, build_manifest,
                               build_self_swap_script, manifest_url,
                               parse_manifest)


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.chunks = [data]

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            return self.data
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class FakeOpener:
    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.requested: list[str] = []

    def __call__(self, request: object, timeout: float | None = None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        self.requested.append(url)
        if url not in self.mapping:
            raise OSError(f"unexpected URL {url}")
        return FakeResponse(self.mapping[url])


def manifest(version: str, digest: str, size: int, extras: dict | None = None) -> bytes:
    payload = {
        "schema": 1, "product": "LIKAcs", "version": version,
        "tag": f"v{version}", "notes": "Bug fixes and a faster installer.",
        "published_at": "2026-11-02T00:00:00Z",
        "html_url": "https://github.com/azyoff/LIKAcs/releases/tag/vX",
        "assets": {"LIKAcs.exe": {
            "url": f"https://github.com/azyoff/LIKAcs/releases/download/v{version}/LIKAcs.exe",
            "sha256": digest, "size": size}},
    }
    if extras:
        payload.update(extras)
    return json.dumps(payload).encode("utf-8")


class SelfUpdateTests(unittest.TestCase):
    def test_manifest_url_is_the_stable_latest_asset(self) -> None:
        self.assertEqual(manifest_url(),
                         "https://github.com/azyoff/LIKAcs/releases/latest/download/latest.json")

    def test_parse_manifest_defaults_urls_from_tag(self) -> None:
        info = parse_manifest({"version": "1.1.0", "tag": "v1.1.0"})
        self.assertEqual(info.url,
                         "https://github.com/azyoff/LIKAcs/releases/download/v1.1.0/LIKAcs.exe")
        self.assertTrue(info.checksums_url.endswith("v1.1.0/SHA256SUMS.txt"))
        self.assertEqual(info.version, "1.1.0")

    def test_parse_manifest_rejects_bad_digest(self) -> None:
        with self.assertRaises(ValueError):
            parse_manifest({"version": "1.1.0", "assets": {
                "LIKAcs.exe": {"sha256": "not-a-sha256"}}})

    def test_build_manifest_only_lists_real_assets(self) -> None:
        digest = "a" * 64
        built = build_manifest("v1.1.0", {"LIKAcs.exe": digest, "README.md": "b" * 64},
                               {"LIKAcs.exe": 12345}, version="1.1.0")
        self.assertEqual(built["product"], "LIKAcs")
        self.assertEqual(built["website"], "http://likaapps.com")
        self.assertEqual(list(built["assets"]), ["LIKAcs.exe"])
        self.assertEqual(built["assets"]["LIKAcs.exe"]["size"], 12345)
        self.assertIn("v1.1.0/LIKAcs.exe", built["assets"]["LIKAcs.exe"]["url"])

    def test_check_uses_manifest_without_hitting_the_api(self) -> None:
        opener = FakeOpener({manifest_url(): manifest("9.9.9", "c" * 64, 100)})
        result = SelfUpdater(current_version="1.0.0", opener=opener).check()
        self.assertTrue(result["ok"])
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest"], "v9.9.9")
        self.assertEqual(result["source"], "manifest")
        self.assertEqual(opener.requested, [manifest_url()])

    def test_check_reports_up_to_date(self) -> None:
        opener = FakeOpener({manifest_url(): manifest(VERSION, "c" * 64, 100)})
        result = SelfUpdater(opener=opener).check()
        self.assertTrue(result["ok"])
        self.assertFalse(result["update_available"])

    def test_one_click_update_is_a_noop_when_up_to_date(self) -> None:
        opener = FakeOpener({manifest_url(): manifest(VERSION, "c" * 64, 100)})
        result = SelfUpdater(opener=opener).one_click_update()
        self.assertTrue(result["ok"])
        self.assertTrue(result["up_to_date"])
        self.assertFalse(result.get("restarting"))

    def test_download_verified_against_manifest_and_checksums(self) -> None:
        content = b"MZ" + b"a real verified executable" * 100
        digest = hashlib.sha256(content).hexdigest()
        tag = "v9.9.9"
        exe_url = f"https://github.com/azyoff/LIKAcs/releases/download/{tag}/LIKAcs.exe"
        sums_url = f"https://github.com/azyoff/LIKAcs/releases/download/{tag}/SHA256SUMS.txt"
        opener = FakeOpener({
            manifest_url(): manifest("9.9.9", digest, len(content)),
            exe_url: content,
            sums_url: f"{digest}  LIKAcs.exe\n{'f' * 64}  README.md\n".encode(),
        })
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "LIKAcs.exe.new"
            result = SelfUpdater(opener=opener).download_verified(
                parse_manifest(json.loads(manifest("9.9.9", digest, len(content)))),
                dest)
            self.assertTrue(result["ok"], result)
            self.assertEqual(dest.read_bytes(), content)
            self.assertEqual(result["sha256"], digest)

    def test_download_is_discarded_on_sha256_mismatch(self) -> None:
        content = b"not the expected bytes"
        bad = "1" * 64
        exe_url = "https://github.com/azyoff/LIKAcs/releases/download/v9.9.9/LIKAcs.exe"
        opener = FakeOpener({exe_url: content})
        info = parse_manifest(json.loads(manifest("9.9.9", bad, len(content))))
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "LIKAcs.exe.new"
            result = SelfUpdater(opener=opener).download_verified(info, dest)
            self.assertFalse(result["ok"])
            self.assertIn("mismatch", result["error"])
            self.assertFalse(dest.exists())

    def test_download_is_discarded_when_checksums_disagree(self) -> None:
        content = b"MZ payload"
        digest = hashlib.sha256(content).hexdigest()
        tag = "v9.9.9"
        exe_url = f"https://github.com/azyoff/LIKAcs/releases/download/{tag}/LIKAcs.exe"
        sums_url = f"https://github.com/azyoff/LIKAcs/releases/download/{tag}/SHA256SUMS.txt"
        opener = FakeOpener({
            exe_url: content,
            sums_url: f"{'0' * 64}  LIKAcs.exe\n".encode(),
        })
        info = parse_manifest(json.loads(manifest(tag.lstrip("v"), digest, len(content))))
        with TemporaryDirectory() as tmp:
            result = SelfUpdater(opener=opener).download_verified(info, Path(tmp) / "x.new")
            self.assertFalse(result["ok"])
            self.assertIn("SHA256SUMS.txt disagrees", result["error"])

    def test_swap_script_verifies_boot_and_rolls_back(self) -> None:
        script = build_self_swap_script(r"C:\LIKAcs\LIKAcs.exe",
                                        r"C:\LIKAcs\LIKAcs.exe.new",
                                        r"C:\LIKAcs\LIKAcs.exe.bak", 4242)
        self.assertIn('set "PID=4242"', script)
        self.assertIn("WaitForExit(20000)", script)
        self.assertIn("--version", script)
        self.assertIn("powershell", script)
        self.assertIn("goto rollback", script)
        self.assertIn('copy /Y "%TARGET%" "%BACKUP%"', script)
        self.assertIn("update failed - previous version restored", script)

    def test_stage_swap_refuses_to_replace_python_in_a_source_checkout(self) -> None:
        result = SelfUpdater().stage_swap(Path("LIKAcs.exe.new"))
        self.assertFalse(result["ok"])
        self.assertIn("installed LIKAcs.exe", result["error"])

    def test_update_info_serialises_for_cli_json(self) -> None:
        info = UpdateInfo(version="1.1.0", tag="v1.1.0", sha256="a" * 64)
        self.assertEqual(info.to_dict()["tag"], "v1.1.0")


if __name__ == "__main__":
    unittest.main()
