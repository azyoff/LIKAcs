"""Headless smoke test used by `--self-test` and the CI build job.

No GUI, no Steam and no network access required. Verifies the cfg generator,
HMAC signing, signed HTTP API, RCON packet codec, tooltip limit and the VAC-safe
launch argument policy.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

from . import VERSION, WEBSITE


def run() -> int:
    from .cfgs import CfgManager, JoinTarget, LIKA_AUTOEXEC, LIKA_JOIN, HOOK_LINE
    from .games import build_server_argv
    from .http_api import AgentHTTPServer, ApiError, SignedClient
    from .security import AuthError, LanAuth, sign_packet, verify_packet
    from .rcon import decode_packets, encode_packet
    from .branding import fit_tray_tooltip

    results: list[tuple[str, bool, str]] = []

    def check(name: str, function: Callable[[], None]) -> None:
        try:
            function()
            results.append((name, True, ""))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    with tempfile.TemporaryDirectory(prefix="likacs-selftest-") as directory:
        os.environ.setdefault("XDG_CONFIG_HOME", directory)
        root = Path(directory)
        cfg_dir = root / "cfg"
        cfg_dir.mkdir()

        def cfg_test() -> None:
            manager = CfgManager(cfg_dir, "cs2")
            manager.install("lika", "F10", True)
            hook = (cfg_dir / "autoexec.cfg").read_text()
            original_line = "bind \"MOUSE1\" \"+attack\"\n"
            (cfg_dir / "autoexec.cfg").write_text(original_line + hook)
            manager.install("lika", "F10", True)
            text = (cfg_dir / "autoexec.cfg").read_text()
            assert text.count(HOOK_LINE) == 1, "hook was duplicated"
            assert original_line.strip() in text, "player settings were overwritten"
            assert (cfg_dir / LIKA_AUTOEXEC).exists()
            assert 'alias "lika" "exec lika_join.cfg"' in (cfg_dir / LIKA_AUTOEXEC).read_text()
            assert 'bind "F10" "lika"' in (cfg_dir / LIKA_AUTOEXEC).read_text()
            # Real-time retarget: alias stays untouched, only the tiny file changes.
            manager.set_target(JoinTarget("192.168.1.5", 27016, room_name="Room 2"))
            assert "connect 192.168.1.5:27016" in (cfg_dir / LIKA_JOIN).read_text()
            manager.set_target(JoinTarget("192.168.1.10", 27015, room_name="Room 1"))
            assert "connect 192.168.1.10:27015" in (cfg_dir / LIKA_JOIN).read_text()
            assert 'bind "F10" "quit prompt"' not in (cfg_dir / LIKA_AUTOEXEC).read_text()

        check("official cfg hooks + real-time lika retarget", cfg_test)

        def security_test() -> None:
            auth = LanAuth("cafe-secret")
            body = b'{"command":"start"}'
            headers = auth.headers_for(body)
            auth.verify({k.lower(): v for k, v in headers.items()}, body)
            try:
                auth.verify(headers, body)  # replay
                raise AssertionError("replay was accepted")
            except AuthError:
                pass
            tampered = dict(headers)
            tampered["x-likacs-signature"] = "0" * 64
            try:
                auth.verify(tampered, body)
                raise AssertionError("tampered signature accepted")
            except AuthError:
                pass
            packet = sign_packet({"kind": "hello", "id": "pc1"}, "cafe-secret")
            verify_packet(packet, "cafe-secret")
            try:
                verify_packet(packet, "wrong-key")
                raise AssertionError("wrong LAN key accepted")
            except AuthError:
                pass

        check("HMAC signing + replay/tamper protection", security_test)

        def http_test() -> None:
            auth = LanAuth("lan-test-key")
            server = AgentHTTPServer(("127.0.0.1", 0), auth,
                                     lambda path, payload: (200, {"ok": True, "echo": payload}),
                                     logger=lambda _m: None)
            server.start()
            try:
                port = int(server.server_address[1])
                good = SignedClient("lan-test-key")
                reply = good.request("127.0.0.1", port, "/status", {"room": 1})
                assert reply["echo"]["room"] == 1
                try:
                    SignedClient("wrong-key").request("127.0.0.1", port, "/status", {})
                    raise AssertionError("unsigned/wrong-key request accepted")
                except ApiError:
                    pass
            finally:
                server.stop()

        check("signed HTTP/JSON station API", http_test)

        def vac_test() -> None:
            install = {
                "game": "cs2", "client_exe": "C:/Steam/cs2.exe",
                "server_exe": "C:/Steam/cs2.exe", "cfg_dir": str(cfg_dir),
                "root": "C:/Steam",
            }
            argv, _ = build_server_argv(install, {
                "game": "cs2", "map": "de_dust2", "port": 27015, "slots": 10,
                "rcon_password": "secret", "name": "Room 1", "server_mode": "listen",
            })
            joined = " ".join(argv).lower()
            for forbidden in ("-insecure", "pymem", "writeprocessmemory",
                              "readprocessmemory", "createremotethread", ".dll",
                              "virtualallocex"):
                assert forbidden not in joined, f"forbidden token in launch args: {forbidden}"
            assert "+sv_lan" in argv and "1" in argv
            assert "-usercon" in argv
            assert "+rcon_password" in argv

        check("VAC-safe official launch parameters", vac_test)

        def rcon_test() -> None:
            packet = encode_packet(7, 2, "status")
            decoded = decode_packets(packet)
            assert len(decoded) == 1 and decoded[0].body == "status" and decoded[0].request_id == 7
            assert decode_packets(packet + packet)[1].body == "status"
            assert len(fit_tray_tooltip([f"Room {i}: 5vs5 playing" for i in range(50)])) <= 127

        check("RCON packet codec + 127-char tray tooltip", rcon_test)

    width = max(len(name) for name, _, _ in results) + 2
    print(f"LIKAcs v{VERSION} - headless self-test ({WEBSITE})")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<{width}} {detail}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
