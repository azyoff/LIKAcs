"""Generate the LIKAcs tray/desktop icon in memory (pure standard library).

No image library and no external asset is needed, which keeps the PyInstaller
build small and guarantees the tray icon exists inside the standalone .exe.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

SIZE = 32


def _bgra(r: int, g: int, b: int, a: int = 255) -> bytes:
    return bytes((b, g, r, a))


def ico_bytes() -> bytes:
    """Return a valid 32x32 32bpp .ico with a stylised cyan/white 'L'."""
    background = _bgra(11, 18, 32)
    white = _bgra(245, 248, 255)
    cyan = _bgra(34, 211, 238)
    grid = [[background for _ in range(SIZE)] for _ in range(SIZE)]

    # Rounded-ish border
    for y in range(SIZE):
        for x in range(SIZE):
            if x == 0 or y == 0 or x == SIZE - 1 or y == SIZE - 1:
                grid[y][x] = _bgra(31, 48, 74)
    # Letter L
    for y in range(6, 26):
        for x in range(8, 13):
            grid[y][x] = white
    for y in range(21, 26):
        for x in range(8, 24):
            grid[y][x] = white
    # Cyan accent (a second 'player')
    for y in range(6, 12):
        for x in range(18, 24):
            grid[y][x] = cyan

    # DIB rows are bottom-up, BGRA
    xor = bytearray()
    for y in range(SIZE - 1, -1, -1):
        for x in range(SIZE):
            xor += grid[y][x]
    and_mask = bytes((SIZE // 8) * SIZE)  # fully opaque, 4-byte aligned rows
    image_size = len(xor) + len(and_mask)
    dib = struct.pack(
        "<IiiHHIIiiII", 40, SIZE, SIZE * 2, 1, 32, 0, image_size, 0, 0, 0, 0,
    )
    image = dib + bytes(xor) + and_mask
    directory = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", SIZE, SIZE, 0, 0, 1, 32, len(image), 22)
    return directory + entry + image


def write_icon_file(path: str | None = None) -> str:
    """Materialise the icon to disk (Windows LoadImageW needs a filename)."""
    target = Path(path) if path else Path(tempfile.gettempdir()) / "LIKAcs" / "lika.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ico_bytes())
    return str(target)
