from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from sports_analysis.db.migrate import migrate

from .conftest import ROOT, insert, make_run

pytestmark = pytest.mark.integration


@pytest.fixture
def market(db, run):
    return insert(
        db,
        "analysis.analysis_markets",
        analysis_run_id=run,
        market_code="FOOTBALL_TOTAL_GOALS",
        status="ELIGIBLE",
        selected_line=Decimal("2.5"),
        line_type="HALF_LINE",
        line_selector_version="line_selector_v1",
        selection_reason="FIXTURE",
        odds_freshness="FRESH",
    )


def prediction_values(market, model):
    return dict(
        analysis_market_id=market,
        model_version_id=model[1],
        model_role="STATISTICAL",
        generated_at="2040-01-01 18:01Z",
        favored_outcome_code="OVER",
        favored_probability=0.578,
        confidence_level="LOW",
        confidence_policy_version="confidence_policy_v1",
        no_bet=False,
        no_bet_policy_version="no_bet_policy_v1",
        model_status_at_prediction="VALIDATED",
    )


@pytest.fixture
def prediction(db, market, model):
    identity = insert(db, "analysis.model_predictions", **prediction_values(market, model))
    for rank, (outcome, probability) in enumerate([("OVER", "0.578"), ("UNDER", "0.422")], 1):
        insert(
            db,
            "analysis.prediction_outcomes",
            prediction_id=identity,
            outcome_code=outcome,
            probability=Decimal(probability),
            fair_odds=1 / Decimal(probability),
            rank=rank,
        )
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    return identity


@pytest.fixture
def quote_and_benchmark(db, market, prediction):
    bookmaker = db.execute(
        "SELECT bookmaker_id FROM market.bookmakers WHERE code='BETANO_PE'"
    ).fetchone()[0]
    quote = insert(
        db,
        "market.selected_quotes",
        analysis_market_id=market,
        bookmaker_id=bookmaker,
        captured_at="2040-01-01 17:59Z",
        available_at="2040-01-01 17:59Z",
        line_value=Decimal("2.5"),
        overround=1 / 1.6 + 1 / 2.4 - 1,
        devig_method="PROPORTIONAL_V1",
    )
    benchmark = insert(
        db,
        "market.market_benchmarks",
        analysis_market_id=market,
        benchmark_type="BETANO",
        devig_method="PROPORTIONAL_V1",
        calculated_at="2040-01-01 18:00Z",
        source_snapshot_at="2040-01-01 17:59Z",
        available_at="2040-01-01 17:59Z",
        freshness="FRESH",
    )
    for outcome, price, probability, model_probability in [
        ("OVER", "1.6", "0.6", "0.578"),
        ("UNDER", "2.4", "0.4", "0.422"),
    ]:
        insert(
            db,
            "market.selected_quote_outcomes",
            quote_id=quote,
            outcome_code=outcome,
            decimal_odds=Decimal(price),
            implied_probability=1 / Decimal(price),
            no_vig_probability=Decimal(probability),
        )
        insert(
            db,
            "market.benchmark_outcomes",
            benchmark_id=benchmark,
            outcome_code=outcome,
            no_vig_probability=Decimal(probability),
            fair_odds=1 / Decimal(probability),
        )
        edge = (Decimal(model_probability) - Decimal(probability)) * 100
        insert(
            db,
            "analysis.prediction_edges",
            prediction_id=prediction,
            benchmark_id=benchmark,
            outcome_code=outcome,
            model_probability=Decimal(model_probability),
            market_probability=Decimal(probability),
            edge_pp=edge,
            is_value_side=edge > 0,
        )
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    return quote, benchmark, bookmaker


def test_incomplete_probability_vector_cannot_commit(db, market, model):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(db, "analysis.model_predictions", **prediction_values(market, model))
        db.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_future_model_and_undeployed_production_are_rejected(db, market, model):
    values = prediction_values(market, model)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "analysis.model_predictions",
            **(values | {"model_status_at_prediction": "PRODUCTION"}),
        )
    future_version = insert(
        db,
        "ml.model_versions",
        model_family_id=model[0],
        version="future",
        status="VALIDATED",
        created_at="2041-01-01Z",
        artifact_uri="models/future",
        artifact_hash="a" * 64,
        git_sha="a" * 40,
        feature_pipeline_version="features_v1",
    )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(db, "analysis.model_predictions", **(values | {"model_version_id": future_version}))


def test_predictions_cannot_reparent_or_rewrite_probabilities(db, prediction, market):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE analysis.model_predictions SET favored_probability=0.9 WHERE prediction_id=%s",
            (prediction,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE analysis.analysis_markets SET selected_line=3.5 WHERE analysis_market_id=%s",
            (market,),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "UPDATE analysis.prediction_outcomes SET probability=0.9 WHERE prediction_id=%s",
            (prediction,),
        )


