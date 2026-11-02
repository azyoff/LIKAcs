import tempfile
import unittest
from pathlib import Path

from likacs.paths import detect_installs, install_summary, parse_libraryfolders


class PathTests(unittest.TestCase):
    def test_libraryfolders_vdf_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vdf = Path(directory) / "libraryfolders.vdf"
            vdf.write_text(
                '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n'
                '\t"1"\n\t{\n\t\t"path"\t\t"E:\\\\Games\\\\Steam"\n\t}\n}\n'
            )
            libraries = parse_libraryfolders(vdf)
            self.assertEqual(len(libraries), 2)
            self.assertIn("SteamLibrary", str(libraries[0]))
            self.assertIn("Games", str(libraries[1]))

    def test_manual_overrides_create_installs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = root / "game" / "csgo" / "cfg"
            cfg.mkdir(parents=True)
            exe = root / "game" / "bin" / "win64" / "cs2.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"fake")
            overrides = {
                "cs2": {
                    "root": str(root), "client_exe": str(exe), "server_exe": str(exe),
                    "cfg_dir": str(cfg), "autoexec_name": "autoexec.cfg",
                }
            }
            installs = detect_installs(overrides)
            self.assertIn("cs2", installs)
            self.assertEqual(installs["cs2"].cfg_dir, str(cfg))
            self.assertEqual(installs["cs2"].detected_via, "manual override")
            self.assertTrue(installs["cs2"].exists)
            summary = install_summary(installs)[0]
            self.assertTrue(summary["exists"])
            self.assertIn("autoexec_name", summary)


if __name__ == "__main__":
    unittest.main()
