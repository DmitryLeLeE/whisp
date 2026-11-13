# -*- coding: utf-8 -*-
"""Checks the translation tables: same keys and placeholders in Russian and English, and every key used in the code exists.

Run: python tests/check_i18n.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402

SOURCES = ["whisper_universal.py", "WhisperSRT_GUI.py", "translator.py", "hub.py"]
KEY = re.compile(r'"((?:ui|log|err|help|lang|stream)\.[a-z_0-9.{}]+)"')
DYNAMIC = {
    "lang.{code}": [f"lang.{c}" for c in i18n._NATIVE],
    "ui.mode.{code}": ["ui.mode.transcribe", "ui.mode.translate", "ui.mode.mt"],
    "ui.device.{code}": ["ui.device.auto", "ui.device.cpu"],
    "ui.variant.{variant}": ["ui.variant.original", "ui.variant.translated", "ui.variant.bilingual"],
    "ui.model.{self.model_state}": ["ui.model.checking", "ui.model.cached", "ui.model.missing"],
    "ui.mt.{self.mt_state}": ["ui.mt.checking", "ui.mt.cached", "ui.mt.missing"],
}


def main() -> int:
    problems = list(i18n.check_parity())
    used: set[str] = set()
    for name in SOURCES:
        text = (ROOT / name).read_text(encoding="utf-8")
        for key in KEY.findall(text):
            used.update(DYNAMIC.get(key, [key]))
    for key in sorted(used):
        if key not in i18n.RU:
            problems.append(f"{key}: used in the code but missing from the tables")
    unused = sorted(set(i18n.RU) - used)
    if problems:
        print("\n".join(problems))
        return 1
    print(f"OK: {len(i18n.RU)} strings, {len(used)} keys used" + (f"; unused: {len(unused)}" if unused else ""))
    if unused:
        print("unused keys:", ", ".join(unused))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
