"""Configuration with explicit secret access and safe string representations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Configuration errors name the setting, never its contents."""


class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Pass directly to the integration client; never log this result."""
        return self._value

    def __repr__(self) -> str:
        return "Secret(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


@dataclass(frozen=True)
class Settings:
    object_root: Path
    database_url: Secret | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        environment = os.environ if environ is None else environ
        root = environment.get("SPORTS_OBJECT_ROOT", ".local/object-storage")
        if not root or "\x00" in root or "://" in root:
            raise ConfigurationError("SPORTS_OBJECT_ROOT must be a local filesystem path")
        database_url = environment.get("DATABASE_URL")
        if database_url:
            try:
                parsed = urlsplit(database_url)
                valid = (
                    parsed.scheme in {"postgresql", "postgres"}
                    and bool(parsed.path.strip("/"))
                    and not parsed.fragment
                    and "\n" not in database_url
                    and "\r" not in database_url
                )
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ConfigurationError(
                    "DATABASE_URL must be a PostgreSQL connection URI"
                ) from None
        return cls(Path(root), Secret(database_url) if database_url else None)
