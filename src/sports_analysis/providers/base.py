"""Provider contracts return RAW bytes; normalization happens after persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Protocol

from sports_analysis.domain.temporal import utc

ParameterValue = str | int | float | bool
SafeParameters = tuple[tuple[str, ParameterValue], ...]

# Authentication headers and arbitrary query parameters never enter audit metadata.
# New providers extend this list deliberately, after checking whether a key is public.
PUBLIC_PARAMETER_NAMES = frozenset(
    {
        "sport",
        "event_id",
        "competition_id",
        "season_id",
        "team_id",
        "player_id",
        "venue_id",
        "date",
        "from_date",
        "to_date",
        "market",
        "page",
        "limit",
        "locale",
        "country",
        "latitude",
        "longitude",
        "units",
    }
)


def safe_parameters(parameters: Mapping[str, ParameterValue]) -> SafeParameters:
    sanitized: list[tuple[str, ParameterValue]] = []
    for key, value in sorted(parameters.items()):
        if key not in PUBLIC_PARAMETER_NAMES:
            continue
        if isinstance(value, str):
            if re.fullmatch(r"[A-Za-z0-9_.:+-]{1,128}", value) is None:
                raise ValueError("Invalid public provider parameter")
        elif isinstance(value, float):
            if not isfinite(value):
                raise ValueError("Invalid public provider parameter")
        elif not isinstance(value, (int, bool)):
            raise ValueError("Invalid public provider parameter")
        sanitized.append((key, value))
    return tuple(sanitized)


def validate_label(value: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) is None or value in {".", ".."}:
        raise ValueError("Invalid provider/version identifier")


@dataclass(frozen=True)
class ProviderRequest:
    endpoint: str
    params: SafeParameters = ()

    def __post_init__(self) -> None:
        # Endpoint is a logical adapter route, never a URL or credential-bearing query.
        if re.fullmatch(r"[A-Za-z0-9_/-]{1,160}", self.endpoint) is None or "//" in self.endpoint:
            raise ValueError("Provider endpoint must be a logical route")
        if len(dict(self.params)) != len(self.params):
            raise ValueError("Duplicate public provider parameters")
        object.__setattr__(self, "params", safe_parameters(dict(self.params)))


@dataclass(frozen=True)
class RawResponse:
    provider: str
    request: ProviderRequest
    fetched_at: datetime
    adapter_version: str
    schema_version: str
    payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.provider, self.adapter_version, self.schema_version):
            validate_label(value)
        object.__setattr__(self, "fetched_at", utc(self.fetched_at))
        if not isinstance(self.payload, bytes):
            raise ValueError("RAW payload must be immutable bytes")


class SportsDataProvider(Protocol):
    def fetch_calendar(self, request: ProviderRequest) -> RawResponse: ...

    def fetch_event_data(self, request: ProviderRequest) -> RawResponse: ...


class OddsProvider(Protocol):
    def fetch_odds(self, request: ProviderRequest) -> RawResponse: ...


class NewsProvider(Protocol):
    def fetch_news(self, request: ProviderRequest) -> RawResponse: ...


class WeatherProvider(Protocol):
    def fetch_weather(self, request: ProviderRequest) -> RawResponse: ...
