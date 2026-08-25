"""Render the itkFlow app icon to a PNG, using only the standard library.

Deliberately dependency-free: this runs in the packaging pipeline, and a build
step that needs a wheel from the network is a build step that breaks. Shapes
are signed-distance fields so edges anti-alias without supersampling.

The motif is the thing itkFlow is about: silicon strips (vertical) crossed by
a hybrid (horizontal bar).

    python desktop/make-icon.py desktop/icon-source.png
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SIZE = 1024

BACKDROP_TOP = (0x14, 0x1F, 0x35)
BACKDROP_BOTTOM = (0x08, 0x0E, 0x1A)
STRIP_COLOR = (0x38, 0xBD, 0xF8)
HYBRID_COLOR = (0xF5, 0x9E, 0x0B)


def rounded_rect_distance(
    x: float, y: float, cx: float, cy: float, half_w: float, half_h: float, radius: float
) -> float:
    """Signed distance to a rounded rectangle; negative inside."""
    dx = abs(x - cx) - (half_w - radius)
    dy = abs(y - cy) - (half_h - radius)
    outside = ((max(dx, 0.0)) ** 2 + (max(dy, 0.0)) ** 2) ** 0.5
    return outside + min(max(dx, dy), 0.0) - radius


def coverage(distance: float, softness: float = 1.0) -> float:
    """Map a signed distance to 0..1 alpha across roughly one pixel."""
    if distance <= -softness:
        return 1.0
    if distance >= softness:
        return 0.0
    return (softness - distance) / (2.0 * softness)


def blend(base: tuple[float, float, float], layer, alpha: float):
    return tuple(base[i] * (1.0 - alpha) + layer[i] * alpha for i in range(3))


def render() -> bytes:
    strips = []
    strip_count = 7
    strip_width = 46.0
    strip_gap = 34.0
    total = strip_count * strip_width + (strip_count - 1) * strip_gap
    first_center = SIZE / 2 - total / 2 + strip_width / 2
    for index in range(strip_count):
        strips.append(first_center + index * (strip_width + strip_gap))

    rows = bytearray()
    for py in range(SIZE):
        rows.append(0)  # PNG filter type 0 for each scanline
        y = py + 0.5
        gradient = py / (SIZE - 1)
        backdrop = tuple(
            BACKDROP_TOP[i] * (1.0 - gradient) + BACKDROP_BOTTOM[i] * gradient
            for i in range(3)
        )
        for px in range(SIZE):
            x = px + 0.5

            body = coverage(
                rounded_rect_distance(x, y, SIZE / 2, SIZE / 2, 448.0, 448.0, 200.0)
            )
            if body <= 0.0:
                rows.extend((0, 0, 0, 0))
                continue

            colour = backdrop

            # Strips: rounded vertical bars.
            for centre in strips:
                alpha = coverage(
                    rounded_rect_distance(x, y, centre, 500.0, strip_width / 2, 232.0, 22.0)
                )
                if alpha > 0.0:
                    colour = blend(colour, STRIP_COLOR, alpha)

            # Hybrid: one horizontal bar across them.
            hybrid = coverage(
                rounded_rect_distance(x, y, SIZE / 2, 632.0, 322.0, 44.0, 40.0)
            )
            if hybrid > 0.0:
                colour = blend(colour, HYBRID_COLOR, hybrid)

            rows.extend(
                (
                    int(colour[0] + 0.5),
                    int(colour[1] + 0.5),
                    int(colour[2] + 0.5),
                    int(body * 255.0 + 0.5),
                )
            )
    return bytes(rows)


def png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, raw: bytes) -> None:
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8-bit RGBA
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else "desktop/icon-source.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    write_png(target, render())
    print(f"wrote {target} ({target.stat().st_size / 1024:.0f} kB, {SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
