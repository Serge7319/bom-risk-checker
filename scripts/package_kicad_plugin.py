"""Package the KiCad IPC plugin for the public Cadivor downloads directory."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "integrations" / "kicad-cadivor"
OUTPUT = ROOT / "marketing-web" / "downloads" / "cadivor-kicad-plugin.zip"
FILES = ("README.md", "cadivor_action.py", "plugin.json", "requirements.txt")


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as archive:
        for filename in FILES:
            archive.write(SOURCE / filename, f"kicad-cadivor/{filename}")
    print(f"Created {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