def paper_values(db, prediction, quote_and_benchmark, *, start="2039-01-01Z"):
    policy = insert(
        db,
        "paper.paper_policies",
        code=f"paper_all_{uuid4().hex}",
        valid_from=start,
        selection_rule="MAX_POSITIVE_EDGE",
        odds_source_rule="BETANO_PRIMARY",
        requires_no_bet_false=False,
        stake_units=1,
        config_hash="c" * 64,
        frozen=True,
    )
    quote, benchmark, bookmaker = quote_and_benchmark
    return dict(
        paper_policy_id=policy,
        prediction_id=prediction,
        outcome_code="UNDER",
        bookmaker_id=bookmaker,
        line_value=Decimal("2.5"),
        decimal_odds=Decimal("2.4"),
        stake_units=1,
        placed_at="2040-01-01 18:00Z",
        quote_id=quote,
        benchmark_id=benchmark,
    )


def test_paper_policy_requires_original_decision_window_and_officiality(
    db, run, prediction, quote_and_benchmark
):
    values = paper_values(db, prediction, quote_and_benchmark)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(db, "paper.paper_bets", **values)
    db.execute(
        "UPDATE analysis.analysis_runs SET officiality='OFFICIAL',officialized_at='2040-01-01 22:00Z' WHERE analysis_run_id=%s",
        (run,),
    )
    later = paper_values(db, prediction, quote_and_benchmark, start="2040-01-02Z")
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(db, "paper.paper_bets", **(later | {"placed_at": "2040-01-03Z"}))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "paper.paper_bets",
            **(values | {"outcome_code": "OVER", "decimal_odds": Decimal("1.6")}),
        )
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(db, "paper.paper_bets", **(values | {"decimal_odds": Decimal("3.0")}))
    identity = insert(db, "paper.paper_bets", **values)
    assert db.execute(
        "SELECT outcome_code,stake_units FROM paper.paper_bets WHERE paper_bet_id=%s", (identity,)
    ).fetchone() == ("UNDER", Decimal(1))


def make_result(db, cycle, *, occurred="2040-01-01 22:00Z"):
    return insert(
        db,
        "event.event_results",
        event_cycle_id=cycle,
        result_status="CONFIRMED",
        home_score=2,
        away_score=1,
        actual_start_at="2040-01-01 20:00Z",
        completed_at="2040-01-01 22:00Z",
        confirmed_at="2040-01-01 22:01Z",
        result_data_uri="raw/result",
        occurred_at=occurred,
        available_at="2040-01-01 22:01Z",
        available_at_source="OBSERVED",
    )


def test_evaluation_never_uses_postponed_successor_results(db, cycle, prediction):
    event = db.execute(
        "SELECT event_id FROM event.event_cycles WHERE event_cycle_id=%s", (cycle,)
    ).fetchone()[0]
    db.execute(
        "UPDATE event.event_cycles SET status='POSTPONED',closed_at=clock_timestamp() WHERE event_cycle_id=%s",
        (cycle,),
    )
    successor = insert(
        db,
        "event.event_cycles",
        event_id=event,
        cycle_number=2,
        previous_cycle_id=cycle,
        scheduled_start_at="2040-01-02 20:00Z",
        status="TRACKING",
    )
    make_result(db, successor)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "analysis.prediction_evaluations",
            prediction_id=prediction,
            event_cycle_id=successor,
            evaluated_at="2040-01-03Z",
            included_in_metrics=False,
            exclusion_reason="POSTPONED",
        )


