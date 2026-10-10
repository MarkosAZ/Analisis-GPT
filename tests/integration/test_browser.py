import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from sports_analysis.db.browser import BrowserIngestor
from sports_analysis.domain.events import Sport
from sports_analysis.providers.browser import CaptureError
from sports_analysis.storage.objects import LocalObjectStore
from tests.browser_fixtures import capture_data

pytestmark = pytest.mark.integration


@pytest.fixture
def ingestor(db, tmp_path):
    # Keep imported rows within the outer rollback fixture; production uses autocommit.
    db.execute("SELECT 1")
    return BrowserIngestor(db, LocalObjectStore(tmp_path))


def import_data(ingestor, data):
    return ingestor.import_bytes(json.dumps(data).encode())


def confirm_all(ingestor, db):
    ids = db.execute(
        "SELECT mapping_id FROM provider.entity_mappings WHERE mapping_method='browser_manual_v1' AND mapping_status='PENDING_REVIEW'"
    ).fetchall()
    for (identity,) in ids:
        ingestor.confirm_mapping(identity, Sport.FOOTBALL, None)


def mapped_calendar(ingestor, db):
    data = capture_data()
    pending = import_data(ingestor, data)
    assert pending.disposition == "PENDING_MAPPING"
    confirm_all(ingestor, db)
    result = ingestor.process(pending.capture_id, uuid4())
    assert result.disposition == "APPLIED"
    return data, result


def next_capture(data, **patch):
    copied = json.loads(json.dumps(data))
    copied["capture_id"] = str(uuid4())
    copied["captured_at"] = (
        datetime.fromisoformat(data["captured_at"]) + timedelta(seconds=1)
    ).isoformat()
    copied["record"].update(patch)
    return copied


def test_first_import_requires_mapping_and_is_idempotent(ingestor, db):
    data = capture_data()
    first = import_data(ingestor, data)
    assert first.disposition == "PENDING_MAPPING"
    assert import_data(ingestor, data) == first
    assert (
        db.execute("SELECT count(*) FROM ops.review_queue WHERE status='PENDING'").fetchone()[0]
        == 3
    )
    assert db.execute("SELECT count(*) FROM event.events").fetchone()[0] == 0
    data["record"]["status"] = "CANCELLED"
    with pytest.raises(CaptureError, match="different bytes"):
        import_data(ingestor, data)


def test_mapping_reprocess_available_only_after_resolution(ingestor, db):
    data = capture_data()
    pending = import_data(ingestor, data)
    decision = db.execute("SELECT clock_timestamp()").fetchone()[0]
    confirm_all(ingestor, db)
    request = uuid4()
    result = ingestor.process(pending.capture_id, request)
    assert result.disposition == "APPLIED"
    assert ingestor.process(pending.capture_id, request) == result
    history = ingestor.observations_as_of(decision)
    assert [row["disposition"] for row in history] == ["PENDING_MAPPING"]
    assert len(ingestor.observations_as_of(datetime.now(UTC) + timedelta(seconds=1))) == 2
    assert db.execute("SELECT season_id FROM event.events").fetchone()[0] is None


def test_postponement_creates_cycle_preserving_tracking_history(ingestor, db):
    data, first = mapped_calendar(ingestor, db)
    request = uuid4()
    ingestor.track(first.event_cycle_id, True, request)
    ingestor.track(first.event_cycle_id, True, request)
    with pytest.raises(CaptureError, match="conflicts"):
        ingestor.track(first.event_cycle_id, False, request)
    postponed = next_capture(data, status="POSTPONED")
    assert import_data(ingestor, postponed).event_cycle_id == first.event_cycle_id
    moved = next_capture(
        postponed, status="SCHEDULED", scheduled_start_at="2040-06-16T20:00:00-05:00"
    )
    second = import_data(ingestor, moved)
    assert second.disposition == "APPLIED"
    assert second.event_cycle_id != first.event_cycle_id
    rows = db.execute(
        "SELECT event_id,cycle_number,status,previous_cycle_id FROM event.event_cycles ORDER BY cycle_number"
    ).fetchall()
    assert rows[0][0] == rows[1][0]
    assert rows[0][2] == "POSTPONED"
    assert rows[1][1:] == (2, "TRACKING", first.event_cycle_id)
    snapshot = json.loads(ingestor.tracking_json())
    assert len(snapshot["cycles"]) == 1
    assert snapshot["cycles"][0]["tracking_status"] == "CLOSED"
    ingestor.track(second.event_cycle_id, True, uuid4())
    assert len(json.loads(ingestor.tracking_json())["cycles"]) == 2


