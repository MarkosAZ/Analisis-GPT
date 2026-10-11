"""Manual provider ingestion with durable receipts and transactional calendar updates.

Use an autocommit connection: receipt and processing transactions must commit separately.
The short catalog lock serializes this manual provider's writes, not network requests.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sports_analysis.domain.events import Sport
from sports_analysis.domain.temporal import utc
from sports_analysis.providers.browser import (
    BrowserCapture,
    CalendarRecord,
    CaptureError,
    normalize_capture,
    parse_capture,
    raw_response,
)
from sports_analysis.storage.objects import ObjectRef, ObjectStore, sha256
from sports_analysis.storage.raw import StoredRawCapture, canonical_json, load_raw, persist_raw

_CATALOG_LOCK = 719846023102
_TERMINAL = {"FINALIZED", "POSTPONED", "CANCELLED", "ABANDONED"}


class MappingConflict(CaptureError):
    """An existing mapping cannot be safely reused for this observation."""


@dataclass(frozen=True)
class ImportResult:
    capture_id: UUID
    observation_id: UUID
    disposition: str
    reason_code: str
    event_cycle_id: UUID | None


class BrowserIngestor:
    def __init__(self, connection: psycopg.Connection[Any], store: ObjectStore) -> None:
        self.connection = connection
        self.store = store

    def _one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(query, params).fetchone()
        if row is None:
            raise CaptureError("Requested public record does not exist")
        return row

    def _lock(self) -> None:
        self.connection.execute("SET LOCAL lock_timeout = '10s'")
        self.connection.execute("SET LOCAL statement_timeout = '30s'")
        self.connection.execute("SELECT pg_advisory_xact_lock(%s)", (_CATALOG_LOCK,))

    def import_bytes(self, payload: bytes) -> ImportResult:
        capture = parse_capture(payload)
        digest = sha256(payload)
        with self.connection.transaction():
            self._lock()
            # Validate the untrusted browser clock before creating operational records.
            raw_response(payload, self._one("SELECT clock_timestamp() AS now")["now"])
            provider_row = self._one(
                """INSERT INTO provider.providers(code,name,provider_type,enabled)
                VALUES (%s,%s,%s,true) ON CONFLICT(code) DO UPDATE SET code=EXCLUDED.code
                RETURNING provider_id,enabled,name""",
                (
                    capture.provider_code,
                    capture.source_origin,
                    "SPORTS_DATA" if capture.kind == "CALENDAR" else "ODDS",
                ),
            )
            if not provider_row["enabled"] or provider_row["name"] != capture.source_origin:
                raise CaptureError("Browser provider is disabled or its identity conflicts")
            provider = provider_row["provider_id"]
            self.connection.execute(
                """INSERT INTO provider.browser_captures
                (capture_id,provider_id,content_hash,kind,source_origin,captured_at)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(capture_id) DO NOTHING""",
                (
                    capture.capture_id,
                    provider,
                    digest,
                    capture.kind,
                    capture.source_origin,
                    capture.captured_at,
                ),
            )
            receipt = self._one(
                "SELECT * FROM provider.browser_captures WHERE capture_id=%s", (capture.capture_id,)
            )
            if receipt["content_hash"] != digest:
                raise CaptureError("Capture UUID is already bound to different bytes")
        # A failed object write leaves a durable receipt; retry reuses its trusted clock.
        raw = persist_raw(
            self.store, raw_response(payload, receipt["received_at"]), capture_id=capture.capture_id
        )
        with self.connection.transaction():
            self.connection.execute(
                "UPDATE provider.browser_captures SET raw_refs=%s WHERE capture_id=%s",
                (
                    Jsonb({"payload": asdict(raw.payload), "metadata": asdict(raw.metadata)}),
                    capture.capture_id,
                ),
            )
        return self.process(capture.capture_id, capture.capture_id)

    def process(self, capture_id: UUID, request_id: UUID) -> ImportResult:
        with self.connection.transaction():
            self._lock()
            with self.connection.cursor(row_factory=dict_row) as cursor:
                prior = cursor.execute(
                    "SELECT * FROM provider.browser_observations WHERE observation_id=%s",
                    (request_id,),
                ).fetchone()
            if prior:
                if prior["capture_id"] != capture_id:
                    raise CaptureError("Request UUID is already used by a different capture")
                return self._result(prior)
            receipt = self._one(
                "SELECT * FROM provider.browser_captures WHERE capture_id=%s", (capture_id,)
            )
            if not receipt["raw_refs"]:
                raise CaptureError("RAW capture is incomplete; retry importing the original file")
            raw = StoredRawCapture(
                capture_id,
                ObjectRef(**receipt["raw_refs"]["payload"]),
                ObjectRef(**receipt["raw_refs"]["metadata"]),
            )
            response = load_raw(self.store, raw)
            capture = parse_capture(response.payload)
            temporal = normalize_capture(self.store, raw)
            if sha256(response.payload) != receipt["content_hash"]:
                raise CaptureError("Stored RAW differs from the durable receipt")
            # Preserve v1 manual manifests byte-for-byte; automatic readers get v2.
            normalizer = capture.normalizer_version
            provenance = (
                {
                    "scan_id": str(capture.scan_id),
                    "reader_version": capture.reader_version,
                    "profile_id": capture.profile_id,
                    "profile_version": capture.profile_version,
                    "profile_hash": capture.profile_hash,
                }
                if capture.scan_id
                else {}
            )
            manifest = self.store.put_if_absent(
                f"manifests/browser/{normalizer}/{capture_id}.json",
                canonical_json(
                    {
                        "schema_version": "browser_normalized_v2"
                        if capture.scan_id
                        else "browser_normalized_v1",
                        "normalizer_version": normalizer,
                        "capture_id": str(capture_id),
                        "capture_method": capture.capture_method,
                        "quality": "DOM_UNVERIFIED" if capture.scan_id else "MANUAL_UNVERIFIED",
                        **provenance,
                        "record": json.loads(response.payload)["record"],
                        "occurred_at": temporal.occurred_at.isoformat(),
                        "available_at": temporal.available_at.isoformat(),
                        "available_at_source": "OBSERVED",
                        "raw_refs": receipt["raw_refs"],
                    }
                ),
            )
            status, reason, cycle_id = ("RAW_ONLY", "ODDS_PHASE_3", None)
            if isinstance(capture.record, CalendarRecord):
                status, reason, cycle_id = self._calendar(capture, receipt["provider_id"])
            row = self._one(
                """INSERT INTO provider.browser_observations
                (observation_id,capture_id,event_cycle_id,disposition,reason_code,normalizer_version,manifest_ref)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    request_id,
                    capture_id,
                    cycle_id,
                    status,
                    reason,
                    normalizer,
                    Jsonb(asdict(manifest)),
                ),
            )
            if status == "REVIEW":
                self.connection.execute(
                    """INSERT INTO ops.review_queue(review_type,reason_code,browser_observation_id)
                    VALUES ('PROVIDER_DATA',%s,%s)""",
                    (reason, request_id),
                )
            return self._result(row)

    @staticmethod
    def _result(row: dict[str, Any]) -> ImportResult:
        return ImportResult(
            row["capture_id"],
            row["observation_id"],
            row["disposition"],
            row["reason_code"],
            row["event_cycle_id"],
        )

    def _mapping(
        self, provider: UUID, sport: Sport, kind: str, external: str, name: str
    ) -> UUID | None:
        self.connection.execute(
            """INSERT INTO provider.entity_mappings
            (provider_id,provider_entity_type,provider_entity_id,provider_name,confidence,mapping_status,mapping_method)
            VALUES (%s,%s,%s,%s,0,'PENDING_REVIEW','browser_manual_v1')
            ON CONFLICT(provider_id,provider_entity_type,provider_entity_id) DO NOTHING""",
            (provider, kind, external, name),
        )
        row = self._one(
            """SELECT entity_id,mapping_status,provider_name FROM provider.entity_mappings
            WHERE provider_id=%s AND provider_entity_type=%s AND provider_entity_id=%s""",
            (provider, kind, external),
        )
        if row["mapping_status"] == "PENDING_REVIEW":
            return None
        if row["mapping_status"] == "REJECTED" or row["provider_name"] != name:
            raise MappingConflict("Entity mapping requires review")
        table, key = (
            ("competitions", "competition_id") if kind == "COMPETITION" else ("teams", "team_id")
        )
        with self.connection.cursor() as cursor:
            match = cursor.execute(
                sql.SQL(
                    "SELECT 1 FROM catalog.{} c JOIN catalog.sports s USING(sport_id) WHERE c.{}=%s AND s.code=%s"
                ).format(sql.Identifier(table), sql.Identifier(key)),
                (row["entity_id"], sport.value),
            ).fetchone()
        if not match:
            raise MappingConflict("Mapped entity type or sport conflicts")
        identity: UUID = row["entity_id"]
        return identity

    def _calendar(self, capture: BrowserCapture, provider: UUID) -> tuple[str, str, UUID | None]:
        row = capture.record
        if not isinstance(row, CalendarRecord):
            raise CaptureError("Calendar record required")
        try:
            mapped = [
                self._mapping(provider, row.sport, kind, external, name)
                for kind, external, name in (
                    ("COMPETITION", row.competition_id, row.competition_name),
                    ("TEAM", row.home_id, row.home_name),
                    ("TEAM", row.away_id, row.away_name),
                )
            ]
        except MappingConflict:
            return "REVIEW", "ENTITY_MAPPING_CONFLICT", None
        if any(identity is None for identity in mapped):
            return "PENDING_MAPPING", "CONFIRM_ENTITY_IDENTITIES", None
        competition, home, away = mapped
        if home == away:
            return "REVIEW", "PARTICIPANT_IDENTITY_COLLISION", None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cycles = cursor.execute(
                """SELECT c.* FROM provider.event_refs r JOIN event.event_cycles c USING(event_cycle_id)
                WHERE r.provider_id=%s AND r.provider_event_id=%s ORDER BY c.cycle_number DESC""",
                (provider, row.event_id),
            ).fetchall()
            newest = cursor.execute(
                """SELECT max(c.captured_at) AS captured_at
                FROM provider.browser_observations o JOIN provider.browser_captures c USING(capture_id)
                JOIN provider.event_refs r ON r.event_cycle_id=o.event_cycle_id AND r.provider_id=c.provider_id
                WHERE c.provider_id=%s AND r.provider_event_id=%s AND o.disposition='APPLIED'""",
                (provider, row.event_id),
            ).fetchone()
        if newest and newest["captured_at"] and capture.captured_at < newest["captured_at"]:
            return "STALE", "OLDER_BROWSER_OBSERVATION", None
        target = {
            "SCHEDULED": "SCHEDULED",
            "IN_PROGRESS": "LOCKED",
            "FINISHED": "FINALIZED",
            "POSTPONED": "POSTPONED",
            "CANCELLED": "CANCELLED",
            "ABANDONED": "ABANDONED",
        }[row.status]
        now = self._one("SELECT clock_timestamp() AS now")["now"]
        if not cycles:
            # Different providers or external IDs must not silently duplicate the same fixture.
            with self.connection.cursor() as cursor:
                candidates = cursor.execute(
                    """SELECT e.event_id FROM event.events e
                    JOIN event.event_participants h ON h.event_id=e.event_id AND h.role='HOME'
                    JOIN event.event_participants a ON a.event_id=e.event_id AND a.role='AWAY'
                    JOIN event.event_cycles c ON c.event_id=e.event_id
                    WHERE e.competition_id=%s AND h.team_id=%s AND a.team_id=%s
                      AND c.scheduled_start_at=%s""",
                    (competition, home, away, row.scheduled_start_at),
                ).fetchall()
            if candidates:
                return "REVIEW", "EVENT_MAPPING_AMBIGUOUS", None
            sport_id = self._one(
                "SELECT sport_id FROM catalog.sports WHERE code=%s", (row.sport.value,)
            )["sport_id"]
            event_id = self._one(
                "INSERT INTO event.events(sport_id,competition_id) VALUES (%s,%s) RETURNING event_id",
                (sport_id, competition),
            )["event_id"]
            self.connection.execute(
                """INSERT INTO event.event_participants(event_id,team_id,role,sort_order)
                VALUES (%s,%s,'HOME',1),(%s,%s,'AWAY',2)""",
                (event_id, home, event_id, away),
            )
            cycle_id = self._new_cycle(event_id, 1, None, row, target, now)
        else:
            if len({item["event_id"] for item in cycles}) != 1:
                return "REVIEW", "EVENT_MAPPING_AMBIGUOUS", None
            current = cycles[0]
            event_id, cycle_id = current["event_id"], current["event_cycle_id"]
            identity = self._one(
                """SELECT e.competition_id,h.team_id AS home,a.team_id AS away FROM event.events e
                JOIN event.event_participants h ON h.event_id=e.event_id AND h.role='HOME'
                JOIN event.event_participants a ON a.event_id=e.event_id AND a.role='AWAY' WHERE e.event_id=%s""",
                (event_id,),
            )
            if (identity["competition_id"], identity["home"], identity["away"]) != (
                competition,
                home,
                away,
            ):
                return "REVIEW", "EVENT_IDENTITY_CHANGED", cycle_id
            rescheduled = current["scheduled_start_at"] != row.scheduled_start_at
            if rescheduled:
                # A delay observed after play starts needs human adjudication, never a new prediction cycle.
                if (
                    current["status"] not in {"SCHEDULED", "TRACKING", "POSTPONED"}
                    or target != "SCHEDULED"
                ):
                    return "REVIEW", "UNSAFE_RESCHEDULE", cycle_id
                if current["status"] != "POSTPONED":
                    self.connection.execute(
                        "UPDATE event.event_cycles SET status='POSTPONED',closed_at=%s WHERE event_cycle_id=%s",
                        (now, cycle_id),
                    )
                self.connection.execute(
                    "UPDATE event.tracking SET tracking_status='CLOSED',updated_at=%s WHERE event_cycle_id=%s",
                    (now, cycle_id),
                )
                # Selection belongs to a cycle. The new cycle requires an explicit selection.
                cycle_id = self._new_cycle(
                    event_id, current["cycle_number"] + 1, cycle_id, row, "TRACKING", now
                )
            elif current["status"] in _TERMINAL:
                if current["status"] != target or current["actual_start_at"] != row.actual_start_at:
                    return "REVIEW", "TERMINAL_CYCLE_CONFLICT", cycle_id
            else:
                if current["status"] == "LOCKED" and target in {"SCHEDULED", "POSTPONED"}:
                    return "REVIEW", "STARTED_EVENT_CONFLICT", cycle_id
                if current["actual_start_at"] and row.actual_start_at != current["actual_start_at"]:
                    return "REVIEW", "ACTUAL_START_CONFLICT", cycle_id
                if current["status"] == "TRACKING" and target == "SCHEDULED":
                    target = "TRACKING"
                self.connection.execute(
                    "UPDATE event.event_cycles SET status=%s,actual_start_at=%s,closed_at=%s WHERE event_cycle_id=%s",
                    (target, row.actual_start_at, now if target in _TERMINAL else None, cycle_id),
                )
                if target in _TERMINAL or target == "LOCKED":
                    self.connection.execute(
                        "UPDATE event.tracking SET tracking_status='CLOSED',updated_at=%s WHERE event_cycle_id=%s",
                        (now, cycle_id),
                    )
        self.connection.execute(
            """INSERT INTO provider.event_refs(provider_id,event_cycle_id,provider_event_id,first_seen_at,last_seen_at)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(provider_id,event_cycle_id) DO UPDATE SET last_seen_at=EXCLUDED.last_seen_at""",
            (provider, cycle_id, row.event_id, now, now),
        )
        return "APPLIED", "CALENDAR_UPDATED", cycle_id

    def _new_cycle(
        self,
        event: UUID,
        number: int,
        previous: UUID | None,
        row: CalendarRecord,
        status: str,
        now: datetime,
    ) -> UUID:
        result: UUID = self._one(
            """INSERT INTO event.event_cycles(event_id,cycle_number,previous_cycle_id,
            scheduled_start_at,actual_start_at,timezone_event,status,created_at,closed_at)
            VALUES (%s,%s,%s,%s,%s,'America/Lima',%s,%s,%s) RETURNING event_cycle_id""",
            (
                event,
                number,
                previous,
                row.scheduled_start_at,
                row.actual_start_at,
                status,
                now,
                now if status in _TERMINAL else None,
            ),
        )["event_cycle_id"]
        return result

    def confirm_mapping(self, mapping_id: UUID, sport: Sport, entity_id: UUID | None) -> UUID:
        """An explicit operator command confirms an existing identity or creates one."""
        with self.connection.transaction():
            self._lock()
            mapping = self._one(
                "SELECT * FROM provider.entity_mappings WHERE mapping_id=%s FOR UPDATE",
                (mapping_id,),
            )
            if (
                mapping["mapping_status"] != "PENDING_REVIEW"
                or mapping["mapping_method"] != "browser_manual_v1"
            ):
                raise CaptureError("Only a pending browser mapping may be confirmed")
            kind = mapping["provider_entity_type"]
            if kind not in {"COMPETITION", "TEAM"}:
                raise CaptureError("Unsupported entity kind")
            table, key = (
                ("competitions", "competition_id")
                if kind == "COMPETITION"
                else ("teams", "team_id")
            )
            sport_id = self._one(
                "SELECT sport_id FROM catalog.sports WHERE code=%s", (sport.value,)
            )["sport_id"]
            with self.connection.cursor() as cursor:
                if entity_id is None:
                    entity_id = uuid4()
                    cursor.execute(
                        "INSERT INTO catalog.entities(entity_id,entity_type) VALUES (%s,%s)",
                        (entity_id, kind),
                    )
                    cursor.execute(
                        sql.SQL(
                            "INSERT INTO catalog.{}({},sport_id,canonical_name) VALUES (%s,%s,%s)"
                        ).format(sql.Identifier(table), sql.Identifier(key)),
                        (entity_id, sport_id, mapping["provider_name"]),
                    )
                elif (
                    cursor.execute(
                        sql.SQL("SELECT 1 FROM catalog.{} WHERE {}=%s AND sport_id=%s").format(
                            sql.Identifier(table), sql.Identifier(key)
                        ),
                        (entity_id, sport_id),
                    ).fetchone()
                    is None
                ):
                    raise CaptureError("Entity type or sport does not match")
            self.connection.execute(
                "UPDATE provider.entity_mappings SET entity_id=%s,mapping_status='MANUAL_CONFIRMED',reviewed_at=clock_timestamp() WHERE mapping_id=%s",
                (entity_id, mapping_id),
            )
            self.connection.execute(
                "UPDATE ops.review_queue SET status='RESOLVED',resolved_at=clock_timestamp() WHERE mapping_id=%s AND status='PENDING'",
                (mapping_id,),
            )
            return entity_id

    def track(self, cycle_id: UUID, active: bool, request_id: UUID) -> None:
        desired = "ACTIVE" if active else "PAUSED"
        with self.connection.transaction():
            self._lock()
            with self.connection.cursor(row_factory=dict_row) as cursor:
                existing = cursor.execute(
                    "SELECT * FROM ops.tracking_commands WHERE request_id=%s", (request_id,)
                ).fetchone()
            if existing:
                if existing["event_cycle_id"] != cycle_id or existing["desired_status"] != desired:
                    raise CaptureError("Tracking request UUID conflicts with an earlier command")
                return
            cycle = self._one(
                "SELECT *,clock_timestamp() AS now FROM event.event_cycles WHERE event_cycle_id=%s FOR UPDATE",
                (cycle_id,),
            )
            if cycle["status"] not in {"SCHEDULED", "TRACKING"} or (
                active and cycle["scheduled_start_at"] <= cycle["now"]
            ):
                raise CaptureError("Tracking requires an open pre-match cycle")
            self.connection.execute(
                """INSERT INTO event.tracking(event_cycle_id,tracking_status,tracking_profile_version)
                VALUES (%s,%s,'manual_browser_v1') ON CONFLICT(event_cycle_id) DO UPDATE
                SET tracking_status=EXCLUDED.tracking_status,updated_at=clock_timestamp()""",
                (cycle_id, desired),
            )
            if active:
                self.connection.execute(
                    "UPDATE event.event_cycles SET status='TRACKING' WHERE event_cycle_id=%s",
                    (cycle_id,),
                )
            self.connection.execute(
                "INSERT INTO ops.tracking_commands(request_id,event_cycle_id,desired_status) VALUES (%s,%s,%s)",
                (request_id, cycle_id, desired),
            )

    def tracking_json(self) -> bytes:
        with self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute("""SELECT c.event_id,c.event_cycle_id,c.cycle_number,c.scheduled_start_at,
                c.timezone_event,c.status,t.tracking_status,t.tracking_profile_version
                FROM event.tracking t JOIN event.event_cycles c USING(event_cycle_id)
                ORDER BY c.scheduled_start_at,c.event_cycle_id""").fetchall()
            now = self._one("SELECT clock_timestamp() AS now")["now"]
        return canonical_json(
            {
                "schema_version": "tracking_v1",
                "generated_at": now.isoformat(),
                "cycles": [
                    {
                        **row,
                        "event_id": str(row["event_id"]),
                        "event_cycle_id": str(row["event_cycle_id"]),
                        "scheduled_start_at": row["scheduled_start_at"].isoformat(),
                    }
                    for row in rows
                ],
            }
        )

    def observations_as_of(self, decision_time: datetime) -> list[dict[str, Any]]:
        """History uses observation availability, never mutable current cycle rows."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """SELECT o.* FROM provider.browser_observations o
                WHERE o.available_at <= %s ORDER BY o.available_at,o.observation_id""",
                (utc(decision_time),),
            ).fetchall()
