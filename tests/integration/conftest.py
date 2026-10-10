"""Real PostgreSQL checks; every test's fixture records roll back.

TEST_DATABASE_URL must identify a disposable owner-accessible database. Never
set it to a shared environment: the migration tests create/drop test databases.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from sports_analysis.db.migrate import migrate

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database_url() -> str:
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        if os.environ.get("CI"):
            pytest.fail("CI must provide a disposable TEST_DATABASE_URL")
        pytest.skip("set TEST_DATABASE_URL to run real PostgreSQL integration checks")
    migrate(dsn, ROOT / "migrations")
    return dsn


@pytest.fixture
def db(database_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(database_url) as conn:
        try:
            yield conn
            conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            conn.rollback()


def insert(db: psycopg.Connection[Any], table: str, **values: Any) -> Any:
    """Insert fixtures with safely quoted identifiers and bound values."""
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(*table.split(".")),
        sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join(sql.Placeholder() for _ in values),
    )
    return db.execute(query, tuple(values.values())).fetchone()[0]


@pytest.fixture
def cycle(db: psycopg.Connection[Any]) -> UUID:
    competition = insert(db, "catalog.entities", entity_type="COMPETITION")
    insert(
        db,
        "catalog.competitions",
        competition_id=competition,
        sport_id=1,
        canonical_name="Test league",
    )
    event = insert(db, "event.events", sport_id=1, competition_id=competition)
    return insert(
        db,
        "event.event_cycles",
        event_id=event,
        cycle_number=1,
        scheduled_start_at="2040-01-01 20:00Z",
        status="TRACKING",
    )


def make_run(db: psycopg.Connection[Any], cycle: UUID, **overrides: Any) -> UUID:
    values = {
        "event_cycle_id": cycle,
        "run_mode": "LIVE",
        "trigger_type": "MANUAL",
        "github_run_id": uuid4().int % 2**62 + 1,
        "decision_time": "2040-01-01 18:00Z",
        "pipeline_version": "pipeline_v1",
        "feature_pipeline_version": "features_v1",
        "line_selector_version": "line_selector_v1",
        "confidence_policy_version": "confidence_policy_v1",
        "no_bet_policy_version": "no_bet_policy_v1",
        "git_sha": "a" * 40,
    }
    values.update(overrides)
    return insert(db, "analysis.analysis_runs", **values)


@pytest.fixture
def run(db: psycopg.Connection[Any], cycle: UUID) -> UUID:
    return make_run(db, cycle)


@pytest.fixture
def provider(db: psycopg.Connection[Any]) -> UUID:
    return insert(
        db, "provider.providers", code="TEST", name="Fixture", provider_type="SPORTS_DATA"
    )


@pytest.fixture
def model(db: psycopg.Connection[Any]) -> tuple[UUID, UUID]:
    family = insert(
        db,
        "ml.model_families",
        code="TEST_STAT",
        sport_id=1,
        market_code="FOOTBALL_TOTAL_GOALS",
        model_role="STATISTICAL",
    )
    version = insert(
        db,
        "ml.model_versions",
        model_family_id=family,
        version="v1",
        status="VALIDATED",
        artifact_uri="models/test.bin",
        artifact_hash="a" * 64,
        git_sha="a" * 40,
        feature_pipeline_version="features_v1",
    )
    return family, version
