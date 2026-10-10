import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from sports_analysis.domain.markets import LineType
from sports_analysis.domain.temporal import as_of
from sports_analysis.providers.browser import (
    CaptureError,
    normalize_capture,
    parse_capture,
    raw_response,
)
from sports_analysis.storage.objects import LocalObjectStore
from sports_analysis.storage.raw import persist_raw
from tests.browser_fixtures import capture_data


@pytest.mark.parametrize("kind", ["CALENDAR", "ODDS"])
def test_browser_raw_before_normalization_and_trusted_availability(tmp_path, kind):
    data = capture_data(kind)
    received = datetime.now(UTC)
    raw = raw_response(json.dumps(data).encode(), received)
    store = LocalObjectStore(tmp_path)
    persisted = persist_raw(store, raw, capture_id=UUID(data["capture_id"]))
    record = normalize_capture(store, persisted)
    assert record.available_at == received
    assert record.occurred_at < received
    assert not as_of([record], received - timedelta(microseconds=1)).records
    assert len(as_of([record], received).records) == 1
    with pytest.raises(CaptureError):
        normalize_capture(store, persist_raw(store, raw, capture_id=uuid4()))


@pytest.mark.parametrize(
    "field,value",
    [
        ("cookie", "private"),
        ("stake", "50"),
        ("real_bet", True),
        ("html", "<html>private</html>"),
        ("available_at", "2000-01-01T00:00:00Z"),
    ],
)
def test_private_and_backdated_fields_rejected_before_raw(field, value):
    data = capture_data()
    data[field] = value
    with pytest.raises(CaptureError, match="Invalid public"):
        parse_capture(json.dumps(data).encode())


@pytest.mark.parametrize(
    "origin",
    [
        "http://fixture.example",
        "https://fixture.example/account",
        "https://fixture.example?token=x",
        "https://fixture.example#private",
        "https://u:p@fixture.example",
        "https://fixture.example/",
    ],
)
def test_only_origin_is_accepted(origin):
    data = capture_data()
    data["source_origin"] = origin
    with pytest.raises(CaptureError):
        parse_capture(json.dumps(data).encode())


@pytest.mark.parametrize(
    "kind,line",
    [
        ("HALF_LINE", "2.5"),
        ("INTEGER_PUSH", "3"),
        ("ASIAN_QUARTER", "2.25"),
        ("ASIAN_QUARTER", "-1.75"),
    ],
)
def test_all_line_types_are_retained_without_selecting_push_lines(kind, line):
    data = capture_data("ODDS")
    data["record"].update(line_type=kind, line=line)
    record = parse_capture(json.dumps(data).encode()).record
    assert record.line.kind == LineType(kind)
    assert record.line.eligible_v1 == (kind == "HALF_LINE")


@pytest.mark.parametrize(
    "patch",
    [
        {"line_type": "HALF_LINE", "line": "2.25"},
        {"line_type": "MONEYLINE", "line": "0"},
        {
            "outcomes": [
                {"code": "OVER", "decimal_odds": "NaN"},
                {"code": "UNDER", "decimal_odds": "2"},
            ]
        },
        {"outcomes": [{"code": "OVER", "decimal_odds": "1.90"}]},
        {
            "outcomes": [
                {"code": "OVER", "decimal_odds": "1.90"},
                {"code": "OVER", "decimal_odds": "2"},
            ]
        },
    ],
)
def test_invalid_or_incomplete_markets_rejected(patch):
    data = capture_data("ODDS")
    data["record"].update(patch)
    with pytest.raises(CaptureError):
        parse_capture(json.dumps(data).encode())


def test_future_clock_rejected_and_errors_sanitized():
    data = capture_data()
    data["captured_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(CaptureError, match="clock"):
        raw_response(json.dumps(data).encode(), datetime.now(UTC))
    data["record"]["home_name"] = "private@example.test"
    with pytest.raises(CaptureError) as error:
        parse_capture(json.dumps(data).encode())
    assert "private@" not in str(error.value)


def test_duplicate_keys_large_payload_invalid_dates_and_nested_private_fields():
    with pytest.raises(CaptureError):
        parse_capture(b'{"kind":"ODDS","kind":"CALENDAR"}')
    with pytest.raises(CaptureError):
        parse_capture(b" " * 16385)
    data = capture_data()
    data["record"]["scheduled_start_at"] = "2030-02-30T00:00:00Z"
    with pytest.raises(CaptureError):
        parse_capture(json.dumps(data).encode())
    data = capture_data("ODDS")
    data["record"]["outcomes"][0]["stake"] = 50
    with pytest.raises(CaptureError):
        parse_capture(json.dumps(data).encode())
