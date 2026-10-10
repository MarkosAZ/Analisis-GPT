"""Execution identity and pure state/lease rules; PostgreSQL owns concurrency."""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sports_analysis.domain.temporal import utc


class TriggerType(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


def scheduled_slot(started_at: datetime, *, slot_minutes: int = 30) -> datetime:
    """Floor actual start in UTC; GitHub does not provide intended cron fire time."""
    if slot_minutes < 1 or 1440 % slot_minutes:
        raise ValueError("slot_minutes must be a positive divisor of one UTC day")
    started_at = utc(started_at, "started_at")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    duration = timedelta(minutes=slot_minutes)
    return epoch + ((started_at - epoch) // duration) * duration


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    event_cycle_id: UUID
    trigger_type: TriggerType
    pipeline_version: str
    slot: datetime | None = None
    github_run_id: int | None = None

    def __post_init__(self) -> None:
        if not self.pipeline_version.strip():
            raise ValueError("pipeline_version is required")
        if self.trigger_type == TriggerType.SCHEDULED:
            if self.slot is None or self.github_run_id is not None:
                raise ValueError("scheduled identity requires only a scheduled slot")
            slot = utc(self.slot, "slot")
            if slot.second or slot.microsecond:
                raise ValueError("scheduled slot must be aligned to a whole minute")
            object.__setattr__(self, "slot", slot)
        elif self.trigger_type == TriggerType.MANUAL:
            if self.slot is not None or self.github_run_id is None or self.github_run_id <= 0:
                raise ValueError("manual identity requires only a positive github_run_id")
        else:
            raise ValueError("unsupported trigger type")

    @classmethod
    def scheduled(
        cls,
        event_cycle_id: UUID,
        started_at: datetime,
        pipeline_version: str,
        *,
        slot_minutes: int = 30,
    ) -> "IdempotencyKey":
        return cls(
            event_cycle_id,
            TriggerType.SCHEDULED,
            pipeline_version,
            slot=scheduled_slot(started_at, slot_minutes=slot_minutes),
        )

    @classmethod
    def manual(
        cls, event_cycle_id: UUID, github_run_id: int, pipeline_version: str
    ) -> "IdempotencyKey":
        return cls(
            event_cycle_id, TriggerType.MANUAL, pipeline_version, github_run_id=github_run_id
        )

    @property
    def digest(self) -> str:
        parts = [
            str(self.event_cycle_id),
            self.trigger_type.value,
            self.pipeline_version,
            self.slot.isoformat() if self.slot else None,
            self.github_run_id,
        ]
        return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    INGESTING = "INGESTING"
    NORMALIZING = "NORMALIZING"
    FEATURES = "FEATURES"
    PREDICTING = "PREDICTING"
    EXPLAINING = "EXPLAINING"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED_DATA = "FAILED_DATA"
    FAILED_MODEL = "FAILED_MODEL"
    FAILED_TIMEOUT = "FAILED_TIMEOUT"


PIPELINE_STAGES = (
    AnalysisStatus.QUEUED,
    AnalysisStatus.INGESTING,
    AnalysisStatus.NORMALIZING,
    AnalysisStatus.FEATURES,
    AnalysisStatus.PREDICTING,
    AnalysisStatus.EXPLAINING,
    AnalysisStatus.PUBLISHING,
)
FAILED_STATUSES = frozenset(
    {AnalysisStatus.FAILED_DATA, AnalysisStatus.FAILED_MODEL, AnalysisStatus.FAILED_TIMEOUT}
)
FINISHED_STATUSES = FAILED_STATUSES | {
    AnalysisStatus.COMPLETED,
    AnalysisStatus.COMPLETED_WITH_WARNINGS,
}


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    analysis_run_id: UUID
    identity: IdempotencyKey
    decision_time: datetime
    started_at: datetime
    stage_started_at: datetime
    heartbeat_at: datetime
    status: AnalysisStatus = AnalysisStatus.QUEUED
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        for field in (
            "decision_time",
            "started_at",
            "stage_started_at",
            "heartbeat_at",
            "finished_at",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, utc(value, field))
        if not self.started_at <= self.stage_started_at <= self.heartbeat_at:
            raise ValueError("stage start and heartbeat must be chronologically ordered")
        if (self.status in FINISHED_STATUSES) != (self.finished_at is not None):
            raise ValueError("only terminal runs must have finished_at")
        if self.finished_at is not None and self.finished_at < self.heartbeat_at:
            raise ValueError("finished_at cannot precede heartbeat_at")

    def heartbeat(self, *, at: datetime) -> "AnalysisRun":
        at = utc(at, "at")
        if self.status in FINISHED_STATUSES or at < self.heartbeat_at:
            raise ValueError("heartbeat cannot modify terminal history or move backwards")
        return replace(self, heartbeat_at=at)

    def transition(self, status: AnalysisStatus, *, at: datetime) -> "AnalysisRun":
        at = utc(at, "at")
        if self.status in FINISHED_STATUSES or at < self.heartbeat_at:
            raise ValueError("run transitions cannot modify terminal history or move backwards")
        if status not in FAILED_STATUSES:
            if self.status == AnalysisStatus.PUBLISHING:
                allowed = {AnalysisStatus.COMPLETED, AnalysisStatus.COMPLETED_WITH_WARNINGS}
            else:
                allowed = {PIPELINE_STAGES[PIPELINE_STAGES.index(self.status) + 1]}
            if status not in allowed:
                raise ValueError(
                    "analysis must follow RAW -> NORMALIZED -> FEATURES -> PREDICTIONS"
                )
        return replace(
            self,
            status=status,
            stage_started_at=at,
            heartbeat_at=at,
            finished_at=at if status in FINISHED_STATUSES else None,
        )

    def reconcile_timeout(self, *, now: datetime, timeout: timedelta) -> "AnalysisRun":
        now = utc(now, "now")
        if timeout <= timedelta(0):
            raise ValueError("timeout must be positive")
        if self.status not in FINISHED_STATUSES and now - self.heartbeat_at >= timeout:
            return self.transition(AnalysisStatus.FAILED_TIMEOUT, at=now)
        return self


@dataclass(frozen=True, slots=True)
class EventLock:
    """Lease rules only: acquisition/renewal must be atomic in PostgreSQL."""

    event_cycle_id: UUID
    owner_analysis_run_id: UUID
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field in ("acquired_at", "heartbeat_at", "expires_at"):
            object.__setattr__(self, field, utc(getattr(self, field), field))
        if not self.acquired_at <= self.heartbeat_at < self.expires_at:
            raise ValueError("lease timestamps must be ordered and TTL positive")

    @classmethod
    def acquire(
        cls, event_cycle_id: UUID, owner_analysis_run_id: UUID, *, now: datetime, ttl: timedelta
    ) -> "EventLock":
        now = utc(now, "now")
        return cls(event_cycle_id, owner_analysis_run_id, now, now, now + ttl)

    def is_active(self, *, now: datetime) -> bool:
        now = utc(now, "now")
        return self.acquired_at <= now < self.expires_at

    def renew(self, owner_analysis_run_id: UUID, *, now: datetime, ttl: timedelta) -> "EventLock":
        now = utc(now, "now")
        if owner_analysis_run_id != self.owner_analysis_run_id:
            raise ValueError("only the lease owner may renew it")
        if not self.is_active(now=now) or now < self.heartbeat_at:
            raise ValueError("expired leases cannot be revived; acquire a new lease")
        return replace(self, heartbeat_at=now, expires_at=now + ttl)
