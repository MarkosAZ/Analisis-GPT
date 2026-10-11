import json
from uuid import uuid4

import pytest

from sports_analysis.db.browser import BrowserIngestor
from sports_analysis.db.public_calendar import export_public_calendar
from sports_analysis.domain.events import Sport
from sports_analysis.public_calendar import FIELDS, load_public_calendar
from sports_analysis.storage.objects import LocalObjectStore
from tests.browser_fixtures import capture_data

pytestmark = pytest.mark.integration


def test_public_export_uses_worker_role_and_preserves_cycles(db, tmp_path):
    db.execute("SET LOCAL ROLE sports_public_worker")
    ingestor = BrowserIngestor(db, LocalObjectStore(tmp_path))
    data = capture_data()
    pending = ingestor.import_bytes(json.dumps(data).encode())
    assert load_public_calendar(export_public_calendar(db))["cycles"] == []
    mappings = db.execute(
        "SELECT mapping_id FROM provider.entity_mappings WHERE mapping_status='PENDING_REVIEW'"
    ).fetchall()
    for (identity,) in mappings:
        ingestor.confirm_mapping(identity, Sport.FOOTBALL, None)
    applied = ingestor.process(pending.capture_id, uuid4())
    ingestor.track(applied.event_cycle_id, True, uuid4())
    initial = load_public_calendar(export_public_calendar(db))
    assert initial["data_kind"] == "PUBLIC"
    assert len(initial["cycles"]) == 1
    assert set(initial["cycles"][0]) == FIELDS
    assert initial["cycles"][0]["home"] == "North FC"
    assert initial["cycles"][0]["tracking_status"] == "ACTIVE"
    data["capture_id"] = str(uuid4())
    data["record"]["scheduled_start_at"] = "2040-06-18T20:00:00-05:00"
    moved = ingestor.import_bytes(json.dumps(data).encode())
    result = load_public_calendar(export_public_calendar(db))
    assert len(result["cycles"]) == 2
    by_id = {row["event_cycle_id"]: row for row in result["cycles"]}
    assert by_id[str(applied.event_cycle_id)]["status"] == "POSTPONED"
    assert by_id[str(moved.event_cycle_id)]["previous_cycle_id"] == str(applied.event_cycle_id)
    assert "raw_refs" not in result and "source_origin" not in result
