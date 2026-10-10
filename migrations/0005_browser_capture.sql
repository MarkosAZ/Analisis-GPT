-- A browser timestamp is a claim. The trusted receipt clock defines availability.
CREATE TABLE provider.browser_captures (
    capture_id uuid PRIMARY KEY,
    provider_id uuid NOT NULL REFERENCES provider.providers,
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    kind text NOT NULL CHECK (kind IN ('CALENDAR','ODDS')),
    source_origin text NOT NULL,
    captured_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    raw_refs jsonb,
    CHECK (received_at >= captured_at),
    CHECK (raw_refs IS NULL OR jsonb_typeof(raw_refs) = 'object')
);
CREATE TABLE provider.browser_observations (
    observation_id uuid PRIMARY KEY,
    capture_id uuid NOT NULL REFERENCES provider.browser_captures,
    event_cycle_id uuid REFERENCES event.event_cycles,
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    disposition text NOT NULL CHECK (disposition IN ('APPLIED','PENDING_MAPPING','REVIEW','STALE','RAW_ONLY')),
    reason_code text NOT NULL,
    normalizer_version text NOT NULL,
    manifest_ref jsonb NOT NULL CHECK (jsonb_typeof(manifest_ref) = 'object'),
    CHECK (disposition <> 'APPLIED' OR event_cycle_id IS NOT NULL)
);
CREATE INDEX browser_observations_as_of ON provider.browser_observations(available_at);
CREATE TABLE ops.tracking_commands (
    request_id uuid PRIMARY KEY,
    event_cycle_id uuid NOT NULL REFERENCES event.event_cycles,
    desired_status text NOT NULL CHECK (desired_status IN ('ACTIVE','PAUSED')),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION provider.guard_browser_capture() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'browser capture receipts are immutable';
    END IF;
    IF TG_OP = 'INSERT' THEN
        -- Never accept a caller-provided availability for a new receipt.
        NEW.received_at := clock_timestamp();
    ELSIF (to_jsonb(NEW) - 'raw_refs') IS DISTINCT FROM (to_jsonb(OLD) - 'raw_refs')
          OR (OLD.raw_refs IS NOT NULL AND NEW.raw_refs IS DISTINCT FROM OLD.raw_refs) THEN
        RAISE EXCEPTION 'browser capture identity and provenance are immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER browser_capture_receipt BEFORE INSERT OR UPDATE OR DELETE
ON provider.browser_captures FOR EACH ROW EXECUTE FUNCTION provider.guard_browser_capture();

CREATE FUNCTION provider.guard_browser_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'browser observations are immutable'; END IF;
    NEW.available_at := clock_timestamp();
    IF NOT EXISTS (SELECT 1 FROM provider.browser_captures c
        WHERE c.capture_id = NEW.capture_id AND c.raw_refs IS NOT NULL
          AND c.received_at <= NEW.available_at) THEN
        RAISE EXCEPTION 'persist RAW before recording a browser observation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER browser_observation_history BEFORE INSERT OR UPDATE OR DELETE
ON provider.browser_observations FOR EACH ROW EXECUTE FUNCTION provider.guard_browser_observation();

REVOKE ALL ON provider.browser_captures, provider.browser_observations, ops.tracking_commands FROM PUBLIC;
GRANT SELECT, INSERT ON provider.browser_captures, provider.browser_observations TO sports_public_worker;
GRANT UPDATE(raw_refs) ON provider.browser_captures TO sports_public_worker;
GRANT SELECT, INSERT ON ops.tracking_commands TO sports_public_worker;
GRANT SELECT ON provider.browser_captures, provider.browser_observations TO model_training_worker;
-- This migration adds no privilege on private_betting and no browser credentials.
