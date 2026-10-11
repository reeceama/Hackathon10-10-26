"""Draws Referee's app icon (Resources/AppIcon.png) from the extension's whistle.

A dark tile with depth, in the style of macOS 26 icons: a top-to-bottom gradient, a soft
light rim along the top edge, and a faint shadow under the whistle.
Run: .venv/bin/python macapp/make_icon.py         (the app icon)
     .venv/bin/python macapp/make_icon.py --extension   (the browser extension's icons)
"""

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
SIZE, TILE, RADIUS = 1024, 824, 185  # Apple's macOS icon grid
SHARE = 0.66                          # how much of the tile's width the whistle spans


def whistle_shape() -> Image.Image:

    """
    The whistle as a greyscale mask, cut from the extension icon.
    """

    src = Image.open(HERE / "Resources/whistle-source.png").convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    mask = Image.new("L", src.size, 0)
    px, pm = src.load(), mask.load()
    for y in range(SIZE):
        for x in range(SIZE):
            r, g, b, a = px[x, y]
            pm[x, y] = int(max(0, min(255, ((r + g + b) / 3 - 120) * 255 / 110)) * a / 255)
    # The old icon's corners, outside its tile, are white too: clear anything joined to the edge.
    solid = mask.point(lambda v: 255 if v > 40 else 0)
    for corner in ((0, 0), (SIZE - 1, 0), (0, SIZE - 1), (SIZE - 1, SIZE - 1)):
        if solid.getpixel(corner):
            ImageDraw.floodfill(solid, corner, 0)
    mask = Image.composite(mask, Image.new("L", mask.size, 0), solid.filter(ImageFilter.MaxFilter(5)))
    return mask.crop(mask.getbbox())


def rounded(box, radius, fill=255) -> Image.Image:

    shape = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(shape).rounded_rectangle(box, radius, fill=fill)
    return shape


def draw(tile_size=TILE, radius=RADIUS, drop_shadow=True) -> Image.Image:

    TILE, RADIUS = tile_size, radius
    edge = (SIZE - TILE) // 2
    box = (edge, edge, edge + TILE, edge + TILE)
    tile_mask = rounded(box, RADIUS)

    # Drop shadow under the tile.
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    if drop_shadow:
        shadow = rounded((edge, edge + 14, edge + TILE, edge + TILE + 14), RADIUS, 120).filter(ImageFilter.GaussianBlur(22))
        icon.putalpha(shadow)

    # Tile: dark graphite at the top, near-black at the bottom.
    gradient = Image.new("RGBA", (SIZE, SIZE))
    draw_gradient = ImageDraw.Draw(gradient)
    top, bottom = (58, 60, 66), (14, 14, 16)
    for y in range(SIZE):
        t = min(1, max(0, (y - edge) / TILE))
        draw_gradient.line([(0, y), (SIZE, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    tile = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tile.paste(gradient, (0, 0), tile_mask)
    icon = Image.alpha_composite(icon, tile)

    # Glass rim: a thin light edge, brightest along the top, fading down the sides.
    rim = ImageChops.subtract(tile_mask, rounded((edge + 6, edge + 6, edge + TILE - 6, edge + TILE - 6), RADIUS - 6))
    fade = Image.new("L", (SIZE, SIZE))
    ImageDraw.Draw(fade).rectangle((0, 0, SIZE, SIZE), fill=0)
    for y in range(SIZE):
        t = max(0.0, 1 - (y - edge) / (TILE * 0.7))
        ImageDraw.Draw(fade).line([(0, y), (SIZE, y)], fill=int(40 + 150 * t))
    rim_layer = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
    rim_layer.putalpha(ImageChops.multiply(rim.filter(ImageFilter.GaussianBlur(1.5)), fade))
    icon = Image.alpha_composite(icon, rim_layer)

    # Whistle, with a faint shadow beneath it.
    shape = whistle_shape()
    width = int(TILE * SHARE)
    shape = shape.resize((width, int(shape.height * width / shape.width)), Image.LANCZOS)
    at = ((SIZE - shape.width) // 2, (SIZE - shape.height) // 2)
    glyph_shadow = Image.new("L", (SIZE, SIZE), 0)
    glyph_shadow.paste(shape, (at[0], at[1] + 12))
    shadow_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow_layer.putalpha(glyph_shadow.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55)))
    icon = Image.alpha_composite(icon, shadow_layer)
    white = Image.new("RGBA", shape.size, (250, 250, 252, 255))
    white.putalpha(shape)
    icon.alpha_composite(white, at)
    return icon


if __name__ == "__main__":
    if "--extension" in sys.argv:
        # Browsers show extension icons as they are, beside other square toolbar icons: the tile
        # fills the whole square, with only slightly rounded corners.
        icon = draw(tile_size=SIZE, radius=110, drop_shadow=False)
        for size in (16, 32, 48, 128):
            out = HERE.parent / "extension" / "icons" / f"icon{size}.png"
            icon.resize((size, size), Image.LANCZOS).save(out)
            print(f"Saved {out}")
    else:
        out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "Resources/AppIcon.png"
        draw().save(out)
        print(f"Saved {out}")
