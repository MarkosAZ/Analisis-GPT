from uuid import uuid4

import pytest

from sports_analysis.domain.mappings import (
    MappingCandidate,
    MappingPolicy,
    MappingStatus,
    resolve_mapping,
)


def test_ambiguous_mapping_requires_review_in_any_order() -> None:
    candidates = (MappingCandidate(uuid4(), 0.999), MappingCandidate(uuid4(), 0.999))
    for ordered in (candidates, tuple(reversed(candidates))):
        result = resolve_mapping(ordered)
        assert result.status == MappingStatus.PENDING_REVIEW
        assert result.entity_id is None
        assert result.reason == "AMBIGUOUS"
        assert result.candidates == ordered


def test_only_unique_high_confidence_match_is_confirmed() -> None:
    identity = uuid4()
    result = resolve_mapping((MappingCandidate(identity, 0.999), MappingCandidate(uuid4(), 0.5)))
    assert result.status == MappingStatus.AUTO_CONFIRMED
    assert result.entity_id == identity
    assert result.policy_version == "mapping_policy_v1"


def test_missing_and_low_confidence_candidates_require_review() -> None:
    assert resolve_mapping(()).status == MappingStatus.PENDING_REVIEW
    assert resolve_mapping((MappingCandidate(uuid4(), 0.95),)).entity_id is None


def test_threshold_is_explicitly_versioned() -> None:
    result = resolve_mapping(
        (MappingCandidate(uuid4(), 0.995),),
        policy=MappingPolicy("mapping_policy_v2", 0.999),
    )
    assert result.status == MappingStatus.PENDING_REVIEW
    assert result.policy_version == "mapping_policy_v2"


@pytest.mark.parametrize("confidence", [-1.0, 1.01, float("nan"), float("inf")])
def test_invalid_confidence_rejected(confidence: float) -> None:
    with pytest.raises(ValueError):
        MappingCandidate(uuid4(), confidence)


def test_duplicate_identity_candidates_rejected() -> None:
    candidate = MappingCandidate(uuid4(), 0.999)
    with pytest.raises(ValueError, match="Duplicate"):
        resolve_mapping((candidate, candidate))
