import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sports_analysis.db.browser import BrowserIngestor
from sports_analysis.domain.events import Sport
from sports_analysis.providers.browser import parse_scan
from sports_analysis.storage.objects import LocalObjectStore, ObjectRef
from tests.browser_fixtures import automatic_data, scan_data

pytestmark = pytest.mark.integration


def test_automatic_batch_ingestion_is_idempotent_and_preserves_mapping_availability(db, tmp_path):
    db.execute("SET LOCAL ROLE sports_public_worker")
    store = LocalObjectStore(tmp_path)
    ingestor = BrowserIngestor(db, store)
    payload = json.dumps(scan_data()).encode()
    member = parse_scan(payload)[0]
    first = ingestor.import_bytes(member)
    assert first.disposition == "PENDING_MAPPING"
    assert ingestor.import_bytes(parse_scan(payload)[0]) == first
    at = db.execute("SELECT clock_timestamp()").fetchone()[0]
    for (identity,) in db.execute(
        "SELECT mapping_id FROM provider.entity_mappings WHERE mapping_status='PENDING_REVIEW'"
    ).fetchall():
        ingestor.confirm_mapping(identity, Sport.FOOTBALL, None)
    applied = ingestor.process(first.capture_id, uuid4())
    assert applied.disposition == "APPLIED"
    assert [row["disposition"] for row in ingestor.observations_as_of(at)] == ["PENDING_MAPPING"]
    assert ingestor.observations_as_of(datetime.now(UTC) - timedelta(minutes=2)) == []
    ref, version = db.execute(
        "SELECT manifest_ref, normalizer_version FROM provider.browser_observations WHERE observation_id=%s",
        (first.observation_id,),
    ).fetchone()
    assert version == "browser_normalizer_v2"
    manifest = json.loads(store.get(ObjectRef(**ref)))
    assert manifest["quality"] == "DOM_UNVERIFIED"
    assert manifest["capture_method"] == "AUTOMATIC_DOM"
    assert manifest["reader_version"] == "dom_fields_v1"
    assert manifest["profile_hash"] == "a" * 64


def test_automatic_odds_stay_raw_only(db, tmp_path):
    db.execute("SET LOCAL ROLE sports_public_worker")
    ingestor = BrowserIngestor(db, LocalObjectStore(tmp_path))
    data = automatic_data("ODDS")
    data["record"].update(line_type="ASIAN_QUARTER", line="2.25")
    result = ingestor.import_bytes(json.dumps(data).encode())
    assert result.disposition == "RAW_ONLY"
    assert db.execute("SELECT count(*) FROM market.odds_captures").fetchone()[0] == 0
