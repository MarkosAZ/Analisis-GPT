import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sports_analysis.providers.browser import (
    CaptureError,
    normalize_capture,
    parse_capture,
    parse_scan,
    raw_response,
)
from sports_analysis.storage.objects import LocalObjectStore
from sports_analysis.storage.raw import persist_raw
from tests.browser_fixtures import automatic_data, capture_data, scan_data


def test_auto_raw_preserves_reader_provenance_and_trusted_availability(tmp_path):
    data = automatic_data("ODDS")
    payload = json.dumps(data).encode()
    capture = parse_capture(payload)
    assert capture.capture_method == "AUTOMATIC_DOM"
    assert capture.normalizer_version == "browser_normalizer_v2"
    assert capture.profile_hash == data["profile_hash"]
    received = datetime.now(UTC)
    response = raw_response(payload, received)
    assert response.adapter_version == "dom_fields_v1"
    assert response.schema_version == "browser_capture_v2"
    store = LocalObjectStore(tmp_path)
    raw = persist_raw(store, response, capture_id=capture.capture_id)
    normalized = normalize_capture(store, raw)
    assert normalized.available_at == received
    assert normalized.occurred_at < normalized.available_at
    data["captured_at"] = (received + timedelta(minutes=1)).isoformat()
    with pytest.raises(CaptureError):
        raw_response(json.dumps(data).encode(), received)


@pytest.mark.parametrize(
    "patch",
    [
        {"capture_method": "MANUAL_REVIEW"},
        {"reader_version": "unverified_code"},
        {"profile_hash": "bad"},
        {"scan_id": "not-a-uuid"},
        {"token": "private"},
    ],
)
def test_automatic_capture_rejects_false_or_private_provenance(patch):
    data = automatic_data()
    data.update(patch)
    with pytest.raises(CaptureError):
        parse_capture(json.dumps(data).encode())


def test_manual_capture_remains_compatible():
    capture = parse_capture(json.dumps(capture_data()).encode())
    assert capture.scan_id is None
    assert capture.schema_version == "browser_capture_v1"
    assert capture.capture_method == "MANUAL_REVIEW"
    assert capture.normalizer_version == "browser_normalizer_v1"


def test_scan_members_are_stable_across_envelope_formatting_and_retries():
    data = scan_data()
    compact = parse_scan(json.dumps(data).encode())
    assert compact == parse_scan(json.dumps(data, indent=4).encode())
    assert len(compact) == 1
    assert parse_capture(compact[0]).scan_id is not None


@pytest.mark.parametrize(
    "change", ["duplicate", "wrong_scan", "future", "partial", "private", "manual", "oversized"]
)
def test_scan_rejects_invalid_batch_before_any_import(change):
    data = scan_data()
    if change == "duplicate":
        data["captures"] *= 2
    elif change == "wrong_scan":
        data["captures"][0]["scan_id"] = str(uuid4())
    elif change == "future":
        data["finished_at"] = data["started_at"]
    elif change == "partial":
        data["status"] = "RUNNING"
    elif change == "private":
        data["real_bet"] = True
    elif change == "manual":
        data["captures"] = [capture_data()]
    else:
        data["captures"] *= 201
    with pytest.raises(CaptureError):
        parse_scan(json.dumps(data).encode())
