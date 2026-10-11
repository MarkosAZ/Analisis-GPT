"""Strict browser capture boundary; page HTML and private fields are rejected."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sports_analysis.domain.events import Sport
from sports_analysis.domain.markets import LineType, MarketLine
from sports_analysis.domain.temporal import AvailableAtSource, TemporalRecord, utc
from sports_analysis.providers.base import ProviderRequest, RawResponse
from sports_analysis.storage.objects import ObjectStore, sha256
from sports_analysis.storage.raw import StoredRawCapture, canonical_json, load_raw

MAX_CAPTURE_BYTES = 16_384
SCHEMA = "browser_capture_v1"
AUTO_SCHEMA = "browser_capture_v2"
NORMALIZER = "browser_normalizer_v1"
MAX_SCAN_BYTES = 4 * 1024 * 1024
_COMMON = {"event_id", "sport"}
_CALENDAR = {
    "competition_id",
    "competition_name",
    "home_id",
    "home_name",
    "away_id",
    "away_name",
    "scheduled_start_at",
    "actual_start_at",
    "status",
}
_ODDS = {"bookmaker", "market", "period", "line_type", "line", "outcomes"}


class CaptureError(ValueError):
    """Safe to display: never includes input contents."""


def _keys(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise CaptureError("Capture fields do not match the public schema")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError("Duplicate JSON field")
        result[key] = value
    return result


def public_text(value: Any, *, identifier: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 100
        or value != value.strip()
        or re.search(r"[<>@\x00-\x1f\x7f]|://|bearer\s|gh[pousr]_", value, re.I)
        or (identifier and re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None)
    ):
        raise CaptureError("Invalid public field")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise CaptureError("Timestamp must include its UTC offset")
    return utc(datetime.fromisoformat(value))


def _decimal(value: Any) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"-?\d{1,6}(?:\.\d{1,4})?", value):
        raise CaptureError("Invalid decimal string")
    return Decimal(value)


@dataclass(frozen=True)
class CalendarRecord:
    event_id: str
    sport: Sport
    competition_id: str
    competition_name: str
    home_id: str
    home_name: str
    away_id: str
    away_name: str
    scheduled_start_at: datetime
    actual_start_at: datetime | None
    status: str


@dataclass(frozen=True)
class OddsRecord:
    event_id: str
    sport: Sport
    bookmaker: str
    market: str
    period: str
    line: MarketLine
    outcomes: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class BrowserCapture:
    capture_id: UUID
    captured_at: datetime
    source_origin: str
    kind: str
    record: CalendarRecord | OddsRecord
    scan_id: UUID | None = None
    reader_version: str | None = None
    profile_id: str | None = None
    profile_version: str | None = None
    profile_hash: str | None = None

    @property
    def schema_version(self) -> str:
        return AUTO_SCHEMA if self.scan_id else SCHEMA

    @property
    def capture_method(self) -> str:
        return "AUTOMATIC_DOM" if self.scan_id else "MANUAL_REVIEW"

    @property
    def normalizer_version(self) -> str:
        return "browser_normalizer_v2" if self.scan_id else NORMALIZER

    @property
    def provider_code(self) -> str:
        # No URLs in RAW object keys. Odds/calendar adapters have separate roles.
        return f"browser_{self.kind.lower()}_{sha256(self.source_origin.encode())[:24]}"


def parse_capture(payload: bytes) -> BrowserCapture:
    """Validate before archiving. Unrecognized fields might carry private data."""
    if not isinstance(payload, bytes) or len(payload) > MAX_CAPTURE_BYTES:
        raise CaptureError("Capture exceeds the public schema size limit")
    try:
        data = json.loads(payload, object_pairs_hook=_unique_pairs)
        automatic = isinstance(data, dict) and data.get("schema_version") == AUTO_SCHEMA
        _keys(
            data,
            {
                "schema_version",
                "capture_id",
                "capture_method",
                "captured_at",
                "source_origin",
                "kind",
                "record",
            }
            | (
                {"scan_id", "reader_version", "profile_id", "profile_version", "profile_hash"}
                if automatic
                else set()
            ),
        )
        if (data["schema_version"], data["capture_method"]) not in {
            (SCHEMA, "MANUAL_REVIEW"),
            (AUTO_SCHEMA, "AUTOMATIC_DOM"),
        }:
            raise CaptureError("Unsupported browser capture schema")
        scan_id = None
        if automatic:
            scan_id = UUID(data["scan_id"])
            if scan_id.version != 4 or str(scan_id) != data["scan_id"]:
                raise CaptureError("Invalid scan identity")
            if data["reader_version"] != "dom_fields_v1":
                raise CaptureError("Unsupported browser reader")
            public_text(data["profile_id"], identifier=True)
            public_text(data["profile_version"], identifier=True)
            if not isinstance(data["profile_hash"], str) or not re.fullmatch(
                r"[a-f0-9]{64}", data["profile_hash"]
            ):
                raise CaptureError("Invalid profile hash")
        identity = UUID(data["capture_id"])
        if identity.version != 4 or str(identity) != data["capture_id"]:
            raise CaptureError("Capture identity must be a canonical UUID v4")
        captured_at = _timestamp(data["captured_at"])
        origin = data["source_origin"]
        if not isinstance(origin, str) or len(origin) > 253:
            raise CaptureError("Invalid public source origin")
        source = urlsplit(origin)
        if (
            source.scheme != "https"
            or not source.hostname
            or "." not in source.hostname
            or source.username
            or source.password
            or source.path
            or source.query
            or source.fragment
            or not re.fullmatch(r"https://[a-z0-9.-]+(?::[0-9]{1,5})?", origin)
            or ".." in source.hostname
            or source.port == 0
        ):
            raise CaptureError("Only a public HTTPS origin is accepted")
        kind = data["kind"]
        if kind not in {"CALENDAR", "ODDS"}:
            raise CaptureError("Unsupported capture kind")
        row = _keys(data["record"], _COMMON | (_CALENDAR if kind == "CALENDAR" else _ODDS))
        event_id = public_text(row["event_id"], identifier=True)
        sport = Sport(row["sport"])
        record: CalendarRecord | OddsRecord
        if kind == "CALENDAR":
            for entity in ("competition", "home", "away"):
                public_text(row[f"{entity}_id"], identifier=True)
                public_text(row[f"{entity}_name"])
            scheduled = _timestamp(row["scheduled_start_at"])
            actual = (
                _timestamp(row["actual_start_at"]) if row["actual_start_at"] is not None else None
            )
            if row["status"] not in {
                "SCHEDULED",
                "IN_PROGRESS",
                "FINISHED",
                "POSTPONED",
                "CANCELLED",
                "ABANDONED",
            }:
                raise CaptureError("Invalid calendar status")
            if row["status"] == "FINISHED" and actual is None:
                raise CaptureError("A finished event requires its actual start")
            if actual is not None and (actual > captured_at or row["status"] == "SCHEDULED"):
                raise CaptureError("Actual start contradicts the observation")
            if row["home_id"] == row["away_id"]:
                raise CaptureError("Participants must be distinct")
            record = CalendarRecord(
                event_id,
                sport,
                row["competition_id"],
                row["competition_name"],
                row["home_id"],
                row["home_name"],
                row["away_id"],
                row["away_name"],
                scheduled,
                actual,
                row["status"],
            )
        else:
            line = MarketLine(
                LineType(row["line_type"]),
                _decimal(row["line"]) if row["line"] is not None else None,
            )
            count = 3 if line.kind == LineType.THREE_WAY else 2
            if not isinstance(row["outcomes"], list) or len(row["outcomes"]) != count:
                raise CaptureError("A complete two-way or three-way market is required")
            outcomes = []
            for outcome in row["outcomes"]:
                item = _keys(outcome, {"code", "decimal_odds"})
                code = public_text(item["code"], identifier=True)
                price = _decimal(item["decimal_odds"])
                if price <= 1:
                    raise CaptureError("Decimal odds must exceed one")
                outcomes.append((code, price))
            if len({code for code, _ in outcomes}) != count:
                raise CaptureError("Duplicate market outcome")
            record = OddsRecord(
                event_id,
                sport,
                public_text(row["bookmaker"]),
                public_text(row["market"], identifier=True),
                public_text(row["period"], identifier=True),
                line,
                tuple(outcomes),
            )
        return BrowserCapture(
            identity,
            captured_at,
            origin,
            kind,
            record,
            scan_id,
            data.get("reader_version"),
            data.get("profile_id"),
            data.get("profile_version"),
            data.get("profile_hash"),
        )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise CaptureError("Invalid public browser capture; review the schema and fields") from None


def raw_response(payload: bytes, received_at: datetime) -> RawResponse:
    capture = parse_capture(payload)
    received = utc(received_at)
    if capture.captured_at > received:
        raise CaptureError("Browser clock is ahead of the receiver; correct it before import")
    return RawResponse(
        capture.provider_code,
        ProviderRequest("browser/import"),
        received,
        capture.reader_version or "browser_extension_v1",
        capture.schema_version,
        payload,
    )


def normalize_capture(
    store: ObjectStore, raw: StoredRawCapture
) -> TemporalRecord[CalendarRecord | OddsRecord]:
    response = load_raw(store, raw)
    capture = parse_capture(response.payload)
    if (
        capture.capture_id != raw.capture_id
        or response.provider != capture.provider_code
        or capture.captured_at > response.fetched_at
        or response.schema_version != capture.schema_version
        or response.adapter_version != (capture.reader_version or "browser_extension_v1")
    ):
        raise CaptureError("RAW provenance does not match the capture")
    return TemporalRecord(
        logical_key=f"{capture.provider_code}:{capture.record.event_id}:{capture.capture_id}",
        revision=1,
        value=capture.record,
        occurred_at=capture.captured_at,
        available_at=response.fetched_at,
        available_at_source=AvailableAtSource.OBSERVED,
    )


def parse_scan(payload: bytes) -> tuple[bytes, ...]:
    """Validate the whole batch first; deterministic member bytes make retries safe."""
    if not isinstance(payload, bytes) or len(payload) > MAX_SCAN_BYTES:
        raise CaptureError("Scan exceeds the size limit")
    try:
        data = _keys(
            json.loads(payload, object_pairs_hook=_unique_pairs),
            {"schema_version", "scan_id", "started_at", "finished_at", "status", "captures"},
        )
        scan_id = UUID(data["scan_id"])
        if (
            data["schema_version"] != "browser_scan_v1"
            or scan_id.version != 4
            or str(scan_id) != data["scan_id"]
            or data["status"]
            not in {"COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "INTERRUPTED"}
            or not isinstance(data["captures"], list)
            or len(data["captures"]) > 200
        ):
            raise CaptureError("Invalid scan envelope")
        start, finish = _timestamp(data["started_at"]), _timestamp(data["finished_at"])
        if finish < start:
            raise CaptureError("Invalid scan interval")
        captures = []
        ids = set()
        for record in data["captures"]:
            raw = canonical_json(record)
            capture = parse_capture(raw)
            if (
                capture.scan_id != scan_id
                or not start <= capture.captured_at <= finish
                or capture.capture_id in ids
            ):
                raise CaptureError("Invalid scan membership")
            ids.add(capture.capture_id)
            captures.append(raw)
        return tuple(captures)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise CaptureError("Invalid public browser scan") from None
