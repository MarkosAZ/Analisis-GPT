import json
from datetime import UTC, datetime

import pytest

from sports_analysis.providers.browser import (
    SOURCE_READERS,
    CaptureError,
    normalize_capture,
    parse_capture,
    parse_scan,
    raw_response,
)
from sports_analysis.storage.objects import LocalObjectStore
from sports_analysis.storage.raw import persist_raw
from tests.browser_fixtures import scan_data, source_data


@pytest.mark.parametrize("reader", SOURCE_READERS)
def test_source_capture_keeps_trusted_receipt_time_and_version(reader, tmp_path):
    data = source_data(reader)
    payload = json.dumps(data).encode()
    capture = parse_capture(payload)
    assert capture.schema_version == "browser_capture_v3"
    assert capture.capture_method == "AUTOMATIC_SOURCE"
    assert capture.normalizer_version == "browser_normalizer_v3"
    received = datetime.now(UTC)
    store = LocalObjectStore(tmp_path)
    raw = persist_raw(store, raw_response(payload, received), capture_id=capture.capture_id)
    assert normalize_capture(store, raw).available_at == received
    assert capture.captured_at < received


@pytest.mark.parametrize(
    "patch",
    [
        {"source_origin": "https://other.example"},
        {"reader_version": "unknown_reader"},
        {"reader_version": "dom_fields_v1"},
        {"profile_version": "2"},
        {"profile_id": "wrong_source"},
        {"capture_method": "AUTOMATIC_DOM"},
        {"schema_version": "browser_capture_v2"},
        {"cookie": "PRIVATE"},
    ],
)
def test_source_identity_cannot_be_relabelled_or_include_private_fields(patch):
    data = source_data()
    data.update(patch)
    with pytest.raises(CaptureError):
        parse_capture(json.dumps(data).encode())


def test_v3_scan_uses_existing_stable_batch_contract():
    batch = scan_data()
    source = source_data()
    source["scan_id"] = batch["scan_id"]
    batch["captures"] = [source]
    members = parse_scan(json.dumps(batch).encode())
    assert members == parse_scan(json.dumps(batch, indent=2).encode())
    assert parse_capture(members[0]).capture_method == "AUTOMATIC_SOURCE"
