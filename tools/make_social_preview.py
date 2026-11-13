# -*- coding: utf-8 -*-
"""Draws the GitHub social preview (docs/social-preview.png, 1280x640). Needs Pillow and the Inter font (any .otf/.ttf path below)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIRS = [Path("/usr/share/fonts/opentype/inter"), Path("C:/Windows/Fonts")]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for directory in FONT_DIRS:
        for candidate in (directory / name, directory / "segoeui.ttf"):
            if candidate.is_file():
                return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> None:
    w, h = 1280, 640
    background = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(background)
    for x in range(w):
        f = x / (w - 1)
        draw.line([(x, 0), (x, h)], fill=(round(18 + 30 * f), round(20 + 8 * f), round(40 + 50 * f)))

    icon = Image.open(ROOT / "assets" / "icon.png").convert("RGBA").resize((150, 150), Image.LANCZOS)
    background.paste(icon, (80, 90), icon)
    draw.text((255, 104), "WhisperSRT", font=font("Inter-Bold.otf", 64), fill="white")
    draw.text((258, 184), "Subtitles from audio & video", font=font("Inter-Medium.otf", 26), fill=(190, 198, 255))

    lines = ["Local recognition on faster-whisper", "Translation to 18 languages (NLLB-200)", "SRT, VTT, TXT, JSON, ASS, bilingual"]
    for i, text in enumerate(lines):
        y = 290 + i * 52
        draw.ellipse((84, y + 12, 100, y + 28), fill=(110, 140, 255))
        draw.text((120, y), text, font=font("Inter-Regular.otf", 27), fill=(235, 238, 255))

    chip_font = font("Inter-SemiBold.otf", 24)
    x = 80
    for label in ("Windows", "No cloud", "EN / RU", "MIT"):
        width = int(draw.textlength(label, font=chip_font)) + 40
        draw.rounded_rectangle((x, 520, x + width, 568), radius=24, outline=(140, 160, 255), width=2)
        draw.text((x + 20, 529), label, font=chip_font, fill=(215, 222, 255))
        x += width + 16

    shot = Image.open(ROOT / "docs" / "screenshot-en-dark.png").convert("RGB")
    shot = shot.resize((470, round(560 * shot.height / shot.width)), Image.LANCZOS)
    shadow = Image.new("RGBA", (shot.width + 60, shot.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((30, 40, shot.width + 30, shot.height + 40), radius=18, fill=(0, 0, 0, 150))
    background.paste(shadow, (745, 70), shadow)
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, shot.width - 1, shot.height - 1), radius=16, fill=255)
    background.paste(shot, (775, 100), mask)

    out = ROOT / "docs" / "social-preview.png"
    background.save(out, optimize=True)
    print("saved", out)


if __name__ == "__main__":
    main()
