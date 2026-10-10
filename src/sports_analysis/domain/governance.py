"""Prospective model attribution and protected evaluation-window contracts.

These immutable objects validate evidence, not caller permissions. The database
and the future explicitly manual admin workflow must enforce authorization.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sports_analysis.domain.temporal import utc


class ModelStatus(StrEnum):
    TRAINING = "TRAINING"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PRODUCTION = "PRODUCTION"
    DEGRADED = "DEGRADED"
    NO_VALIDATED = "NO_VALIDATED"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class ModelVersion:
    model_version_id: UUID
    model_family_id: UUID
    version: str
    status: ModelStatus
    created_at: datetime
    artifact_uri: str
    artifact_hash: str
    feature_pipeline_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", utc(self.created_at, "created_at"))
        if not self.version or not self.artifact_uri or not self.feature_pipeline_version:
            raise ValueError("model version, artifact and feature pipeline provenance are required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.artifact_hash):
            raise ValueError("artifact_hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ModelDeployment:
    model_version_id: UUID
    model_family_id: UUID
    recorded_at: datetime
    valid_from: datetime
    prospective_track_start: datetime
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        for field in ("recorded_at", "valid_from", "prospective_track_start", "valid_to"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, utc(value, field))
        if self.valid_from < self.recorded_at:
            raise ValueError("production activation cannot be backdated")
        if self.prospective_track_start != self.valid_from:
            raise ValueError("live track record starts exactly at production activation")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("deployment end must follow activation")

    def includes(self, decision_time: datetime) -> bool:
        at = utc(decision_time, "decision_time")
        return self.valid_from <= at and (self.valid_to is None or at < self.valid_to)

    def retire(self, *, valid_to: datetime, recorded_at: datetime) -> "ModelDeployment":
        valid_to = utc(valid_to, "valid_to")
        recorded_at = utc(recorded_at, "recorded_at")
        if self.valid_to is not None:
            raise ValueError("a retired deployment is immutable")
        if valid_to < recorded_at or recorded_at < self.recorded_at:
            raise ValueError("deployment retirement cannot rewrite past attribution")
        return replace(self, valid_to=valid_to)


def activate_model(
    version: ModelVersion, *, recorded_at: datetime, valid_from: datetime
) -> ModelDeployment:
    """Only validated candidates can begin a new prospective production record."""
    recorded_at = utc(recorded_at, "recorded_at")
    if version.status != ModelStatus.VALIDATED:
        raise ValueError("only a validated model version may enter production")
    if recorded_at < version.created_at:
        raise ValueError("activation cannot precede creation of the model version")
    return ModelDeployment(
        model_version_id=version.model_version_id,
        model_family_id=version.model_family_id,
        recorded_at=recorded_at,
        valid_from=valid_from,
        prospective_track_start=valid_from,
    )


def production_model_as_of(
    deployments: Iterable[ModelDeployment], *, model_family_id: UUID, decision_time: datetime
) -> ModelDeployment | None:
    at = utc(decision_time, "decision_time")
    eligible = [
        deployment
        for deployment in deployments
        if deployment.model_family_id == model_family_id and deployment.includes(at)
    ]
    if len(eligible) > 1:
        raise ValueError("overlapping production deployments are ambiguous")
    return eligible[0] if eligible else None


class WindowType(StrEnum):
    TRAIN = "TRAIN"
    DEVELOPMENT = "DEVELOPMENT"
    HOLDOUT = "HOLDOUT"
    PROSPECTIVE = "PROSPECTIVE"


class HoldoutLockedError(PermissionError):
    """Normal evaluation cannot observe the protected final period."""


@dataclass(frozen=True, slots=True)
class UnlockEvidence:
    """Evidence written by an authorized manual workflow, not an auth token.

    Supplying this object alone grants no SQL privileges. Production callers
    require a separately authenticated admin identity; workers never get it.
    """

    github_run_id: int
    actor: str
    recorded_at: datetime
    reason: str
    trigger_type: str = "workflow_dispatch"

    def __post_init__(self) -> None:
        if self.github_run_id <= 0 or not self.actor.strip() or not self.reason.strip():
            raise ValueError("manual unlock requires run identity, actor and reason")
        if self.trigger_type != "workflow_dispatch":
            raise ValueError("holdout unlock must originate from an explicit manual workflow")
        object.__setattr__(self, "recorded_at", utc(self.recorded_at, "recorded_at"))


@dataclass(frozen=True, slots=True)
class EvaluationWindow:
    window_id: UUID
    name: str
    window_type: WindowType
    starts_at: datetime
    ends_at: datetime
    locked: bool = False
    unlock_evidence: UnlockEvidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "starts_at", utc(self.starts_at, "starts_at"))
        object.__setattr__(self, "ends_at", utc(self.ends_at, "ends_at"))
        if self.ends_at <= self.starts_at or not self.name.strip():
            raise ValueError("evaluation windows require a name and a nonempty interval")
        if (
            self.window_type == WindowType.HOLDOUT
            and not self.locked
            and self.unlock_evidence is None
        ):
            raise ValueError("a holdout begins locked and requires evidence to unlock")
        if self.unlock_evidence is not None and (
            self.locked or self.window_type != WindowType.HOLDOUT
        ):
            raise ValueError("unlock evidence only belongs to an unlocked holdout")

    def require_evaluation_access(self) -> None:
        if self.locked:
            raise HoldoutLockedError("evaluation period is locked")


def unlock_holdout(window: EvaluationWindow, *, evidence: UnlockEvidence) -> EvaluationWindow:
    """Model an explicit audited admin operation; this function cannot authenticate it."""
    if window.window_type != WindowType.HOLDOUT or not window.locked:
        raise ValueError("only a locked holdout can be unlocked")
    return replace(window, locked=False, unlock_evidence=evidence)


def assert_evaluation_range_allowed(
    *, starts_at: datetime, ends_at: datetime, protected_windows: Iterable[EvaluationWindow]
) -> None:
    """Check interval overlap so renaming a request cannot bypass a holdout.

    Callers must load all protected windows from the trusted registry. Database
    policies independently restrict the relevant protected data.
    """
    starts_at, ends_at = utc(starts_at, "starts_at"), utc(ends_at, "ends_at")
    if ends_at <= starts_at:
        raise ValueError("evaluation interval must be nonempty")
    for window in protected_windows:
        if window.locked and starts_at < window.ends_at and ends_at > window.starts_at:
            raise HoldoutLockedError("evaluation interval overlaps a protected period")
