from __future__ import annotations

import shutil
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from sports_analysis.db.migrate import MigrationError, migrate

from .conftest import ROOT, insert, make_run

pytestmark = pytest.mark.integration


def test_migrations_repeat_and_checksums(database_url: str, tmp_path: Path) -> None:
    assert migrate(database_url, ROOT / "migrations") == ()
    copied = tmp_path / "migrations"
    shutil.copytree(ROOT / "migrations", copied)
    first = sorted(copied.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- tampering\n")
    with pytest.raises(MigrationError, match="history differs"):
        migrate(database_url, copied)
    assert migrate(database_url, ROOT / "migrations") == ()


def test_domain_tables_and_seeds(db) -> None:
    schemas = (
        "catalog",
        "provider",
        "event",
        "market",
        "analysis",
        "ml",
        "paper",
        "private_betting",
        "ops",
    )
    count = db.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ANY(%s) AND table_type='BASE TABLE' AND table_name <> 'schema_migrations'",
        (list(schemas),),
    ).fetchone()[0]
    assert count == 50  # 47 Foundation + 3 browser ingestion/tracking tables
    assert db.execute("SELECT code FROM catalog.sports ORDER BY sport_id").fetchall() == [
        ("FOOTBALL",),
        ("BASKETBALL",),
        ("BASEBALL",),
    ]
    assert db.execute("SELECT code FROM market.bookmakers WHERE is_primary").fetchone() == (
        "BETANO_PE",
    )
    assert (
        db.execute(
            "SELECT count(*) FROM market.market_definitions WHERE active_for_prediction"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("role", ["sports_public_worker", "model_training_worker"])
def test_private_schema_denied_to_public_and_training(db, role) -> None:
    # SET ROLE alone would retain the superuser session's ability to switch to
    # another role. Test using the worker as the actual session identity.
    db.execute(f"SET SESSION AUTHORIZATION {role}")
    assert db.execute(
        "SELECT has_schema_privilege(current_user,'private_betting','USAGE')"
    ).fetchone() == (False,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("SELECT * FROM private_betting.real_bets")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("SET LOCAL ROLE private_bets_worker")


def test_future_private_objects_default_deny(db) -> None:
    db.execute("CREATE TABLE private_betting.future_secret (id integer)")
    db.execute(
        "CREATE FUNCTION private_betting.future_secret_fn() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
    )
    function_oid = db.execute(
        "SELECT 'private_betting.future_secret_fn()'::regprocedure::oid"
    ).fetchone()[0]
    db.execute("SET LOCAL ROLE sports_public_worker")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("SELECT * FROM private_betting.future_secret")
    assert not db.execute(
        "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function_oid,)
    ).fetchone()[0]
    db.execute("RESET ROLE")
    db.execute("SET LOCAL ROLE private_bets_worker")
    db.execute("INSERT INTO private_betting.future_secret VALUES (1)")
    assert db.execute("SELECT * FROM private_betting.future_secret").fetchall() == [(1,)]


@pytest.mark.parametrize(
    "role", ["sports_public_worker", "model_training_worker", "private_bets_worker"]
)
def test_workers_cannot_mutate_governance_or_migrations(db, role) -> None:
    db.execute(f"SET LOCAL ROLE {role}")
    for target in [
        "ops.schema_migrations",
        "ml.evaluation_windows",
        "ml.model_deployments",
        "paper.paper_policies",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute(f"DELETE FROM {target}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("SELECT ml.unlock_holdout(%s, 123)", (uuid4(),))


def test_manual_idempotency_does_not_use_decision_time(db, cycle) -> None:
    make_run(db, cycle, github_run_id=123)
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        make_run(db, cycle, github_run_id=123, decision_time="2040-01-01 18:30Z")
    make_run(db, cycle, github_run_id=124)


def test_scheduled_idempotency_does_not_use_decision_time(db, cycle) -> None:
    values = {"trigger_type": "SCHEDULED", "scheduled_slot": "2040-01-01 18:00Z"}
    make_run(db, cycle, **values)
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        make_run(db, cycle, **values, decision_time="2040-01-01 18:30Z")
    make_run(db, cycle, **values, pipeline_version="pipeline_v2")


def test_input_pit_blocks_late_data_and_identity_rewrite(db, run, provider) -> None:
    values = dict(
        analysis_run_id=run,
        domain="STATS",
        provider_id=provider,
        object_uri="raw/fixture",
        content_hash="b" * 64,
        fetched_at="2040-01-01 17:00Z",
        occurred_at="2040-01-01 16:00Z",
        available_at_min="2040-01-01 17:00Z",
        available_at_max="2040-01-01 18:00Z",
        available_at_source="OBSERVED",
        adapter_version="v1",
        normalizer_version="v1",
        schema_version="v1",
    )
    insert(db, "analysis.input_refs", **values)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "analysis.input_refs",
            **(values | {"object_uri": "raw/future", "available_at_max": "2040-01-01 18:01Z"}),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE analysis.analysis_runs SET decision_time='2040-01-01 16:00Z' WHERE analysis_run_id=%s",
            (run,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE analysis.input_refs SET available_at_max='2040-01-01 19:00Z'")


def test_postponement_creates_new_cycle_without_reparenting(db, cycle, run) -> None:
    event_id = db.execute(
        "SELECT event_id FROM event.event_cycles WHERE event_cycle_id=%s", (cycle,)
    ).fetchone()[0]
    db.execute(
        "UPDATE event.event_cycles SET status='POSTPONED',closed_at=clock_timestamp() WHERE event_cycle_id=%s",
        (cycle,),
    )
    successor = insert(
        db,
        "event.event_cycles",
        event_id=event_id,
        cycle_number=2,
        previous_cycle_id=cycle,
        scheduled_start_at="2040-01-02 20:00Z",
        status="TRACKING",
    )
    assert (
        db.execute(
            "SELECT event_cycle_id FROM analysis.analysis_runs WHERE analysis_run_id=%s", (run,)
        ).fetchone()[0]
        == cycle
    )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE analysis.analysis_runs SET event_cycle_id=%s WHERE analysis_run_id=%s",
            (successor, run),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE event.event_cycles SET status='TRACKING' WHERE event_cycle_id=%s", (cycle,)
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE event.event_cycles SET scheduled_start_at='2040-01-03 20:00Z' WHERE event_cycle_id=%s",
            (successor,),
        )


def test_lock_ttl_owner_and_fencing(db, cycle, run) -> None:
    other = make_run(db, cycle)
    db.execute("SET LOCAL ROLE sports_public_worker")
    token = db.execute(
        "SELECT ops.acquire_event_lock(%s,%s,interval '50 milliseconds')", (cycle, run)
    ).fetchone()[0]
    assert token > 0
    assert (
        db.execute(
            "SELECT ops.acquire_event_lock(%s,%s,interval '1 minute')", (cycle, other)
        ).fetchone()[0]
        is None
    )
    assert not db.execute(
        "SELECT ops.heartbeat_event_lock(%s,%s,%s,interval '1 minute')", (cycle, other, token)
    ).fetchone()[0]
    assert not db.execute(
        "SELECT ops.release_event_lock(%s,%s,%s)", (cycle, other, token)
    ).fetchone()[0]
    time.sleep(0.06)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), db.transaction():
        db.execute("SELECT ops.assert_event_lock(%s,%s,%s)", (cycle, run, token))
    new_token = db.execute(
        "SELECT ops.acquire_event_lock(%s,%s,interval '1 minute')", (cycle, other)
    ).fetchone()[0]
    assert new_token > token
    assert not db.execute(
        "SELECT ops.release_event_lock(%s,%s,%s)", (cycle, run, token)
    ).fetchone()[0]
    db.execute("SELECT ops.assert_event_lock(%s,%s,%s)", (cycle, other, new_token))
    assert db.execute(
        "SELECT ops.release_event_lock(%s,%s,%s)", (cycle, other, new_token)
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("DELETE FROM ops.event_locks")


@pytest.mark.parametrize("ttl", ["0 seconds", "-1 minute", "2 hours"])
def test_invalid_lock_ttl(db, cycle, run, ttl) -> None:
    with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
        db.execute("SELECT ops.acquire_event_lock(%s,%s,%s::interval)", (cycle, run, ttl))


def test_mapping_ambiguity_creates_one_review(db, provider) -> None:
    mapping = insert(
        db,
        "provider.entity_mappings",
        provider_id=provider,
        provider_entity_type="TEAM",
        provider_entity_id="ambiguous",
        provider_name="United",
        confidence=0.5,
        mapping_status="PENDING_REVIEW",
        mapping_method="NAME_MATCH",
    )
    db.execute("UPDATE provider.entity_mappings SET confidence=0.6 WHERE mapping_id=%s", (mapping,))
    assert db.execute(
        "SELECT reason_code FROM ops.review_queue WHERE mapping_id=%s", (mapping,)
    ).fetchall() == [("AMBIGUOUS_MAPPING",)]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE provider.entity_mappings SET mapping_status='AUTO_CONFIRMED' WHERE mapping_id=%s",
            (mapping,),
        )


def test_policies_freeze_prospectively(db) -> None:
    values = dict(
        code="paper_all_v1",
        valid_from="2040-01-01Z",
        selection_rule="MAX_POSITIVE_EDGE",
        odds_source_rule="BETANO_PRIMARY",
        requires_no_bet_false=False,
        stake_units=1,
        config_hash="c" * 64,
        frozen=True,
    )
    policy = insert(db, "paper.paper_policies", **values)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE paper.paper_policies SET requires_no_bet_false=true WHERE paper_policy_id=%s",
            (policy,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "paper.paper_policies",
            **(values | {"code": "historical_v1", "valid_from": "2000-01-01Z"}),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("DELETE FROM paper.paper_policies WHERE paper_policy_id=%s", (policy,))


def test_deployments_preserve_prospective_track_record(db, model) -> None:
    family, version = model
    values = dict(
        model_family_id=family,
        model_version_id=version,
        valid_from="2040-01-01Z",
        prospective_track_start="2040-01-01Z",
        deployment_reason="Approved validation",
    )
    deployment = insert(db, "ml.model_deployments", **values)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "ml.model_deployments",
            **(values | {"valid_from": "2000-01-01Z", "prospective_track_start": "2000-01-01Z"}),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "ml.model_deployments",
            **(values | {"valid_from": "2040-02-01Z", "prospective_track_start": "2040-02-01Z"}),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE ml.model_deployments SET valid_from='2039-01-01Z' WHERE deployment_id=%s",
            (deployment,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE ml.model_versions SET artifact_hash=%s WHERE model_version_id=%s",
            ("d" * 64, version),
        )
