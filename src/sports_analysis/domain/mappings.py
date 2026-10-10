"""Conservative provider identity resolution; domain IDs are always UUIDs."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from uuid import UUID


class MappingStatus(StrEnum):
    AUTO_CONFIRMED = "AUTO_CONFIRMED"
    MANUAL_CONFIRMED = "MANUAL_CONFIRMED"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class MappingCandidate:
    entity_id: UUID
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.entity_id, UUID):
            raise ValueError("Mapping requires an internal UUID")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Mapping confidence must be between zero and one")


@dataclass(frozen=True)
class MappingPolicy:
    version: str = "mapping_policy_v1"
    minimum_confidence: float = 0.99

    def __post_init__(self) -> None:
        if not self.version or not 0 < self.minimum_confidence <= 1:
            raise ValueError("Invalid mapping policy")


@dataclass(frozen=True)
class MappingDecision:
    status: MappingStatus
    entity_id: UUID | None
    reason: str
    policy_version: str
    candidates: tuple[MappingCandidate, ...]


def resolve_mapping(
    candidates: tuple[MappingCandidate, ...], *, policy: MappingPolicy | None = None
) -> MappingDecision:
    """Only a unique qualifying identity can match; ties never use list order."""
    policy = MappingPolicy() if policy is None else policy
    ids = {candidate.entity_id for candidate in candidates}
    if len(ids) != len(candidates):
        raise ValueError("Duplicate mapping candidates")
    qualified = tuple(
        candidate for candidate in candidates if candidate.confidence >= policy.minimum_confidence
    )
    if len(qualified) == 1:
        return MappingDecision(
            MappingStatus.AUTO_CONFIRMED,
            qualified[0].entity_id,
            "UNIQUE_HIGH_CONFIDENCE",
            policy.version,
            candidates,
        )
    reason = "AMBIGUOUS" if len(qualified) > 1 else "INSUFFICIENT_CONFIDENCE"
    return MappingDecision(MappingStatus.PENDING_REVIEW, None, reason, policy.version, candidates)
