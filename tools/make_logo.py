"""Generate the League of Kiffance logo (assets/logo.png + logo.ico).

The logo is code, not a mystery binary: re-run this to regenerate at any size
or to tweak the design. Original artwork in a hextech-flavoured style — it
deliberately does NOT reproduce Riot's marks (see assets/README.md).

Design: angular hexagonal frame with corner cuts (concept F) around a faceted
smirking face (concept G).

Run: .venv\\Scripts\\python tools\\make_logo.py
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ASSETS = Path(__file__).resolve().parent.parent / "kiffance" / "assets"

GOLD = (200, 170, 110, 255)  # #c8aa6e
GOLD_DARK = (120, 90, 40, 255)  # #785a28
INK = (30, 35, 40, 255)  # #1e2328

# Design space: 156x156, centred on (78, 72).
CENTRE = (78.0, 72.0)
HEX = [(78, 2), (142, 38), (142, 106), (78, 142), (14, 106), (14, 38)]
FACE = [
    [(56, 62), (72, 57), (69, 70)],  # left eye
    [(100, 62), (84, 57), (87, 70)],  # right eye
    [(58, 88), (78, 102), (98, 85), (104, 93), (78, 112), (53, 95)],  # smirk
]
CUTS = [
    [(78, 0), (93, 9), (78, 18), (63, 9)],  # top gem
    [(78, 144), (93, 135), (78, 126), (63, 135)],  # bottom gem
]


def scaled(points, factor):
    """Scale a polygon about the design centre."""
    cx, cy = CENTRE
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in points]


def draw_logo(size: int, supersample: int = 8) -> Image.Image:
    """Render at high resolution and downsample — PIL polygons are aliased."""
    big = size * supersample
    scale = big / 156.0
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def poly(points, colour, factor=1.0):
        draw.polygon([(x * scale, y * scale) for x, y in scaled(points, factor)], fill=colour)

    poly(HEX, GOLD)  # outer gold body
    poly(HEX, INK, 0.90)  # hollow it out -> gold rim
    poly(HEX, GOLD_DARK, 0.84)  # thin inner accent ring
    poly(HEX, INK, 0.80)
    for shape in FACE:
        poly(shape, GOLD)
    for cut in CUTS:
        poly(cut, GOLD)

    return img.resize((size, size), Image.LANCZOS)


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    png = ASSETS / "logo.png"
    draw_logo(512).save(png)
    print(f"wrote {png} (512x512)")

    ico = ASSETS / "logo.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw_logo(256).save(ico, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {ico} ({', '.join(f'{s}px' for s in sizes)})")

    # Contact sheet so the small sizes can be eyeballed.
    preview = Image.new("RGBA", (560, 300), (16, 20, 26, 255))
    x = 20
    for s in (256, 128, 64, 32, 16):
        preview.alpha_composite(draw_logo(s), (x, 20 + (256 - s) // 2))
        x += s + 20
    out = ASSETS / "logo_preview.png"
    preview.save(out)
    print(f"wrote {out} (size comparison)")


if __name__ == "__main__":
    main()
