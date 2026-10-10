"""Transactional, checksum-verified migrations for a repository checkout.

The CLI reads DATABASE_URL only from the environment and intentionally avoids
logging driver exceptions, which can contain credentials or server details.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import psycopg


class MigrationError(ValueError):
    """A migration history cannot be safely reproduced."""


def migrate(dsn: str, directory: Path) -> tuple[str, ...]:
    """Apply new SQL files atomically; refuse modified or missing history.

    Call only with owner credentials on a database selected by the caller.
    Uses an advisory transaction lock so concurrent setup cannot double-apply.
    """
    paths = sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not paths:
        raise MigrationError("No migration files found")
    if len({p.name[:4] for p in paths}) != len(paths):
        raise MigrationError("Duplicate migration version")
    sources = {p.name: p.read_bytes() for p in paths}
    applied: list[str] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(719846023101)")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS ops")
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS ops.schema_migrations (
                name text PRIMARY KEY,
                sha256 text NOT NULL CHECK (length(sha256) = 64),
                applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
            )"""
        )
        cursor.execute("SELECT name, sha256 FROM ops.schema_migrations ORDER BY name")
        existing: dict[str, str] = dict(cursor.fetchall())
        for name, checksum in existing.items():
            if name not in sources or hashlib.sha256(sources[name]).hexdigest() != checksum:
                raise MigrationError("Applied migration history differs from source")
        for name, source in sources.items():
            if name in existing:
                continue
            if existing and name < max(existing):
                raise MigrationError("New migrations must follow applied versions")
            cursor.execute(source.decode("utf-8"))
            cursor.execute(
                "INSERT INTO ops.schema_migrations (name, sha256) VALUES (%s, %s)",
                (name, hashlib.sha256(source).hexdigest()),
            )
            applied.append(name)
        cursor.execute("REVOKE ALL ON ops.schema_migrations FROM PUBLIC")
    return tuple(applied)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply checked PostgreSQL migrations")
    parser.add_argument("--directory", type=Path, default=Path("migrations"))
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.exit(2, "DATABASE_URL is required; configure it securely in the environment.\n")
    try:
        applied = migrate(dsn, args.directory)
    except (psycopg.Error, OSError, ValueError):
        parser.exit(1, "Migration failed; verify database access and migration history securely.\n")
    print(f"Migration validation complete; {len(applied)} new migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
