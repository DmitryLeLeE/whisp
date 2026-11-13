"""Write version_info.txt: the "Details" tab of WhisperSRT.exe (version, author, description).

The version is read from whisper_universal.py, so it is written in one place only.
Usage: python tools/make_version_info.py [output file]
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_version() -> str:
    text = (ROOT / "whisper_universal.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"(\d+(?:\.\d+){1,3})"', text, re.MULTILINE)
    if not match:
        raise SystemExit("__version__ not found in whisper_universal.py")
    return match.group(1)


def render(version: str) -> str:
    parts = [int(p) for p in version.split(".")]
    parts += [0] * (4 - len(parts))
    numbers = tuple(parts[:4])
    dotted = ".".join(str(p) for p in numbers)
    strings = [
        ("CompanyName", "DmitryLeLeE"),
        ("FileDescription", "WhisperSRT: subtitles with faster-whisper"),
        ("FileVersion", dotted),
        ("InternalName", "WhisperSRT"),
        ("LegalCopyright", "MIT License. Copyright (c) 2026 DmitryLeLeE"),
        ("OriginalFilename", "WhisperSRT.exe"),
        ("ProductName", "WhisperSRT"),
        ("ProductVersion", dotted),
    ]
    rows = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [{rows}])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "version_info.txt"
    out.write_text(render(read_version()), encoding="utf-8")
    print(f"Wrote {out} (version {read_version()})")


if __name__ == "__main__":
    main()
