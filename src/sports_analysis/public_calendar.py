"""Strict publication boundary for the static calendar, with no private or RAW fields."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sports_analysis.domain.events import CycleStatus, Sport
from sports_analysis.domain.temporal import utc
from sports_analysis.providers.browser import public_text
from sports_analysis.storage.raw import canonical_json

SCHEMA = "public_calendar_v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_CYCLES = 5000
TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
FIELDS = frozenset(
    {
        "event_id",
        "event_cycle_id",
        "cycle_number",
        "previous_cycle_id",
        "sport",
        "competition",
        "home",
        "away",
        "scheduled_start_at",
        "actual_start_at",
        "status",
        "tracking_status",
        "last_observed_at",
    }
)


def _time(value: Any, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise ValueError("Invalid public timestamp")
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError("Invalid public timestamp offset")
    return utc(datetime.fromisoformat(value))


def _uuid(value: Any) -> None:
    if (
        not isinstance(value, str)
        or str(UUID(value)) != value
        or UUID(value).version not in range(1, 6)
    ):
        raise ValueError("Invalid public UUID")


def validate_public_calendar(data: Any, *, expected_kind: str | None = None) -> dict[str, Any]:
    """Reject unknown keys rather than stripping potentially private input silently."""
    try:
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "data_kind",
            "generated_at",
            "display_timezone",
            "cycles",
        }:
            raise ValueError
        if (
            data["schema_version"] != SCHEMA
            or data["data_kind"] not in {"PUBLIC", "SYNTHETIC"}
            or (expected_kind and data["data_kind"] != expected_kind)
            or data["display_timezone"] != "America/Lima"
            or not isinstance(data["cycles"], list)
            or len(data["cycles"]) > MAX_CYCLES
        ):
            raise ValueError
        generated = _time(data["generated_at"], nullable=True)
        if data["cycles"] and generated is None:
            raise ValueError
        cycles: dict[str, dict[str, Any]] = {}
        numbers: set[tuple[str, int]] = set()
        for row in data["cycles"]:
            if not isinstance(row, dict) or set(row) != FIELDS:
                raise ValueError
            _uuid(row["event_id"])
            _uuid(row["event_cycle_id"])
            if (
                row["event_cycle_id"] in cycles
                or type(row["cycle_number"]) is not int
                or row["cycle_number"] < 1
            ):
                raise ValueError
            if (row["event_id"], row["cycle_number"]) in numbers:
                raise ValueError
            numbers.add((row["event_id"], row["cycle_number"]))
            Sport(row["sport"])
            CycleStatus(row["status"])
            if row["tracking_status"] not in {None, "ACTIVE", "PAUSED", "CLOSED"}:
                raise ValueError
            for field in ("competition", "home", "away"):
                public_text(row[field])
            _time(row["scheduled_start_at"])
            _time(row["actual_start_at"], nullable=True)
            observed = _time(row["last_observed_at"])
            if generated is None or observed is None or observed > generated:
                raise ValueError
            cycles[row["event_cycle_id"]] = row
        for row in cycles.values():
            if row["cycle_number"] == 1:
                if row["previous_cycle_id"] is not None:
                    raise ValueError
            else:
                _uuid(row["previous_cycle_id"])
                previous = cycles[row["previous_cycle_id"]]
                if (
                    previous["event_id"] != row["event_id"]
                    or previous["cycle_number"] + 1 != row["cycle_number"]
                    or previous["status"] != "POSTPONED"
                ):
                    raise ValueError
        if len(canonical_json(data)) > MAX_BYTES:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError("Invalid public calendar snapshot") from None
    return data


def load_public_calendar(payload: bytes, *, expected_kind: str | None = None) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise ValueError("Public calendar exceeds the publication size limit")
    try:
        data = json.loads(payload)
    except (ValueError, RecursionError):
        raise ValueError("Invalid public calendar JSON") from None
    return validate_public_calendar(data, expected_kind=expected_kind)
