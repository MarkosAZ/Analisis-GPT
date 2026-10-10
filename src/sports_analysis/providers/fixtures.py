"""Offline adapter and small normalizer for exercising RAW -> NORMALIZED."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Protocol
from uuid import UUID

from sports_analysis.domain.temporal import AvailableAtSource, TemporalRecord, utc
from sports_analysis.providers.base import ProviderRequest, RawResponse, validate_label
from sports_analysis.storage.objects import ObjectStore
from sports_analysis.storage.raw import StoredRawCapture, load_raw


def _now() -> datetime:
    return datetime.now(UTC)


class FixtureProvider:
    """Explicit offline data; no endpoints, credential discovery, or HTTP requests."""

    def __init__(
        self, fixtures: Mapping[str, bytes], *, clock: Callable[[], datetime] = _now
    ) -> None:
        self._fixtures = dict(fixtures)
        self._clock = clock

    def _fetch(self, request: ProviderRequest) -> RawResponse:
        try:
            payload = self._fixtures[request.endpoint]
        except KeyError:
            raise ValueError("No fixture registered for logical route") from None
        return RawResponse("fixture", request, self._clock(), "fixture_adapter_v1", "1", payload)

    def fetch_calendar(self, request: ProviderRequest) -> RawResponse:
        return self._fetch(request)

    def fetch_event_data(self, request: ProviderRequest) -> RawResponse:
        return self._fetch(request)

    def fetch_odds(self, request: ProviderRequest) -> RawResponse:
        return self._fetch(request)

    def fetch_news(self, request: ProviderRequest) -> RawResponse:
        return self._fetch(request)

    def fetch_weather(self, request: ProviderRequest) -> RawResponse:
        return self._fetch(request)


class Normalizer[T](Protocol):
    def normalize(
        self, capture: StoredRawCapture, store: ObjectStore
    ) -> tuple[TemporalRecord[T], ...]: ...


@dataclass(frozen=True)
class NormalizedStat:
    entity_id: UUID
    metric: str
    value: float
    raw_capture_id: UUID
    raw_content_hash: str
    normalizer_version: str


class FixtureStatsNormalizer:
    """Fixture schema only, not a live sports integration or a feature pipeline.

    OBSERVED timestamps are conservative: data fetched today cannot claim it was
    observed yesterday. Historical reconstructed availability must say ESTIMATED.
    """

    version = "fixture_stats_normalizer_v1"

    def normalize(
        self, capture: StoredRawCapture, store: ObjectStore
    ) -> tuple[TemporalRecord[NormalizedStat], ...]:
        raw = load_raw(store, capture)
        if raw.provider != "fixture" or raw.schema_version != "1":
            raise ValueError("RAW metadata does not match the fixture capture")
        records: list[TemporalRecord[NormalizedStat]] = []
        try:
            decoded = json.loads(raw.payload)
            if not isinstance(decoded, list):
                raise ValueError
            for row in decoded:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row["logical_key"], str)
                    or not row["logical_key"].strip()
                    or type(row["revision"]) is not int
                    or row["revision"] < 1
                    or type(row["value"]) not in {int, float}
                    or not isinstance(row["metric"], str)
                ):
                    raise ValueError
                validate_label(row["metric"])
                value = float(row["value"])
                if not isfinite(value):
                    raise ValueError
                source = AvailableAtSource(row["available_at_source"])
                available = utc(datetime.fromisoformat(row["available_at"]))
                if source == AvailableAtSource.OBSERVED:
                    available = max(available, raw.fetched_at)
                stat = NormalizedStat(
                    UUID(row["entity_id"]),
                    row["metric"],
                    value,
                    capture.capture_id,
                    capture.payload.content_hash,
                    self.version,
                )
                records.append(
                    TemporalRecord(
                        row["logical_key"],
                        row["revision"],
                        stat,
                        datetime.fromisoformat(row["occurred_at"]),
                        available,
                        source,
                    )
                )
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise ValueError("Invalid fixture statistics payload") from None
        return tuple(records)
