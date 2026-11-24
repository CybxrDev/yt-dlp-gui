"""
The app icon (a white download arrow on a blue rounded square), drawn in code.

Generating it here means no image files or image libraries are needed: `png_bytes()`
encodes it as a PNG using only the standard library. The window uses it at run time and
packaging/build.py writes it to disk as the executable's icon.
"""

from __future__ import annotations

import struct
import zlib

_BLUE = (37, 99, 235, 255)
_WHITE = (255, 255, 255, 255)
_CLEAR = (0, 0, 0, 0)


def _pixel(x: int, y: int, size: int) -> tuple:
    u, v = (x + 0.5) / size, (y + 0.5) / size  # 0..1 across the icon
    low, high, radius = 0.04, 0.96, 0.22
    if not (low <= u <= high and low <= v <= high):
        return _CLEAR
    cx = min(max(u, low + radius), high - radius)
    cy = min(max(v, low + radius), high - radius)
    if (u - cx) ** 2 + (v - cy) ** 2 > radius ** 2:
        return _CLEAR  # outside a rounded corner
    if 0.44 <= u <= 0.56 and 0.18 <= v <= 0.52:
        return _WHITE  # arrow shaft
    if 0.46 <= v <= 0.70 and abs(u - 0.5) <= (0.70 - v) * 0.95:
        return _WHITE  # arrow head
    if 0.26 <= u <= 0.74 and 0.77 <= v <= 0.83:
        return _WHITE  # base line
    return _BLUE


def png_bytes(size: int = 64) -> bytes:
    rows = b"".join(
        b"\x00" + bytes(channel for x in range(size) for channel in _pixel(x, y, size))
        for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
