"""One consistent SQL statement exports only explicitly public calendar fields."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from sports_analysis.public_calendar import MAX_CYCLES, SCHEMA, validate_public_calendar
from sports_analysis.storage.raw import canonical_json


def export_public_calendar(connection: psycopg.Connection[Any]) -> bytes:
    with connection.cursor(row_factory=dict_row) as cursor:
        result = cursor.execute(
            """WITH public_cycles AS (
                SELECT c.event_id,c.event_cycle_id,c.cycle_number,c.previous_cycle_id,
                       s.code AS sport,p.canonical_name AS competition,
                       h.canonical_name AS home,a.canonical_name AS away,
                       c.scheduled_start_at,c.actual_start_at,c.status,t.tracking_status,
                       observation.last_observed_at
                FROM event.event_cycles c
                JOIN event.events e USING(event_id)
                JOIN catalog.sports s ON s.sport_id=e.sport_id
                JOIN catalog.competitions p ON p.competition_id=e.competition_id
                JOIN event.event_participants hp ON hp.event_id=e.event_id AND hp.role='HOME'
                JOIN catalog.teams h ON h.team_id=hp.team_id
                JOIN event.event_participants ap ON ap.event_id=e.event_id AND ap.role='AWAY'
                JOIN catalog.teams a ON a.team_id=ap.team_id
                LEFT JOIN event.tracking t ON t.event_cycle_id=c.event_cycle_id
                JOIN LATERAL (
                    SELECT max(o.available_at) AS last_observed_at
                    FROM provider.browser_observations o
                    WHERE o.event_cycle_id=c.event_cycle_id AND o.disposition='APPLIED'
                ) observation ON observation.last_observed_at IS NOT NULL
                ORDER BY c.scheduled_start_at,c.event_cycle_id LIMIT %s
            ) SELECT clock_timestamp() AS generated_at,
                     COALESCE(jsonb_agg(to_jsonb(public_cycles)
                       ORDER BY scheduled_start_at,event_cycle_id), '[]'::jsonb) AS cycles
              FROM public_cycles""",
            (MAX_CYCLES + 1,),
        ).fetchone()
    if result is None:
        raise ValueError("Public calendar query did not return a snapshot")
    data = {
        "schema_version": SCHEMA,
        "data_kind": "PUBLIC",
        "display_timezone": "America/Lima",
        "generated_at": result["generated_at"].isoformat(),
        "cycles": result["cycles"],
    }
    return canonical_json(validate_public_calendar(data))
