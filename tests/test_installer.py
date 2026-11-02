"""Offline tests for the per-user installer / uninstaller engine."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from likacs import VERSION, WEBSITE
from likacs.installer import (APP_EXE, INSTALL_MANIFEST, InstallPlan, install,
                              launch_app, registry_values, shortcut_paths,
                              smoke_install, uninstall)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="likacs-installer-test-")
        base = Path(self.tmp.name)
        self.payload = base / "payload.exe"
        self.payload.write_bytes(b"MZ" + b"likacs-test-payload" * 200)
        self.patch = mock.patch.dict(os.environ, {"LIKACS_PAYLOAD": str(self.payload)})
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def plan(self, **kwargs: object) -> InstallPlan:
        options = dict(
            install_dir=Path(self.tmp.name) / "installed",
            desktop_shortcut=False, start_menu_shortcut=False,
            autostart_station=False, launch_after=False, register_uninstall=False,
        )
        options.update(kwargs)
        return InstallPlan(**options)  # type: ignore[arg-type]

    def test_install_copies_embedded_payload_byte_for_byte(self) -> None:
        plan = self.plan()
        report = install(plan)
        self.assertTrue(report["ok"], report)
        target = Path(report["exe"])
        self.assertEqual(target.name, APP_EXE)
        self.assertEqual(target.read_bytes(), self.payload.read_bytes())
        self.assertEqual(report["version"], VERSION)
        manifest = json.loads((plan.install_dir / INSTALL_MANIFEST).read_text())
        self.assertEqual(manifest["website"], WEBSITE)
        self.assertEqual(manifest["product"], "LIKAcs")

    def test_uninstall_removes_the_folder_and_reports_success(self) -> None:
        plan = self.plan()
        self.assertTrue(install(plan)["ok"])
        removed = uninstall(plan.install_dir)
        self.assertTrue(removed["ok"], removed)
        # On Linux the cleanup is synchronous; on Windows a delayed .cmd runs.
        if os.name != "nt":
            self.assertFalse(plan.install_dir.exists())

    def test_smoke_install_end_to_end(self) -> None:
        self.assertEqual(smoke_install(), 0)

    def test_registry_values_point_at_a_real_uninstall_command(self) -> None:
        exe = Path("C:/Users/Cafe/AppData/Local/LIKAcs/LIKAcs.exe")
        values = registry_values(self.plan(), exe)
        self.assertIn("--mode=uninstall", values["UninstallString"])
        self.assertIn("--silent", values["QuietUninstallString"])
        self.assertEqual(values["URLInfoAbout"], WEBSITE)
        self.assertEqual(values["DisplayName"], "LIKAcs")
        self.assertIn("releases/latest", values["URLUpdateInfo"])

    def test_shortcuts_cover_chooser_control_center_and_station(self) -> None:
        plan = InstallPlan(install_dir=Path(self.tmp.name) / "installed",
                           desktop_shortcut=True, start_menu_shortcut=True)
        paths = shortcut_paths(plan)
        names = {path.name for path in paths.values()}
        self.assertIn("LIKAcs.lnk", names)
        self.assertIn("LIKAcs Control Center.lnk", names)
        self.assertIn("LIKAcs Station Agent.lnk", names)
        self.assertIn("LIKAcs Website.url", names)

    def test_progress_reaches_one_hundred(self) -> None:
        seen: list[int] = []
        report = install(self.plan(), progress=lambda label, percent: seen.append(percent))
        self.assertTrue(report["ok"])
        self.assertEqual(seen[-1], 100)
        self.assertGreater(len(seen), 3)

    def test_launch_app_is_safe_when_exe_is_missing(self) -> None:
        self.assertFalse(launch_app(Path(self.tmp.name) / "missing.exe"))


if __name__ == "__main__":
    unittest.main()