@pytest.mark.parametrize("terminal", ["CANCELLED", "ABANDONED"])
def test_terminal_cycle_cannot_reopen_or_reschedule(ingestor, db, terminal):
    data, first = mapped_calendar(ingestor, db)
    cancelled = next_capture(data, status=terminal)
    assert import_data(ingestor, cancelled).disposition == "APPLIED"
    result = import_data(ingestor, next_capture(cancelled, status="SCHEDULED"))
    assert result.reason_code == "TERMINAL_CYCLE_CONFLICT"
    with pytest.raises(CaptureError):
        ingestor.track(first.event_cycle_id, True, uuid4())


def test_stale_capture_does_not_undo_current_state(ingestor, db):
    data, first = mapped_calendar(ingestor, db)
    moved = next_capture(data, scheduled_start_at="2040-06-18T20:00:00Z")
    second = import_data(ingestor, moved)
    stale = dict(data, capture_id=str(uuid4()))
    assert import_data(ingestor, stale).disposition == "STALE"
    assert db.execute("SELECT count(*) FROM event.event_cycles").fetchone()[0] == 2
    assert second.event_cycle_id != first.event_cycle_id


def test_identity_changes_and_duplicate_external_ids_need_review(ingestor, db):
    data, _ = mapped_calendar(ingestor, db)
    assert (
        import_data(ingestor, next_capture(data, event_id="new-external-id")).reason_code
        == "EVENT_MAPPING_AMBIGUOUS"
    )
    assert (
        import_data(
            ingestor,
            next_capture(
                data, home_id="team-2", home_name="South FC", away_id="team-1", away_name="North FC"
            ),
        ).reason_code
        == "EVENT_IDENTITY_CHANGED"
    )


def test_odds_remain_raw_unmapped_and_same_prices_keep_observations(ingestor, db):
    data = capture_data("ODDS")
    first = import_data(ingestor, data)
    assert first.disposition == "RAW_ONLY"
    second = import_data(ingestor, next_capture(data))
    assert second.capture_id != first.capture_id
    assert db.execute("SELECT count(*) FROM provider.browser_captures").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM market.odds_captures").fetchone()[0] == 0


def test_sql_receipt_clock_and_history_are_immutable(ingestor, db):
    data, result = mapped_calendar(ingestor, db)
    assert db.execute(
        "SELECT received_at>captured_at FROM provider.browser_captures WHERE capture_id=%s",
        (UUID(data["capture_id"]),),
    ).fetchone()[0]
    for query, params in [
        (
            "UPDATE provider.browser_captures SET received_at=captured_at WHERE capture_id=%s",
            (result.capture_id,),
        ),
        (
            "DELETE FROM provider.browser_observations WHERE observation_id=%s",
            (result.observation_id,),
        ),
    ]:
        with pytest.raises(psycopg.Error), db.transaction():
            db.execute(query, params)


def test_public_worker_imports_without_private_access(ingestor, db):
    db.execute("SET LOCAL ROLE sports_public_worker")
    data, result = mapped_calendar(ingestor, db)
    ingestor.track(result.event_cycle_id, True, uuid4())
    assert json.loads(ingestor.tracking_json())["schema_version"] == "tracking_v1"
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("SELECT * FROM private_betting.real_bets")
    assert import_data(ingestor, data).disposition == "PENDING_MAPPING"


