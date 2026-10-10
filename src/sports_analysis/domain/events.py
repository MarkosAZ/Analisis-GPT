"""Sporting identity and immutable scheduling cycles."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sports_analysis.domain.temporal import utc


class Sport(StrEnum):
    FOOTBALL = "FOOTBALL"
    BASKETBALL = "BASKETBALL"
    BASEBALL = "BASEBALL"


class CycleStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    TRACKING = "TRACKING"
    LOCKED = "LOCKED"
    FINALIZED = "FINALIZED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"


TERMINAL_CYCLE_STATUSES = frozenset(
    {CycleStatus.FINALIZED, CycleStatus.POSTPONED, CycleStatus.CANCELLED, CycleStatus.ABANDONED}
)


@dataclass(frozen=True, slots=True)
class Event:
    event_id: UUID
    sport: Sport
    competition_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class EventCycle:
    event_cycle_id: UUID
    event_id: UUID
    cycle_number: int
    scheduled_start_at: datetime
    created_at: datetime
    timezone_event: str = "America/Lima"
    status: CycleStatus = CycleStatus.SCHEDULED
    previous_cycle_id: UUID | None = None
    actual_start_at: datetime | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.cycle_number < 1:
            raise ValueError("cycle_number must be positive")
        if (self.cycle_number == 1) != (self.previous_cycle_id is None):
            raise ValueError("only the first cycle has no previous_cycle_id")
        if self.previous_cycle_id == self.event_cycle_id:
            raise ValueError("a cycle cannot replace itself")
        ZoneInfo(self.timezone_event)
        for field in ("scheduled_start_at", "created_at", "actual_start_at", "closed_at"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, utc(value, field))
        if (self.status in TERMINAL_CYCLE_STATUSES) != (self.closed_at is not None):
            raise ValueError("terminal cycles require closed_at; active cycles cannot have it")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise ValueError("a cycle cannot close before it was created")
        if self.status == CycleStatus.FINALIZED and self.actual_start_at is None:
            raise ValueError("a finalized cycle requires actual_start_at")
        if (
            self.actual_start_at is not None
            and self.closed_at is not None
            and self.actual_start_at > self.closed_at
        ):
            raise ValueError("actual_start_at cannot follow closed_at")

    def transition(
        self, status: CycleStatus, *, at: datetime, actual_start_at: datetime | None = None
    ) -> "EventCycle":
        if self.status in TERMINAL_CYCLE_STATUSES:
            raise ValueError("terminal cycles cannot reopen; create a new scheduling cycle")
        allowed = {
            CycleStatus.SCHEDULED: {
                CycleStatus.TRACKING,
                CycleStatus.LOCKED,
                CycleStatus.POSTPONED,
                CycleStatus.CANCELLED,
                CycleStatus.ABANDONED,
                CycleStatus.FINALIZED,
            },
            CycleStatus.TRACKING: {
                CycleStatus.LOCKED,
                CycleStatus.POSTPONED,
                CycleStatus.CANCELLED,
                CycleStatus.ABANDONED,
                CycleStatus.FINALIZED,
            },
            CycleStatus.LOCKED: TERMINAL_CYCLE_STATUSES,
        }
        if status not in allowed.get(self.status, frozenset()):
            raise ValueError("invalid event cycle transition")
        changed_at = utc(at, "at")
        if changed_at < self.created_at:
            raise ValueError("transition cannot precede cycle creation")
        return replace(
            self,
            status=status,
            closed_at=changed_at if status in TERMINAL_CYCLE_STATUSES else None,
            actual_start_at=actual_start_at or self.actual_start_at,
        )


def postpone_cycle(
    cycle: EventCycle,
    *,
    recorded_at: datetime,
    new_start_at: datetime,
    replacement_id: UUID | None = None,
) -> tuple[EventCycle, EventCycle]:
    """Preserve the previous cycle and create another under the same event.

    Persistence must commit both records atomically and enforce the unique
    ``(event_id, cycle_number)`` constraint. Existing prediction FKs stay put.
    """
    if cycle.status == CycleStatus.POSTPONED:
        old = cycle
    else:
        old = cycle.transition(CycleStatus.POSTPONED, at=recorded_at)
    recorded_at = utc(recorded_at, "recorded_at")
    if old.closed_at is not None and recorded_at < old.closed_at:
        raise ValueError("a replacement cannot be recorded before postponement")
    new = EventCycle(
        event_cycle_id=replacement_id or uuid4(),
        event_id=old.event_id,
        cycle_number=old.cycle_number + 1,
        scheduled_start_at=new_start_at,
        created_at=recorded_at,
        timezone_event=old.timezone_event,
        status=CycleStatus.TRACKING,
        previous_cycle_id=old.event_cycle_id,
    )
    return old, new


class EvaluationDisposition(StrEnum):
    SCORE = "SCORE"
    EXCLUDE = "EXCLUDE"
    PENDING = "PENDING"
    PENDING_REVIEW = "PENDING_REVIEW"


def evaluation_disposition(
    prediction_cycle_id: UUID, result_cycle: EventCycle
) -> EvaluationDisposition:
    """Scientific evaluation never borrows results from a replacement cycle.

    Bookmaker-specific paper settlement rules are separate. In particular an
    abandoned match requires review, rather than an invented win/loss/void.
    """
    if prediction_cycle_id != result_cycle.event_cycle_id:
        raise ValueError("prediction and result must reference the same event_cycle_id")
    if result_cycle.status == CycleStatus.FINALIZED:
        return EvaluationDisposition.SCORE
    if result_cycle.status in {CycleStatus.POSTPONED, CycleStatus.CANCELLED}:
        return EvaluationDisposition.EXCLUDE
    if result_cycle.status == CycleStatus.ABANDONED:
        return EvaluationDisposition.PENDING_REVIEW
    return EvaluationDisposition.PENDING
