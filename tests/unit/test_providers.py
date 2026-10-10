import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from sports_analysis.domain.temporal import AvailableAtSource, as_of
from sports_analysis.providers.base import (
    NewsProvider,
    OddsProvider,
    ProviderRequest,
    SportsDataProvider,
    WeatherProvider,
    safe_parameters,
)
from sports_analysis.providers.fixtures import FixtureProvider, FixtureStatsNormalizer
from sports_analysis.storage.objects import LocalObjectStore, ObjectIntegrityError
from sports_analysis.storage.raw import persist_raw


def test_fixture_adapter_supports_all_provider_contracts() -> None:
    fixtures = FixtureProvider({"sample": b"[]"})
    sports: SportsDataProvider = fixtures
    odds: OddsProvider = fixtures
    news: NewsProvider = fixtures
    weather: WeatherProvider = fixtures
    request = ProviderRequest("sample")
    assert sports.fetch_calendar(request).payload == b"[]"
    assert sports.fetch_event_data(request).provider == "fixture"
    assert odds.fetch_odds(request).payload == b"[]"
    assert news.fetch_news(request).payload == b"[]"
    assert weather.fetch_weather(request).payload == b"[]"


def test_credentials_and_arbitrary_metadata_are_not_persistable() -> None:
    parameters = safe_parameters(
        {
            "event_id": "123",
            "token": "private",
            "password": "private",
            "dsn": "postgresql://private",
            "Authorization": "Bearer private",
            "unknown": "value",
        }
    )
    assert parameters == (("event_id", "123"),)
    for endpoint in ("https://user:private@api.example/events", "events?api_key=private"):
        with pytest.raises(ValueError) as error:
            ProviderRequest(endpoint)
        assert "private" not in str(error.value)
    with pytest.raises(ValueError):
        safe_parameters({"event_id": "https://user:private@example.com"})


def fixture_payload(source: str, time: datetime) -> bytes:
    return json.dumps(
        [
            {
                "entity_id": str(uuid4()),
                "logical_key": "entity:shots:2026-01-01",
                "revision": 1,
                "metric": "shots",
                "value": 10,
                "occurred_at": time.isoformat(),
                "available_at": time.isoformat(),
                "available_at_source": source,
            }
        ]
    ).encode()


def test_observed_normalization_cannot_backdate_to_before_fetch(tmp_path: Path) -> None:
    occurred = datetime(2026, 1, 1, tzinfo=UTC)
    fetched = occurred + timedelta(days=1)
    provider = FixtureProvider(
        {"stats": fixture_payload("OBSERVED", occurred)}, clock=lambda: fetched
    )
    store = LocalObjectStore(tmp_path)
    capture = persist_raw(store, provider.fetch_event_data(ProviderRequest("stats")))
    records = FixtureStatsNormalizer().normalize(capture, store)
    assert as_of(records, occurred).records == ()
    visible = as_of(records, fetched).records[0]
    assert visible.available_at == fetched
    assert visible.value.raw_capture_id == capture.capture_id
    assert visible.value.raw_content_hash == capture.payload.content_hash
    assert visible.value.normalizer_version == "fixture_stats_normalizer_v1"
    assert visible.available_at_source == AvailableAtSource.OBSERVED


def test_reconstruction_keeps_estimated_provenance(tmp_path: Path) -> None:
    available = datetime(2026, 1, 1, tzinfo=UTC)
    provider = FixtureProvider(
        {"stats": fixture_payload("ESTIMATED", available)},
        clock=lambda: available + timedelta(days=365),
    )
    store = LocalObjectStore(tmp_path)
    capture = persist_raw(store, provider.fetch_event_data(ProviderRequest("stats")))
    records = FixtureStatsNormalizer().normalize(capture, store)
    assert as_of(records, available).estimated_fraction == 1.0


def test_normalization_requires_intact_persisted_raw(tmp_path: Path) -> None:
    provider = FixtureProvider({"stats": b"[]"})
    store = LocalObjectStore(tmp_path)
    capture = persist_raw(store, provider.fetch_event_data(ProviderRequest("stats")))
    (tmp_path / capture.payload.key).write_bytes(b"corrupted")
    with pytest.raises(ObjectIntegrityError):
        FixtureStatsNormalizer().normalize(capture, store)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metric", ["mutable"]),
        ("value", True),
        ("value", "private-nonnumeric"),
        ("value", float("nan")),
        ("revision", True),
        ("revision", 1.1),
        ("revision", 0),
        ("logical_key", []),
        ("logical_key", " "),
        ("entity_id", 7),
        ("available_at", "private-invalid-time"),
    ],
)
def test_normalizer_rejects_untyped_fields_without_echoing_data(
    tmp_path: Path, field: str, value: object
) -> None:
    occurred = datetime(2026, 1, 1, tzinfo=UTC)
    rows = json.loads(fixture_payload("OBSERVED", occurred))
    rows[0][field] = value
    provider = FixtureProvider({"stats": json.dumps(rows).encode()})
    store = LocalObjectStore(tmp_path)
    capture = persist_raw(store, provider.fetch_event_data(ProviderRequest("stats")))
    with pytest.raises(ValueError, match="Invalid fixture statistics payload") as error:
        FixtureStatsNormalizer().normalize(capture, store)
    assert "private" not in str(error.value)
