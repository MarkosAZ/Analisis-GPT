from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sports_analysis.domain.events import (
    CycleStatus,
    EvaluationDisposition,
    EventCycle,
    evaluation_disposition,
    postpone_cycle,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def cycle() -> EventCycle:
    return EventCycle(uuid4(), uuid4(), 1, NOW + timedelta(days=1), NOW)


def test_postponement_preserves_event_identity_and_prediction_cycle() -> None:
    first = cycle()
    original_prediction_cycle = first.event_cycle_id
    old, replacement = postpone_cycle(
        first, recorded_at=NOW + timedelta(hours=1), new_start_at=NOW + timedelta(days=2)
    )
    assert old.event_cycle_id == original_prediction_cycle
    assert old.status == CycleStatus.POSTPONED
    assert first.status == CycleStatus.SCHEDULED
    assert replacement.status == CycleStatus.TRACKING
    assert replacement.event_id == old.event_id
    assert replacement.previous_cycle_id == old.event_cycle_id
    assert replacement.event_cycle_id != old.event_cycle_id
    assert replacement.cycle_number == 2
    result = replacement.transition(
        CycleStatus.FINALIZED,
        at=NOW + timedelta(days=2, hours=2),
        actual_start_at=NOW + timedelta(days=2),
    )
    with pytest.raises(ValueError, match="same event_cycle_id"):
        evaluation_disposition(original_prediction_cycle, result)
    assert evaluation_disposition(result.event_cycle_id, result) == EvaluationDisposition.SCORE


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CycleStatus.CANCELLED, EvaluationDisposition.EXCLUDE),
        (CycleStatus.POSTPONED, EvaluationDisposition.EXCLUDE),
        (CycleStatus.ABANDONED, EvaluationDisposition.PENDING_REVIEW),
    ],
)
def test_terminal_events_do_not_invent_results(
    status: CycleStatus, expected: EvaluationDisposition
) -> None:
    closed = cycle().transition(status, at=NOW + timedelta(hours=1))
    assert evaluation_disposition(closed.event_cycle_id, closed) == expected
    with pytest.raises(ValueError, match="cannot reopen"):
        closed.transition(CycleStatus.TRACKING, at=NOW + timedelta(hours=2))


def test_postponed_cycle_can_get_new_schedule_later() -> None:
    postponed = cycle().transition(CycleStatus.POSTPONED, at=NOW + timedelta(hours=1))
    old, replacement = postpone_cycle(
        postponed, recorded_at=NOW + timedelta(days=1), new_start_at=NOW + timedelta(days=3)
    )
    assert old == postponed
    assert replacement.created_at > old.closed_at  # type: ignore[operator]


def test_finalization_requires_actual_start() -> None:
    with pytest.raises(ValueError, match="actual_start_at"):
        cycle().transition(CycleStatus.FINALIZED, at=NOW + timedelta(hours=1))


def test_replacement_cannot_reuse_previous_cycle_identity() -> None:
    first = cycle()
    with pytest.raises(ValueError, match="replace itself"):
        postpone_cycle(
            first,
            recorded_at=NOW,
            new_start_at=NOW + timedelta(days=2),
            replacement_id=first.event_cycle_id,
        )
