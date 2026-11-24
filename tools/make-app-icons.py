"""DMD Mining's icons: the DebitMyData apps' icon (the DMD coin with a red badge at the bottom right,
as the pool's and DMD Stats' are), with a white flame in the badge. Needs Pillow, numpy and
rsvg-convert (librsvg2-bin).

    python3 tools/make-app-icons.py <an app's web/images/app folder> web/images/app [glyph]

The source folder is any DebitMyData app's icons (the pool's, or DMD Stats' web/images/app): their
badge is drawn again in red, with the glyph inside. Glyphs: flame (the default), trophy, globe,
hammer. It writes the app icons (192, 512, 1024, the maskable ones for Android, the iPhone one),
the notifications' badge (badge-96.png: the glyph alone, white), the top bar's badge
(web/images/dmd-mining-25/50/75.png) and web/favicon.ico (the whole icon, for the browser's tab).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

RED = (200, 8, 21, 255)
# Each glyph in a 24×24 box, white; drawn at the badge's centre.
GLYPHS = {
    "flame": (
        '<path fill="#fff" fill-rule="evenodd" d="M12 1.6C13.6 4.6 19.4 8.6 19.4 14.4A7.4 7.4 0 0 1 4.6 '
        "14.4C4.6 11.2 6.2 8.8 7.9 7.3 7.8 9.6 8.9 11.2 10.3 11.8 9.9 8.2 10.8 4.6 12 1.6ZM12.3 12.9C12.6 "
        '14.6 15.3 15.9 15.3 18.1A3.3 3.3 0 0 1 8.7 18.1C8.7 16.7 9.5 15.6 10.4 15 10.4 16 10.9 16.7 '
        '11.6 17 11.4 15.6 11.7 14.2 12.3 12.9Z"/>'
    ),
    "trophy": (
        '<g fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 3.5h10v5a5 5 0 0 1-10 0z" fill="#fff"/><path d="M7 5.5H4.5a3 3 0 0 0 3 4"/>'
        '<path d="M17 5.5h2.5a3 3 0 0 1-3 4"/><path d="M12 13.5v4M8 20.5h8M9.5 17.5h5"/></g>'
    ),
    "globe": (
        '<g fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="8.6"/>'
        '<path d="M3.6 12h16.8M12 3.4c2.6 2.4 3.9 5.3 3.9 8.6s-1.3 6.2-3.9 8.6c-2.6-2.4-3.9-5.3-3.9-8.6s1.3-6.2 3.9-8.6z"/>'
        "</g>"
    ),
    "hammer": (
        '<g fill="#fff" transform="rotate(-42 12 12)"><rect x="10.9" y="8.5" width="2.6" height="14" rx="1.2"/>'
        '<path d="M5.2 3.6h10.3l3.3 2.9v2.6h-3.2l-1.3-1.5H5.2A2 2 0 0 1 3.2 5.6 2 2 0 0 1 5.2 3.6z"/></g>'
    ),
}

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
GLYPH = sys.argv[3] if len(sys.argv) > 3 else "flame"
OUT.mkdir(parents=True, exist_ok=True)


def glyph(size: int) -> Image.Image:
    """The glyph, white on transparent, `size` pixels square."""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{GLYPHS[GLYPH]}</svg>'
    with tempfile.TemporaryDirectory() as work:
        src, png = Path(work) / "g.svg", Path(work) / "g.png"
        src.write_text(svg)
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(src), "-o", str(png)], check=True)
        return Image.open(png).convert("RGBA")


def badge_geometry(im: Image.Image) -> tuple[float, float, float]:
    a = np.array(im.convert("RGBA")).astype(int)
    red = (a[..., 0] > 180) & (a[..., 1] < 40) & (a[..., 2] < 50) & (a[..., 3] > 200)
    ys, xs = np.nonzero(red)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    return (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2


def badge(draw_on: Image.Image, cx: float, cy: float, r: float, scale: int, fill: float = 0.66) -> None:
    d = ImageDraw.Draw(draw_on)
    rr = (r + 1.0) * scale
    d.ellipse([cx * scale - rr, cy * scale - rr, cx * scale + rr, cy * scale + rr], fill=RED)
    size = max(4, round(2 * r * fill * scale))
    g = glyph(size)
    draw_on.alpha_composite(g, (round(cx * scale - size / 2), round(cy * scale - size / 2)))


def rebadge(name: str) -> None:
    im = Image.open(SRC / name).convert("RGBA")
    cx, cy, r = badge_geometry(im)
    S = 4
    big = im.resize((im.width * S, im.height * S), Image.LANCZOS)
    badge(big, cx, cy, r, S)
    big.resize(im.size, Image.LANCZOS).save(OUT / name, optimize=True)


for name in ["icon-192.png", "icon-512.png", "icon-1024.png", "icon-maskable-512.png",
             "icon-maskable-1024.png", "apple-touch-icon.png"]:  # fmt: skip
    rebadge(name)

# The notifications' badge (Android's status bar): the glyph alone, white.
glyph(96).save(OUT / "badge-96.png", optimize=True)

# The top bar's brand: the badge alone (25, 50, 75 px).
for size in (25, 50, 75):
    S = 8
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    badge(im, size / 2, size / 2, size / 2 * 0.98 - 1 / S, S, 0.7)
    im.resize((size, size), Image.LANCZOS).save(OUT.parent / f"dmd-mining-{size}.png", optimize=True)

# The favicon (the browser's tab): the whole icon, the coin with its badge, as the pool's.
Image.open(OUT / "icon-512.png").convert("RGBA").save(
    OUT.parent.parent / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
)
print("ok:", GLYPH)
