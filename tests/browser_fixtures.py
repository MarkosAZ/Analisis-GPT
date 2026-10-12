"""Synthetic public capture examples; never a saved page or real bet."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sports_analysis.providers.browser import SOURCE_READERS


def capture_data(kind="CALENDAR"):
    record = (
        {
            "event_id": "fixture-1",
            "sport": "FOOTBALL",
            "competition_id": "league-1",
            "competition_name": "Fixture League",
            "home_id": "team-1",
            "home_name": "North FC",
            "away_id": "team-2",
            "away_name": "South FC",
            "scheduled_start_at": "2040-06-15T20:00:00-05:00",
            "actual_start_at": None,
            "status": "SCHEDULED",
        }
        if kind == "CALENDAR"
        else {
            "event_id": "fixture-1",
            "sport": "FOOTBALL",
            "bookmaker": "Fixture bookmaker",
            "market": "TOTAL_GOALS",
            "period": "FULL_TIME",
            "line_type": "HALF_LINE",
            "line": "2.5",
            "outcomes": [
                {"code": "OVER", "decimal_odds": "1.90"},
                {"code": "UNDER", "decimal_odds": "2.00"},
            ],
        }
    )
    return {
        "schema_version": "browser_capture_v1",
        "capture_id": str(uuid4()),
        "capture_method": "MANUAL_REVIEW",
        "captured_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "source_origin": f"https://fixture-{uuid4().hex}.example",
        "kind": kind,
        "record": record,
    }


def automatic_data(kind="CALENDAR"):
    data = capture_data(kind)
    data.update(
        {
            "schema_version": "browser_capture_v2",
            "capture_method": "AUTOMATIC_DOM",
            "scan_id": str(uuid4()),
            "reader_version": "dom_fields_v1",
            "profile_id": "fixture",
            "profile_version": "1",
            "profile_hash": "a" * 64,
        }
    )
    return data


def scan_data():
    capture = automatic_data()
    observed = datetime.fromisoformat(capture["captured_at"])
    return {
        "schema_version": "browser_scan_v1",
        "scan_id": capture["scan_id"],
        "started_at": (observed - timedelta(seconds=1)).isoformat(),
        "finished_at": (observed + timedelta(seconds=1)).isoformat(),
        "status": "COMPLETED",
        "captures": [capture],
    }


def source_data(reader="sofascore_calendar_v1"):
    profile, origin, kind = SOURCE_READERS[reader]
    data = automatic_data(kind)
    data.update(
        schema_version="browser_capture_v3",
        capture_method="AUTOMATIC_SOURCE",
        reader_version=reader,
        profile_id=profile,
        profile_version="1",
        source_origin=origin,
    )
    return data
