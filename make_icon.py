#!/usr/bin/env python3
"""Generates the application icons (run once; requires Pillow).

Writes assets/icon.png (256x256, used in development) and the full set of
sizes for the hicolor icon theme into assets/icons/.
"""

import os

from PIL import Image, ImageDraw

SIZES = [16, 22, 24, 32, 48, 64, 128, 256]
TOP = (229, 57, 53)
BOTTOM = (141, 25, 26)


def render(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Vertical gradient background
    grad = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        c = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)
        gd.line([(0, y), (size, y)], fill=c)

    # Rounded-square mask
    margin = max(1, size // 32)
    radius = max(2, size // 4)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [margin, margin, size - margin, size - margin], radius=radius, fill=255
    )
    img.paste(grad, (0, 0), mask)

    # Download arrow (proportional)
    d = ImageDraw.Draw(img)
    cx = size // 2
    u = size / 256  # scale unit
    d.rectangle([cx - 22 * u, 52 * u, cx + 22 * u, 132 * u], fill="white")
    d.polygon(
        [(cx - 52 * u, 128 * u), (cx + 52 * u, 128 * u), (cx, 184 * u)],
        fill="white",
    )
    d.rounded_rectangle(
        [cx - 52 * u, 196 * u, cx + 52 * u, 216 * u], radius=10 * u, fill="white"
    )
    return img


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    base = render(256)
    out = os.path.join(root, "assets", "icon.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    base.save(out)
    print(f"Wrote {out}")

    icons_dir = os.path.join(root, "assets", "icons")
    os.makedirs(icons_dir, exist_ok=True)
    for size in SIZES:
        img = base.resize((size, size), Image.LANCZOS) if size != 256 else base
        path = os.path.join(icons_dir, f"{size}.png")
        img.save(path)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()