"""Generate the installable-app icons, with no image library.

The kit ships no Pillow and no binary assets, and the CSP only allows same-origin
images, so the icons have to be produced here and committed as real PNGs. This
writes them with zlib + struct directly: a few dozen lines, deterministic output,
and nothing new in requirements.txt.

The mark is the product's own dual-role idea rather than decoration: a warm
orange listening dot resting inside a calm blue rounded square — 优活 (blue,
errands) holding 无忧伴 (orange, company). It reads at 48px, which is the size
that actually matters on a home screen.

    python backend/scripts/make_app_icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "static" / "icons"

BLUE = (0x2F, 0x6F, 0xB5)
BLUE_LIGHT = (0x4A, 0x90, 0xD9)
ORANGE = (0xF5, 0xA6, 0x23)
WHITE = (0xFF, 0xFF, 0xFF)

#: Supersampling factor. 3x is enough to make the curves read as smooth at 48px
#: without the generator getting slow at 512.
SS = 3


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[float, float, float]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _rounded_square_sdf(x: float, y: float, half: float, radius: float) -> float:
    """Signed distance to a rounded square centred on the origin."""
    dx = abs(x) - (half - radius)
    dy = abs(y) - (half - radius)
    outside = (max(dx, 0.0) ** 2 + max(dy, 0.0) ** 2) ** 0.5
    inside = min(max(dx, dy), 0.0)
    return outside + inside - radius


def _sample(nx: float, ny: float, maskable: bool) -> tuple[float, float, float, float]:
    """Colour and alpha at normalised coordinates in [-1, 1]."""
    # A maskable icon may be cropped to a circle of ~80% width by the launcher,
    # so the artwork has to sit inside the safe zone and bleed to the edges.
    plate_half = 1.0 if maskable else 0.86
    plate_radius = 0.0 if maskable else 0.30

    d = _rounded_square_sdf(nx, ny, plate_half, plate_radius)
    edge = 0.012
    plate_alpha = max(0.0, min(1.0, 0.5 - d / edge))
    if plate_alpha <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)

    # Diagonal brand gradient, light at the top-left.
    t = max(0.0, min(1.0, (nx + ny + 2) / 4))
    colour = _lerp(BLUE_LIGHT, BLUE, t)

    # The listening dot: warm, off-centre low-right, the way the orange pulse
    # sits under the elder's microphone on screen.
    dot_r = 0.30 if maskable else 0.26
    dot = ((nx - 0.20) ** 2 + (ny - 0.18) ** 2) ** 0.5 - dot_r
    dot_alpha = max(0.0, min(1.0, 0.5 - dot / edge))
    if dot_alpha > 0.0:
        colour = _lerp(colour, ORANGE, dot_alpha)

    # A calm white arc above it, suggesting speech without spelling out a bubble.
    ring = abs(((nx + 0.16) ** 2 + (ny + 0.20) ** 2) ** 0.5 - 0.40) - 0.055
    ring_alpha = max(0.0, min(1.0, 0.5 - ring / edge))
    if ring_alpha > 0.0 and ny < 0.16:
        colour = _lerp(colour, WHITE, ring_alpha * 0.92)

    return (*colour, plate_alpha)


def render(size: int, *, maskable: bool) -> bytes:
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    nx = ((px + (sx + 0.5) / SS) / size) * 2 - 1
                    ny = ((py + (sy + 0.5) / SS) / size) * 2 - 1
                    cr, cg, cb, ca = _sample(nx, ny, maskable)
                    r += cr * ca
                    g += cg * ca
                    b += cb * ca
                    a += ca
            n = SS * SS
            if a > 0:
                # Un-premultiply so edge pixels keep their colour.
                row += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))

    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for size in (192, 512):
        for maskable in (False, True):
            name = f"icon-{size}{'-maskable' if maskable else ''}.png"
            path = OUT / name
            path.write_bytes(render(size, maskable=maskable))
            written.append(f"{name} ({path.stat().st_size} bytes)")
    # iOS ignores the manifest icons and uses apple-touch-icon; it also does not
    # round the corners itself, so this one keeps the plate's own radius.
    (OUT / "apple-touch-icon.png").write_bytes(render(180, maskable=False))
    written.append("apple-touch-icon.png")
    print("\n".join(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
