"""Point-in-time boundaries shared by every feature and historical dataset."""

from collections.abc import Iterable
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from uuid import UUID


class AvailableAtSource(StrEnum):
    OBSERVED = "OBSERVED"
    ESTIMATED = "ESTIMATED"


class TemporalLeakageError(ValueError):
    """An input was unavailable when the decision was made."""


def utc(value: datetime, name: str = "timestamp") -> datetime:
    """Reject ambiguous naive timestamps and normalize aware timestamps to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_immutable(value: object) -> None:
    """Reject payload aliases that could silently rewrite a historical snapshot.

    Normalizers use scalar values, tuples/frozensets or frozen dataclasses with
    recursively immutable fields. Mutable mappings must be normalized first.
    """
    if value is None or isinstance(
        value, (str, bytes, int, float, Decimal, UUID, date, time, timedelta)
    ):
        return
    if isinstance(value, Enum):
        _require_immutable(value.value)
        return
    if isinstance(value, (tuple, frozenset)):
        for item in value:
            _require_immutable(item)
        return
    parameters = getattr(type(value), "__dataclass_params__", None)
    if is_dataclass(value) and not isinstance(value, type) and parameters and parameters.frozen:
        for field in fields(value):
            _require_immutable(getattr(value, field.name))
        return
    raise ValueError("temporal payloads must be recursively immutable")


@dataclass(frozen=True, slots=True)
class TemporalRecord[T]:
    """An append-only revision with a recursively immutable payload.

    ``logical_key`` identifies a fact, not a provider's entire history. Distinct
    observations (including unchanged odds captures) need distinct keys.
    ``occurred_at`` may be in the future, for example a scheduled fixture.
    Only ``available_at`` controls visibility; corrected facts are new revisions.
    """

    logical_key: str
    revision: int
    value: T
    occurred_at: datetime
    available_at: datetime
    available_at_source: AvailableAtSource

    def __post_init__(self) -> None:
        if not self.logical_key or self.revision < 1:
            raise ValueError("a nonempty logical_key and positive revision are required")
        if not isinstance(self.available_at_source, AvailableAtSource):
            raise ValueError("available_at_source must be OBSERVED or ESTIMATED")
        _require_immutable(self.value)
        object.__setattr__(self, "occurred_at", utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "available_at", utc(self.available_at, "available_at"))


def assert_point_in_time[T](records: Iterable[TemporalRecord[T]], decision_time: datetime) -> None:
    cutoff = utc(decision_time, "decision_time")
    if any(record.available_at > cutoff for record in records):
        raise TemporalLeakageError("feature input available_at exceeds decision_time")


@dataclass(frozen=True, slots=True)
class FeatureSnapshot[T]:
    decision_time: datetime
    records: tuple[TemporalRecord[T], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_time", utc(self.decision_time, "decision_time"))
        object.__setattr__(self, "records", tuple(self.records))
        assert_point_in_time(self.records, self.decision_time)
        if len({record.logical_key for record in self.records}) != len(self.records):
            raise ValueError("a feature snapshot must contain one revision per logical fact")

    @property
    def estimated_fraction(self) -> float:
        if not self.records:
            return 0.0
        estimated = sum(
            record.available_at_source == AvailableAtSource.ESTIMATED for record in self.records
        )
        return estimated / len(self.records)


def as_of[T](records: Iterable[TemporalRecord[T]], decision_time: datetime) -> FeatureSnapshot[T]:
    """Select the latest revision that was available, never today's corrected row.

    Duplicate delivery of an identical revision is idempotent. Conflicting
    revisions and availability timestamps that go backwards fail closed.
    """
    cutoff = utc(decision_time, "decision_time")
    versions: dict[str, dict[int, TemporalRecord[T]]] = {}
    for record in records:
        by_revision = versions.setdefault(record.logical_key, {})
        previous = by_revision.get(record.revision)
        if previous is not None and previous != record:
            raise ValueError("conflicting copies of the same logical revision")
        by_revision[record.revision] = record

    selected: list[TemporalRecord[T]] = []
    for logical_key in sorted(versions):
        revisions = sorted(versions[logical_key].values(), key=lambda row: row.revision)
        previous_available_at: datetime | None = None
        visible: TemporalRecord[T] | None = None
        for record in revisions:
            if previous_available_at is not None and record.available_at < previous_available_at:
                raise ValueError(
                    "a correction cannot backdate availability before its prior revision"
                )
            previous_available_at = record.available_at
            if record.available_at <= cutoff:
                visible = record
        if visible is not None:
            selected.append(visible)
    return FeatureSnapshot(cutoff, tuple(selected))
