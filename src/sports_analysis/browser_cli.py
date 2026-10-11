"""Local commands; credentials stay in the environment, never the extension."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from sports_analysis.config import Settings
from sports_analysis.db.browser import BrowserIngestor
from sports_analysis.db.public_calendar import export_public_calendar
from sports_analysis.domain.events import Sport
from sports_analysis.providers.browser import MAX_CAPTURE_BYTES, MAX_SCAN_BYTES, parse_scan
from sports_analysis.storage.objects import LocalObjectStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Import reviewed public browser captures")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import")
    ingest.add_argument("file", type=Path)
    scan_ingest = commands.add_parser("import-scan")
    scan_ingest.add_argument("file", type=Path)
    process = commands.add_parser("reprocess")
    process.add_argument("capture_id", type=UUID)
    process.add_argument("--request-id", type=UUID, required=True)
    commands.add_parser("pending-mappings")
    mapping = commands.add_parser("map-entity")
    mapping.add_argument("mapping_id", type=UUID)
    mapping.add_argument("--sport", choices=[sport.value for sport in Sport], required=True)
    target = mapping.add_mutually_exclusive_group(required=True)
    target.add_argument("--entity-id", type=UUID)
    target.add_argument("--create", action="store_true")
    track = commands.add_parser("track")
    track.add_argument("cycle_id", type=UUID)
    track.add_argument("--status", choices=["ACTIVE", "PAUSED"], required=True)
    track.add_argument("--request-id", type=UUID, required=True)
    export = commands.add_parser("export-tracking")
    export.add_argument("output", type=Path)
    site_export = commands.add_parser("export-calendar")
    site_export.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if not settings.database_url:
            raise ValueError("Missing database setting")
        with psycopg.connect(settings.database_url.reveal(), autocommit=True) as connection:
            ingestor = BrowserIngestor(connection, LocalObjectStore(settings.object_root))
            if args.command == "import":
                with args.file.open("rb") as handle:
                    payload = handle.read(MAX_CAPTURE_BYTES + 1)
                result = ingestor.import_bytes(payload)
                print(json.dumps(asdict(result), default=str))
            elif args.command == "import-scan":
                with args.file.open("rb") as handle:
                    members = parse_scan(handle.read(MAX_SCAN_BYTES + 1))
                for payload in members:
                    result = ingestor.import_bytes(payload)
                    print(json.dumps(asdict(result), default=str))
            elif args.command == "reprocess":
                print(
                    json.dumps(
                        asdict(ingestor.process(args.capture_id, args.request_id)), default=str
                    )
                )
            elif args.command == "pending-mappings":
                with connection.cursor(row_factory=dict_row) as cursor:
                    records = cursor.execute("""SELECT mapping_id,provider_entity_type,provider_entity_id,provider_name
                        FROM provider.entity_mappings WHERE mapping_method='browser_manual_v1'
                        AND mapping_status='PENDING_REVIEW' ORDER BY mapping_id""").fetchall()
                print(json.dumps(records, default=str, ensure_ascii=False))
            elif args.command == "map-entity":
                print(ingestor.confirm_mapping(args.mapping_id, Sport(args.sport), args.entity_id))
            elif args.command == "track":
                ingestor.track(args.cycle_id, args.status == "ACTIVE", args.request_id)
                print("Tracking command applied.")
            elif args.command == "export-tracking":
                # Refuse to overwrite an existing document or follow a destination symlink.
                with args.output.open("xb") as handle:
                    handle.write(ingestor.tracking_json() + b"\n")
                print("Public tracking snapshot exported.")
            elif args.command == "export-calendar":
                payload = export_public_calendar(connection)
                with args.output.open("xb") as handle:
                    handle.write(payload + b"\n")
                print("Public calendar snapshot exported.")
    except (psycopg.Error, OSError, ValueError):
        parser.exit(
            1,
            "Operation failed. Check capture schema, mappings, migrations and environment settings; input and connection details are not logged.\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
