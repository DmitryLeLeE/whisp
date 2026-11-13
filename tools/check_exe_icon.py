"""Check that an .exe carries the WhisperSRT icon: its icon sizes must match assets/icon.ico.

Usage: python tools/check_exe_icon.py dist\\WhisperSRT.exe
Needs pefile, which PyInstaller installs on Windows.
"""
import struct
import sys
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
RT_GROUP_ICON = pefile.RESOURCE_TYPE["RT_GROUP_ICON"]


def icon_sizes(data: bytes, entry_size: int) -> set:
    """Sizes listed in an ICONDIR header (an .ico file or an RT_GROUP_ICON resource)."""
    count = struct.unpack_from("<H", data, 4)[0]
    sizes = set()
    for index in range(count):
        width, height = struct.unpack_from("BB", data, 6 + index * entry_size)
        sizes.add((width or 256, height or 256))
    return sizes


def exe_icon_groups(path: Path) -> list:
    pe = pefile.PE(str(path))
    groups = []
    resources = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    for kind in (resources.entries if resources else []):
        if kind.id != RT_GROUP_ICON:
            continue
        for item in kind.directory.entries:
            for lang in item.directory.entries:
                leaf = lang.data.struct
                data = pe.get_data(leaf.OffsetToData, leaf.Size)
                groups.append(icon_sizes(data, 14))
    pe.close()
    return groups


def main() -> int:
    exe = Path(sys.argv[1])
    expected = icon_sizes((ROOT / "assets" / "icon.ico").read_bytes(), 16)
    groups = exe_icon_groups(exe)
    print(f"{exe.name}: {len(groups)} icon group(s)")
    for sizes in groups:
        print("  sizes:", ", ".join(f"{w}x{h}" for w, h in sorted(sizes)))
    print("expected:", ", ".join(f"{w}x{h}" for w, h in sorted(expected)))
    if expected in groups:
        print("OK: the exe carries the WhisperSRT icon")
        return 0
    print("WARNING: no icon group in the exe matches assets/icon.ico")
    return 1


if __name__ == "__main__":
    sys.exit(main())