def test_failed_storage_retry_reuses_receipt_and_does_not_create_events(ingestor, db, monkeypatch):
    data = capture_data()
    original = ingestor.store.put_if_absent
    monkeypatch.setattr(
        ingestor.store, "put_if_absent", lambda *args: (_ for _ in ()).throw(OSError("fixture"))
    )
    with pytest.raises(OSError):
        import_data(ingestor, data)
    received = db.execute("SELECT received_at FROM provider.browser_captures").fetchone()[0]
    assert db.execute("SELECT count(*) FROM provider.browser_observations").fetchone()[0] == 0
    monkeypatch.setattr(ingestor.store, "put_if_absent", original)
    assert import_data(ingestor, data).disposition == "PENDING_MAPPING"
    assert db.execute("SELECT received_at FROM provider.browser_captures").fetchone()[0] == received


def test_changed_mapping_name_is_queued_without_rewriting_identity(ingestor, db):
    data, first = mapped_calendar(ingestor, db)
    result = import_data(ingestor, next_capture(data, home_name="Another club"))
    assert result.reason_code == "ENTITY_MAPPING_CONFLICT"
    assert (
        db.execute(
            "SELECT reason_code FROM ops.review_queue WHERE browser_observation_id=%s",
            (result.observation_id,),
        ).fetchone()[0]
        == result.reason_code
    )
    assert db.execute("SELECT count(*) FROM event.event_cycles").fetchone()[0] == 1
    assert first.event_cycle_id is not None


def test_disabled_provider_rejected(ingestor, db):
    data = capture_data()
    import_data(ingestor, data)
    db.execute("UPDATE provider.providers SET enabled=false")
    with pytest.raises(CaptureError, match="disabled"):
        import_data(ingestor, next_capture(data))


def test_started_event_cannot_return_to_scheduled_or_change_actual_start(ingestor, db):
    data, _ = mapped_calendar(ingestor, db)
    actual = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    live = next_capture(data, status="IN_PROGRESS", actual_start_at=actual)
    assert import_data(ingestor, live).disposition == "APPLIED"
    assert (
        import_data(
            ingestor, next_capture(live, status="SCHEDULED", actual_start_at=None)
        ).reason_code
        == "STARTED_EVENT_CONFLICT"
    )
    final = next_capture(live, status="FINISHED")
    result = import_data(ingestor, final)
    assert result.disposition == "APPLIED"
    assert (
        db.execute(
            "SELECT status FROM event.event_cycles WHERE event_cycle_id=%s",
            (result.event_cycle_id,),
        ).fetchone()[0]
        == "FINALIZED"
    )
    assert db.execute("SELECT count(*) FROM event.event_results").fetchone()[0] == 0


def test_tracking_commands_cannot_be_rewritten(ingestor, db):
    _, result = mapped_calendar(ingestor, db)
    request = uuid4()
    ingestor.track(result.event_cycle_id, True, request)
    with pytest.raises(psycopg.Error), db.transaction():
        db.execute(
            "UPDATE ops.tracking_commands SET desired_status='PAUSED' WHERE request_id=%s",
            (request,),
        )


def test_concurrent_durable_import_uses_one_receipt(database_url, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from sports_analysis.db.migrate import migrate

    from .conftest import ROOT

    database_name = f"browser_test_{uuid4().hex}"
    isolated_dsn = make_conninfo(database_url, dbname=database_name)
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            migrate(isolated_dsn, ROOT / "migrations")
            payload = json.dumps(capture_data()).encode()
            store = LocalObjectStore(tmp_path)

            def ingest():
                with psycopg.connect(isolated_dsn, autocommit=True) as connection:
                    return BrowserIngestor(connection, store).import_bytes(payload)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: ingest(), range(2)))
            assert results[0] == results[1]
            with psycopg.connect(isolated_dsn) as connection:
                assert (
                    connection.execute("SELECT count(*) FROM provider.browser_captures").fetchone()[
                        0
                    ]
                    == 1
                )
                assert (
                    connection.execute(
                        "SELECT count(*) FROM provider.browser_observations"
                    ).fetchone()[0]
                    == 1
                )
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )
