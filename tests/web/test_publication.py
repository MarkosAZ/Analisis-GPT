import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.build_site import SITE_ASSETS, build_site
from scripts.package_extension import ASSETS
from sports_analysis.public_calendar import load_public_calendar, validate_public_calendar

ROOT = Path(__file__).resolve().parents[2]


def demo():
    return json.loads((ROOT / "web/demo.json").read_bytes())


def test_build_contains_only_allowlisted_site_and_extension_assets(tmp_path):
    output = tmp_path / "site"
    build_site(output)
    names = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
    assert names == set(SITE_ASSETS) | {
        "web/public.json",
        "web/demo.json",
        ".nojekyll",
        "downloads/sports-capture-extension.zip",
    }
    assert load_public_calendar((output / "web/public.json").read_bytes())["cycles"] == []
    with ZipFile(output / "downloads/sports-capture-extension.zip") as archive:
        assert set(archive.namelist()) == set(ASSETS)
    with pytest.raises(ValueError):
        build_site(output)


@pytest.mark.parametrize("key", ["real_bet", "stake", "token", "raw_refs", "source_origin"])
def test_public_contract_rejects_extra_fields_before_publication(key):
    data = demo()
    data["cycles"][0][key] = "not-public"
    with pytest.raises(ValueError):
        validate_public_calendar(data)


def test_builder_rejects_demo_in_public_slot_and_private_snapshot(tmp_path):
    with pytest.raises(ValueError):
        build_site(tmp_path / "synthetic", snapshot=ROOT / "web/demo.json")
    source = tmp_path / "snapshot.json"
    data = demo()
    data["data_kind"] = "PUBLIC"
    data["cycles"][0]["real_bet"] = True
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        build_site(tmp_path / "private", snapshot=source)
    assert not (tmp_path / "private").exists()


def test_dates_chains_and_uuid_invariants():
    valid = demo()
    validate_public_calendar(valid)
    invalid = demo()
    invalid["cycles"].pop(0)
    with pytest.raises(ValueError):
        validate_public_calendar(invalid)
    invalid = demo()
    invalid["cycles"][0]["last_observed_at"] = "2031-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        validate_public_calendar(invalid)
    with pytest.raises(ValueError):
        load_public_calendar(b" " * (2 * 1024 * 1024 + 1))


@pytest.mark.parametrize(
    "timestamp",
    [
        "2030-06-14T18:00Z",
        "2030-06-14T18:00:00+00:60",
        "2030-02-30T18:00:00Z",
        "2030-06-14T18:00:00.1234567Z",
    ],
)
def test_builder_rejects_timestamps_the_browser_cannot_accept(timestamp):
    data = demo()
    data["generated_at"] = timestamp
    with pytest.raises(ValueError):
        validate_public_calendar(data)
