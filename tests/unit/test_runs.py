from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from sports_analysis.domain.runs import (
    PIPELINE_STAGES,
    AnalysisRun,
    AnalysisStatus,
    EventLock,
    IdempotencyKey,
    scheduled_slot,
)

NOW = datetime(2026, 1, 1, 19, 5, tzinfo=UTC)


def run() -> AnalysisRun:
    identity = IdempotencyKey.manual(uuid4(), 1234, "pipeline_v1")
    return AnalysisRun(uuid4(), identity, NOW, NOW, NOW, NOW)


def test_scheduled_idempotency_is_based_on_actual_start_floor_slot() -> None:
    cycle_id = uuid4()
    first = IdempotencyKey.scheduled(cycle_id, NOW, "v1")
    retry = IdempotencyKey.scheduled(cycle_id, NOW + timedelta(minutes=10), "v1")
    assert first == retry
    assert first.digest == retry.digest
    assert first.slot == datetime(2026, 1, 1, 19, tzinfo=UTC)
    assert first != IdempotencyKey.scheduled(cycle_id, NOW + timedelta(minutes=30), "v1")
    assert first != IdempotencyKey.scheduled(cycle_id, NOW, "v2")


def test_scheduled_slot_uses_utc_independent_of_display_timezone() -> None:
    assert scheduled_slot(NOW.astimezone(timezone(timedelta(hours=-5)))) == scheduled_slot(NOW)
    with pytest.raises(ValueError, match="divisor"):
        scheduled_slot(NOW, slot_minutes=7)


def test_manual_runs_are_independent_of_cron_and_retry_uses_same_github_run() -> None:
    cycle_id = uuid4()
    manual = IdempotencyKey.manual(cycle_id, 1234, "v1")
    assert manual == IdempotencyKey.manual(cycle_id, 1234, "v1")
    assert manual != IdempotencyKey.manual(cycle_id, 1235, "v1")
    assert manual.digest != IdempotencyKey.scheduled(cycle_id, NOW, "v1").digest


def test_run_cannot_skip_normalization_or_change_completed_history() -> None:
    current = run()
    with pytest.raises(ValueError, match="RAW"):
        current.transition(AnalysisStatus.PREDICTING, at=NOW)
    for offset, status in enumerate(PIPELINE_STAGES[1:], start=1):
        current = current.transition(status, at=NOW + timedelta(seconds=offset))
    completed = current.transition(AnalysisStatus.COMPLETED, at=NOW + timedelta(minutes=1))
    assert completed.decision_time == NOW
    assert completed.finished_at is not None
    with pytest.raises(ValueError, match="terminal history"):
        completed.heartbeat(at=NOW + timedelta(minutes=2))


def test_dead_runner_times_out_but_recent_heartbeat_preserves_live_run() -> None:
    started = run().transition(AnalysisStatus.INGESTING, at=NOW)
    timeout = timedelta(minutes=10)
    now = NOW + timeout
    assert (
        started.reconcile_timeout(now=now, timeout=timeout).status == AnalysisStatus.FAILED_TIMEOUT
    )
    live = started.heartbeat(at=now - timedelta(minutes=1))
    assert live.reconcile_timeout(now=now, timeout=timeout) == live


def test_lock_ttl_expires_exactly_at_boundary_and_only_owner_can_renew() -> None:
    owner = uuid4()
    lock = EventLock.acquire(uuid4(), owner, now=NOW, ttl=timedelta(minutes=5))
    assert lock.is_active(now=NOW + timedelta(minutes=4))
    assert not lock.is_active(now=NOW + timedelta(minutes=5))
    with pytest.raises(ValueError, match="owner"):
        lock.renew(uuid4(), now=NOW + timedelta(minutes=1), ttl=timedelta(minutes=5))
    with pytest.raises(ValueError, match="expired"):
        lock.renew(owner, now=NOW + timedelta(minutes=5), ttl=timedelta(minutes=5))
    renewed = lock.renew(owner, now=NOW + timedelta(minutes=4), ttl=timedelta(minutes=5))
    assert renewed.acquired_at == lock.acquired_at
    assert renewed.expires_at == NOW + timedelta(minutes=9)


def test_lock_rejects_zero_ttl() -> None:
    with pytest.raises(ValueError, match="TTL positive"):
        EventLock.acquire(uuid4(), uuid4(), now=NOW, ttl=timedelta(0))
