# -*- coding: utf-8 -*-
"""Draws the program icon (assets/icon.png and assets/icon.ico). Run: python tools/make_icon.py (needs Pillow)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024  # drawn large, then scaled down for smooth edges
ASSETS = Path(__file__).resolve().parent.parent / "assets"


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * f) for x, y in zip(a, b))  # type: ignore[return-value]


def draw() -> Image.Image:
    top, bottom = (63, 94, 251), (110, 52, 214)
    gradient = Image.new("RGB", (SIZE, SIZE))
    pixels = ImageDraw.Draw(gradient)
    for y in range(SIZE):
        pixels.line([(0, y), (SIZE, y)], fill=lerp(top, bottom, y / (SIZE - 1)))

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=int(SIZE * 0.22), fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), mask)

    d = ImageDraw.Draw(icon)
    white = (255, 255, 255, 255)
    soft = (255, 255, 255, 190)

    # sound waveform (speech) on top
    center_y = int(SIZE * 0.32)
    heights = [0.07, 0.14, 0.22, 0.11, 0.18, 0.09, 0.15]
    bar_w, gap = int(SIZE * 0.06), int(SIZE * 0.04)
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (SIZE - total) // 2
    for h in heights:
        half = int(SIZE * h)
        d.rounded_rectangle((x, center_y - half, x + bar_w, center_y + half), radius=bar_w // 2, fill=white)
        x += bar_w + gap

    # subtitle lines below
    left, right = int(SIZE * 0.2), int(SIZE * 0.8)
    line_h = int(SIZE * 0.07)
    y1 = int(SIZE * 0.58)
    d.rounded_rectangle((left, y1, right, y1 + line_h), radius=line_h // 2, fill=white)
    y2 = y1 + line_h + int(SIZE * 0.06)
    d.rounded_rectangle((left + int(SIZE * 0.12), y2, right - int(SIZE * 0.12), y2 + line_h), radius=line_h // 2, fill=soft)
    return icon


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = draw()
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(ASSETS / "icon.ico", sizes=sizes)
    print("saved", ASSETS / "icon.png", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
