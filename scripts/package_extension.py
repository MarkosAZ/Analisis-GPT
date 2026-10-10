"""Build a deterministic unpacked-extension ZIP from a fixed asset allowlist."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ASSETS = (
    "manifest.json",
    "background.js",
    "core.mjs",
    "picker.mjs",
    "panel.html",
    "panel.css",
    "panel.mjs",
    "README.md",
)


def build(output: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "extension"
    contents = [(name, (root / name).read_bytes()) for name in ASSETS]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle, ZipFile(handle, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in contents:
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output)
