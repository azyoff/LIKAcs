"""CI guard: fail the build if any game-memory / injection technique appears.

LIKAcs promises 100% VAC safety. This scanner strips comments and string
literals (docs describing what we must NOT do are fine) and inspects only real
code tokens for forbidden Windows APIs and binary-patching constructs. It also
asserts that the official mechanisms are still present.
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "likacs"
sys.path.insert(0, str(ROOT / "src"))

FORBIDDEN = [
    r"WriteProcessMemory", r"ReadProcessMemory", r"OpenProcess\s*\(",
    r"CreateRemoteThread", r"VirtualAllocEx", r"VirtualProtectEx",
    r"NtWriteVirtualMemory", r"SetWindowsHookEx", r"LoadLibraryA",
    r"LoadLibraryW", r"QueueUserAPC", r"WritePrivateProfileString",
    r"pymem", r"inject_dll", r"dll_inject", r"patch_binary",
    r"patch_game", r"memory\.write", r"mem_write", r"\bcheat\b\s*=",
    r"-insecure",
]
POSITIVE = [
    r"exec lika_autoexec\.cfg",
    r"sv_lan",
    r"rcon_password",
    r"steam://connect/",
    r"-usercon",
]


def code_only(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    tokens: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                              tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                              tokenize.ENCODING, tokenize.ENDMARKER):
                continue
            tokens.append(token.string)
    except (tokenize.TokenError, IndentationError):
        return text
    return " ".join(tokens)


def main() -> int:
    violations: list[str] = []
    corpus: list[str] = []
    raw_corpus: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        code = code_only(path)
        corpus.append(code)
        raw_corpus.append(path.read_text(encoding="utf-8", errors="replace"))
        for pattern in FORBIDDEN:
            if re.search(pattern, code, re.IGNORECASE):
                violations.append(f"{path.relative_to(ROOT)}: forbidden pattern {pattern}")
    joined = "\n".join(raw_corpus)  # official strings live inside string literals
    missing = [pattern for pattern in POSITIVE if not re.search(pattern, joined, re.IGNORECASE)]
    for pattern in missing:
        violations.append(f"official mechanism missing from source: {pattern}")

    # Runtime assertion on the generated launch command line.
    try:
        from likacs.games import build_server_argv
        install = {"client_exe": "C:/Steam/cs2.exe", "server_exe": "C:/Steam/cs2.exe",
                   "cfg_dir": "C:/Steam/cfg", "root": "C:/Steam"}
        argv, _ = build_server_argv(install, {
            "game": "cs2", "map": "de_dust2", "port": 27015, "slots": 10,
            "rcon_password": "x", "name": "Room 1", "server_mode": "listen",
        })
        line = " ".join(argv).lower()
        if "-insecure" in line or ".dll" in line:
            violations.append("generated launch args contain a VAC-disabling/injection flag")
        if "+sv_lan" not in argv or "-usercon" not in argv:
            violations.append("generated launch args are missing official LAN/RCON flags")
    except Exception as exc:
        violations.append(f"could not verify launch args: {exc}")

    if violations:
        print("VAC SAFETY CHECK FAILED:")
        for item in violations:
            print(f"  - {item}")
        return 1
    print("VAC SAFETY CHECK PASSED - no memory access, no DLL injection, no binary patching.")
    print("Official mechanisms present: cfg exec, sv_lan 1, -usercon, rcon_password, steam://connect/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
