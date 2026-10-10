from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sports_analysis.domain.temporal import (
    AvailableAtSource,
    FeatureSnapshot,
    TemporalLeakageError,
    TemporalRecord,
    as_of,
    assert_point_in_time,
)

DECISION = datetime(2026, 1, 1, 12, tzinfo=UTC)


def fact(**changes: object) -> TemporalRecord[str]:
    row = TemporalRecord(
        logical_key="lineup:team-a",
        revision=1,
        value="unconfirmed",
        occurred_at=DECISION - timedelta(days=1),
        available_at=DECISION - timedelta(hours=1),
        available_at_source=AvailableAtSource.OBSERVED,
    )
    return replace(row, **changes)


def test_historical_snapshot_uses_revision_known_then_not_latest_today() -> None:
    initial = fact()
    correction = fact(revision=2, value="confirmed", available_at=DECISION + timedelta(minutes=1))
    assert as_of([correction, initial], DECISION).records == (initial,)
    assert as_of([correction, initial], correction.available_at).records == (correction,)


@pytest.mark.parametrize("domain", ["stats", "odds", "news", "injury", "lineup", "weather"])
def test_as_of_rejects_future_information_for_every_feature_domain(domain: str) -> None:
    future = fact(logical_key=domain, available_at=DECISION + timedelta(microseconds=1))
    assert as_of([future], DECISION).records == ()
    with pytest.raises(TemporalLeakageError):
        assert_point_in_time([future], DECISION)
    with pytest.raises(TemporalLeakageError):
        FeatureSnapshot(DECISION, (future,))


def test_scheduled_future_occurrence_is_usable_if_already_known() -> None:
    fixture = fact(occurred_at=DECISION + timedelta(days=7))
    assert as_of([fixture], DECISION).records == (fixture,)


def test_boundary_available_at_equals_decision_time_is_visible() -> None:
    row = fact(available_at=DECISION)
    assert as_of([row], DECISION).records == (row,)


def test_utc_normalization_and_naive_timestamp_rejection() -> None:
    lima = DECISION.astimezone(timezone(timedelta(hours=-5)))
    row = fact(available_at=lima)
    assert row.available_at.tzinfo is UTC
    assert as_of([row], lima).records == (row,)
    with pytest.raises(ValueError, match="timezone-aware"):
        fact(available_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        as_of([], datetime(2026, 1, 1))


def test_revision_duplicate_delivery_is_idempotent_but_conflicts_fail() -> None:
    row = fact()
    assert as_of([row, row], DECISION).records == (row,)
    with pytest.raises(ValueError, match="conflicting"):
        as_of([row, fact(value="changed without new revision")], DECISION)


def test_correction_cannot_backdate_availability() -> None:
    with pytest.raises(ValueError, match="backdate"):
        as_of([fact(), fact(revision=2, available_at=DECISION - timedelta(days=1))], DECISION)


def test_identical_prices_in_distinct_captures_are_preserved() -> None:
    first = fact(logical_key="capture:1", value="2.0")
    second = fact(logical_key="capture:2", value="2.0", available_at=DECISION)
    assert len(as_of([first, second], DECISION).records) == 2


def test_estimated_provenance_is_reported_and_records_are_frozen() -> None:
    observed = fact()
    estimated = fact(logical_key="historical", available_at_source=AvailableAtSource.ESTIMATED)
    assert as_of([observed, estimated], DECISION).estimated_fraction == 0.5
    assert as_of([], DECISION).estimated_fraction == 0.0
    with pytest.raises(FrozenInstanceError):
        observed.available_at = DECISION


@pytest.mark.parametrize("payload", [{"goals": 1}, [1], ("immutable", [1])])
def test_mutable_payload_cannot_rewrite_a_historical_snapshot(payload: object) -> None:
    with pytest.raises(ValueError, match="recursively immutable"):
        fact(value=payload)


def test_frozen_payload_also_requires_immutable_nested_fields() -> None:
    @dataclass(frozen=True)
    class MutableField:
        goals: list[int]

    @dataclass(frozen=True)
    class ImmutableField:
        goals: tuple[int, ...]

    with pytest.raises(ValueError, match="recursively immutable"):
        fact(value=MutableField([1]))
    record = fact(value=ImmutableField((1,)))
    assert as_of([record], DECISION).records == (record,)
