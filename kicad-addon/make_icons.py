#!/usr/bin/env python3
"""Draw the add-on's icons (standard library only): a rounded square with a
white speech bubble and three dots.  Writes plugins/icons/chat-{24,48}[-dark].png
(toolbar) and resources/icon.png (64x64, shown in the Plugin and Content Manager)."""
import struct
import zlib
from pathlib import Path

SS = 4      # supersampling for smooth edges


def rrect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def sample(u, v, bg, fg):
    """Colour at (u, v) in the unit square, or None for transparent."""
    if not rrect(u, v, 0.02, 0.02, 0.98, 0.98, 0.20):
        return None
    bubble = rrect(u, v, 0.16, 0.20, 0.84, 0.66, 0.13)
    tail = 0.28 <= u <= 0.48 and 0.64 <= v <= 0.84 and (u - 0.28) <= (0.84 - v)
    if bubble or tail:
        for cx in (0.34, 0.50, 0.66):
            if (u - cx) ** 2 + (v - 0.43) ** 2 <= 0.055 ** 2:
                return bg
        return fg
    return bg


def png(size, bg, fg=(255, 255, 255)):
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            acc, n = [0, 0, 0], 0
            for sy in range(SS):
                for sx in range(SS):
                    c = sample((x + (sx + .5) / SS) / size, (y + (sy + .5) / SS) / size, bg, fg)
                    if c:
                        n += 1
                        for i in range(3):
                            acc[i] += c[i]
            row += bytes((acc[0] // n, acc[1] // n, acc[2] // n, 255 * n // (SS * SS))) if n else bytes(4)
        rows.append(bytes(row))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def main():
    here = Path(__file__).resolve().parent
    light, dark = (0, 121, 107), (38, 166, 154)
    icons = here / "plugins" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for s in (24, 48):
        (icons / f"chat-{s}.png").write_bytes(png(s, light))
        (icons / f"chat-{s}-dark.png").write_bytes(png(s, dark))
    (here / "resources").mkdir(exist_ok=True)
    (here / "resources" / "icon.png").write_bytes(png(64, light))
    print("icons written")


if __name__ == "__main__":
    main()