@pytest.mark.parametrize("role", ["sports_public_worker", "model_training_worker"])
def test_holdout_labels_and_overlapping_evaluations_require_admin_unlock(db, cycle, model, role):
    holdout = insert(
        db,
        "ml.evaluation_windows",
        name="Final",
        window_type="HOLDOUT",
        starts_at="2040-01-01Z",
        ends_at="2040-02-01Z",
        locked=True,
    )
    alternate = insert(
        db,
        "ml.evaluation_windows",
        name="Renamed",
        window_type="DEVELOPMENT",
        starts_at="2040-01-01Z",
        ends_at="2040-01-03Z",
        locked=False,
    )
    make_result(db, cycle)
    db.execute(f"SET LOCAL ROLE {role}")
    assert db.execute("SELECT * FROM event.event_results").fetchall() == []
    assert (
        db.execute("SELECT * FROM ml.evaluation_windows WHERE window_id=%s", (holdout,)).fetchall()
        == []
    )
    assert not db.execute("SELECT ml.evaluation_window_is_open(%s)", (alternate,)).fetchone()[0]
    if role == "model_training_worker":
        with (
            pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)),
            db.transaction(),
        ):
            insert(
                db,
                "ml.experiment_runs",
                model_family_id=model[0],
                attempt_number=1,
                config_hash="b" * 64,
                dataset_manifest_hash="c" * 64,
                validation_window_id=alternate,
                git_sha="a" * 40,
                status="RUNNING",
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("SELECT ml.unlock_holdout(%s,123)", (holdout,))
    db.execute("RESET ROLE")
    db.execute("SELECT ml.unlock_holdout(%s,123)", (holdout,))
    db.execute(f"SET LOCAL ROLE {role}")
    assert db.execute("SELECT home_score,away_score FROM event.event_results").fetchone() == (2, 1)
    assert db.execute("SELECT ml.evaluation_window_is_open(%s)", (alternate,)).fetchone()[0]


def test_unchanged_odds_remain_distinct_observations(db, cycle, provider):
    values = dict(
        event_cycle_id=cycle,
        provider_id=provider,
        capture_mode="API",
        fetched_at="2040-01-01 17:00Z",
        occurred_at="2040-01-01 17:00Z",
        available_at="2040-01-01 17:00Z",
        available_at_source="OBSERVED",
        content_hash="d" * 64,
        raw_uri="raw/same",
        adapter_version="v1",
        normalizer_version="v1",
        schema_version="1",
        market_count=1,
        bookmaker_count=1,
        source_quality=1,
        status="CAPTURED",
    )
    first = insert(db, "market.odds_captures", **values)
    second = insert(
        db,
        "market.odds_captures",
        **(values | {"fetched_at": "2040-01-01 17:01Z", "available_at": "2040-01-01 17:01Z"}),
    )
    assert first != second


def test_fresh_migrations_and_concurrent_lock_acquisition(database_url):
    # An entirely new database proves fresh installation, separately from reruns.
    database_name = "foundation_test_" + uuid4().hex
    config = conninfo_to_dict(database_url)
    config["dbname"] = database_name
    isolated_dsn = make_conninfo(**config)
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            assert len(migrate(isolated_dsn, ROOT / "migrations")) == len(
                list((ROOT / "migrations").glob("*.sql"))
            )
            with psycopg.connect(isolated_dsn) as connection:
                competition = insert(connection, "catalog.entities", entity_type="COMPETITION")
                insert(
                    connection,
                    "catalog.competitions",
                    competition_id=competition,
                    sport_id=1,
                    canonical_name="Concurrent fixture",
                )
                event = insert(connection, "event.events", sport_id=1, competition_id=competition)
                cycle = insert(
                    connection,
                    "event.event_cycles",
                    event_id=event,
                    cycle_number=1,
                    scheduled_start_at="2040-01-01Z",
                    status="TRACKING",
                )
                runs = [make_run(connection, cycle), make_run(connection, cycle)]
            barrier = Barrier(2)

            def acquire(run):
                with psycopg.connect(isolated_dsn) as connection:
                    connection.execute("SET LOCAL ROLE sports_public_worker")
                    barrier.wait(timeout=10)
                    return connection.execute(
                        "SELECT ops.acquire_event_lock(%s,%s,interval '1 minute')", (cycle, run)
                    ).fetchone()[0]

            with ThreadPoolExecutor(max_workers=2) as pool:
                tokens = list(pool.map(acquire, runs))
            assert sum(token is not None for token in tokens) == 1
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


@pytest.mark.parametrize("line,kind", [("3.0", "INTEGER_PUSH"), ("2.25", "ASIAN_QUARTER")])
def test_sql_selector_v1_rejects_push_and_asian(db, run, line, kind):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "analysis.analysis_markets",
            analysis_run_id=run,
            market_code="FOOTBALL_TOTAL_GOALS",
            status="ELIGIBLE",
            selected_line=Decimal(line),
            line_type=kind,
            line_selector_version="line_selector_v1",
            selection_reason="FIXTURE",
            odds_freshness="FRESH",
        )


def test_benchmark_cannot_backdate_a_future_snapshot(db, market):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        insert(
            db,
            "market.market_benchmarks",
            analysis_market_id=market,
            benchmark_type="BETANO",
            devig_method="PROPORTIONAL_V1",
            calculated_at="2040-01-01 19:00Z",
            source_snapshot_at="2040-01-01 19:00Z",
            available_at="2040-01-01 17:00Z",
            freshness="FRESH",
        )


def test_sql_quote_preserves_declared_devig_math(db, market):
    bookmaker = db.execute(
        "SELECT bookmaker_id FROM market.bookmakers WHERE code='BETANO_PE'"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        quote = insert(
            db,
            "market.selected_quotes",
            analysis_market_id=market,
            bookmaker_id=bookmaker,
            captured_at="2040-01-01 17:00Z",
            available_at="2040-01-01 17:00Z",
            line_value=Decimal("2.5"),
            overround=1 / 1.6 + 1 / 2.4 - 1,
            devig_method="PROPORTIONAL_V1",
        )
        for code, odds in [("OVER", "1.6"), ("UNDER", "2.4")]:
            insert(
                db,
                "market.selected_quote_outcomes",
                quote_id=quote,
                outcome_code=code,
                decimal_odds=Decimal(odds),
                implied_probability=1 / Decimal(odds),
                no_vig_probability=0.5,
            )
        db.execute("SET CONSTRAINTS ALL IMMEDIATE")
