"""Build a Pages-ready directory from explicit assets, never the repository root."""

from __future__ import annotations

import argparse
from pathlib import Path

from sports_analysis.public_calendar import load_public_calendar
from sports_analysis.storage.raw import canonical_json

try:
    from scripts.package_extension import build as build_extension
except ModuleNotFoundError:
    from package_extension import build as build_extension

ROOT = Path(__file__).resolve().parents[1]
SITE_ASSETS = (
    "index.html",
    "web/styles.css",
    "web/app.mjs",
    "web/core.mjs",
    "web/scanner.mjs",
    "web/icon.svg",
)


def build_site(output: Path, *, snapshot: Path | None = None) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("Site output must be a new directory")
    public = load_public_calendar(
        (snapshot or ROOT / "web/public.json").read_bytes(), expected_kind="PUBLIC"
    )
    demo = load_public_calendar((ROOT / "web/demo.json").read_bytes(), expected_kind="SYNTHETIC")
    assets = [(name, (ROOT / name).read_bytes()) for name in SITE_ASSETS]
    output.mkdir(parents=True)
    for name, payload in assets:
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (output / "web/public.json").write_bytes(canonical_json(public) + b"\n")
    (output / "web/demo.json").write_bytes(canonical_json(demo) + b"\n")
    (output / ".nojekyll").touch()
    build_extension(output / "downloads/sports-capture-extension.zip")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, help="Validated public calendar export only")
    args = parser.parse_args()
    try:
        build_site(args.output, snapshot=args.snapshot)
    except (OSError, ValueError):
        parser.exit(
            1, "Site build failed: check the public snapshot and use a new output directory.\n"
        )
    print("Static site built from approved public assets.")
