from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sports_analysis.domain.governance import (
    EvaluationWindow,
    HoldoutLockedError,
    ModelStatus,
    ModelVersion,
    UnlockEvidence,
    WindowType,
    activate_model,
    assert_evaluation_range_allowed,
    production_model_as_of,
    unlock_holdout,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def model() -> ModelVersion:
    return ModelVersion(
        uuid4(),
        uuid4(),
        "v17",
        ModelStatus.VALIDATED,
        NOW,
        "models/v17.bin",
        "a" * 64,
        "features_v1",
    )


def holdout() -> EvaluationWindow:
    return EvaluationWindow(
        uuid4(), "final", WindowType.HOLDOUT, NOW, NOW + timedelta(days=30), locked=True
    )


def test_model_live_record_starts_at_production_not_training_or_backtest_date() -> None:
    version = model()
    start = NOW + timedelta(days=10)
    deployment = activate_model(version, recorded_at=start, valid_from=start)
    assert not deployment.includes(NOW)
    assert deployment.includes(start)
    assert deployment.prospective_track_start == start
    assert (
        production_model_as_of(
            [deployment], model_family_id=version.model_family_id, decision_time=NOW
        )
        is None
    )
    assert (
        production_model_as_of(
            [deployment], model_family_id=version.model_family_id, decision_time=start
        )
        == deployment
    )


def test_activation_rejects_backdating_and_versions_that_do_not_yet_exist() -> None:
    version = model()
    with pytest.raises(ValueError, match="backdated"):
        activate_model(version, recorded_at=NOW + timedelta(days=1), valid_from=NOW)
    with pytest.raises(ValueError, match="creation"):
        activate_model(version, recorded_at=NOW - timedelta(days=1), valid_from=NOW)
    with pytest.raises(ValueError, match="validated"):
        activate_model(
            replace(version, status=ModelStatus.CANDIDATE), recorded_at=NOW, valid_from=NOW
        )


def test_model_artifact_is_immutable_and_deployments_cannot_overlap() -> None:
    version = model()
    with pytest.raises(FrozenInstanceError):
        version.artifact_hash = "b" * 64
    deployment = activate_model(version, recorded_at=NOW, valid_from=NOW)
    with pytest.raises(ValueError, match="overlapping"):
        production_model_as_of(
            [deployment, deployment], model_family_id=version.model_family_id, decision_time=NOW
        )


def test_retirement_does_not_erase_bad_past_performance() -> None:
    deployment = activate_model(model(), recorded_at=NOW, valid_from=NOW)
    later = NOW + timedelta(days=10)
    with pytest.raises(ValueError, match="past attribution"):
        deployment.retire(valid_to=NOW + timedelta(days=1), recorded_at=later)
    retired = deployment.retire(valid_to=later, recorded_at=later)
    assert retired.includes(NOW)
    assert not retired.includes(later)


def test_holdout_is_inaccessible_to_normal_evaluation() -> None:
    window = holdout()
    with pytest.raises(HoldoutLockedError):
        window.require_evaluation_access()
    with pytest.raises(ValueError, match="requires evidence"):
        replace(window, locked=False)


def test_range_queries_cannot_bypass_holdout_by_selecting_another_window_name() -> None:
    with pytest.raises(HoldoutLockedError, match="overlaps"):
        assert_evaluation_range_allowed(
            starts_at=NOW - timedelta(days=1),
            ends_at=NOW + timedelta(days=1),
            protected_windows=[holdout()],
        )
    assert_evaluation_range_allowed(
        starts_at=NOW - timedelta(days=1), ends_at=NOW, protected_windows=[holdout()]
    )


def test_unlock_requires_explicit_manual_workflow_evidence_preserved_for_audit() -> None:
    with pytest.raises(ValueError, match="manual workflow"):
        UnlockEvidence(1234, "admin", NOW, "final evaluation", trigger_type="schedule")
    evidence = UnlockEvidence(1234, "admin", NOW, "final evaluation")
    locked = holdout()
    unlocked = unlock_holdout(locked, evidence=evidence)
    unlocked.require_evaluation_access()
    assert unlocked.unlock_evidence == evidence
    assert locked.locked
