-- Run as the database migration owner, never as a workflow's runtime identity.
-- Runtime LOGIN roles are provisioned separately and receive ONE of these groups.
DO $$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['sports_public_worker','private_bets_worker','model_training_worker'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS', role_name);
        ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name AND
            (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolcanlogin)) THEN
            RAISE EXCEPTION 'unsafe existing runtime group attributes';
        END IF;
    END LOOP;
END;
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$
DECLARE schema_name text;
BEGIN
    FOREACH schema_name IN ARRAY ARRAY['catalog','provider','event','market','analysis','ml','paper','private_betting','ops'] LOOP
        EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', schema_name);
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC', schema_name);
        EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC', schema_name);
        EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM PUBLIC', schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM PUBLIC', schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM PUBLIC', schema_name);
    END LOOP;
END;
$$;
-- Function EXECUTE defaults are global; a schema-local revoke alone cannot
-- remove PostgreSQL's global PUBLIC default. Applies to this migration owner.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

GRANT USAGE ON SCHEMA catalog, provider, event, market, analysis, ml, paper, ops TO sports_public_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA catalog, provider, event, market, analysis, paper TO sports_public_worker;
GRANT SELECT ON ALL TABLES IN SCHEMA ml TO sports_public_worker;
GRANT SELECT, INSERT, UPDATE ON ops.review_queue, ops.github_runs, ops.cron_slots, ops.page_deployments TO sports_public_worker;
GRANT SELECT ON ops.event_locks TO sports_public_worker;
GRANT EXECUTE ON FUNCTION ops.acquire_event_lock(uuid,uuid,interval),
    ops.heartbeat_event_lock(uuid,uuid,bigint,interval),
    ops.release_event_lock(uuid,uuid,bigint) TO sports_public_worker;
-- Call inside the SAME transaction before persisting analysis output. The row
-- lock prevents a successor taking ownership while that transaction commits.
CREATE FUNCTION ops.assert_event_lock(cycle uuid, owner_run uuid, fence bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    PERFORM 1 FROM ops.event_locks WHERE event_cycle_id = cycle
        AND owner_analysis_run_id = owner_run AND fencing_token = fence
        AND expires_at > clock_timestamp() FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event lock ownership lost or expired' USING ERRCODE = '55000';
    END IF;
END;
$$;
GRANT EXECUTE ON FUNCTION ops.assert_event_lock(uuid,uuid,bigint) TO sports_public_worker;
-- Governed policies are promoted with a separate administrative identity.
REVOKE INSERT, UPDATE, DELETE ON paper.paper_policies FROM sports_public_worker;
REVOKE ALL ON ops.schema_migrations FROM sports_public_worker, private_bets_worker, model_training_worker;

GRANT USAGE ON SCHEMA catalog, provider, event, market, analysis, ml TO model_training_worker;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog, provider, event, market, analysis, ml TO model_training_worker;
GRANT INSERT, UPDATE ON ml.model_families, ml.model_versions, ml.experiment_runs, ml.backtest_runs TO model_training_worker;
-- Model deployment, window creation/unlocking and policy activation remain owner-only.

GRANT USAGE ON SCHEMA private_betting, analysis, event, market TO private_bets_worker;
GRANT SELECT ON analysis.model_predictions, analysis.prediction_outcomes, analysis.analysis_markets,
    analysis.analysis_runs, event.events, event.event_cycles, event.event_results, market.bookmakers TO private_bets_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA private_betting TO private_bets_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA private_betting
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO private_bets_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA private_betting
    GRANT USAGE, SELECT ON SEQUENCES TO private_bets_worker;
REVOKE ALL ON SCHEMA private_betting FROM sports_public_worker, model_training_worker;
REVOKE ALL ON ALL TABLES IN SCHEMA private_betting FROM sports_public_worker, model_training_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA private_betting FROM sports_public_worker, model_training_worker;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA private_betting FROM sports_public_worker, model_training_worker;

-- The owner is the only identity that can explicitly unlock a protected window.
-- Record the manual administrative workflow run, without accepting a claimed user.
CREATE FUNCTION ml.unlock_holdout(target_window uuid, manual_workflow_run bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF manual_workflow_run IS NULL OR manual_workflow_run <= 0 THEN
        RAISE EXCEPTION 'manual workflow run identifier is required' USING ERRCODE = '22023';
    END IF;
    UPDATE ml.evaluation_windows SET locked = false, unlocked_at = clock_timestamp(),
        unlocked_by_run_id = manual_workflow_run
        WHERE window_id = target_window AND window_type = 'HOLDOUT' AND locked;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'holdout does not exist or is already unlocked' USING ERRCODE = '22023';
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION ml.unlock_holdout(uuid,bigint) FROM PUBLIC, sports_public_worker, private_bets_worker, model_training_worker;

-- These functions return eligibility only; they never expose protected metrics.
CREATE FUNCTION ml.evaluation_time_is_open(moment timestamptz)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT moment IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM ml.evaluation_windows
        WHERE window_type = 'HOLDOUT' AND locked AND moment >= starts_at AND moment < ends_at
    );
$$;
GRANT EXECUTE ON FUNCTION ml.evaluation_time_is_open(timestamptz)
    TO sports_public_worker, model_training_worker, private_bets_worker;

ALTER TABLE ml.evaluation_windows ENABLE ROW LEVEL SECURITY;
CREATE POLICY unlocked_windows ON ml.evaluation_windows FOR SELECT
    TO sports_public_worker, model_training_worker USING (NOT locked);
ALTER TABLE event.event_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY result_visibility ON event.event_results FOR SELECT
    TO sports_public_worker, model_training_worker, private_bets_worker
    USING (ml.evaluation_time_is_open(occurred_at));
CREATE POLICY result_ingestion ON event.event_results FOR INSERT
    TO sports_public_worker WITH CHECK (true);
CREATE POLICY result_correction ON event.event_results FOR UPDATE
    TO sports_public_worker USING (ml.evaluation_time_is_open(occurred_at))
    WITH CHECK (ml.evaluation_time_is_open(occurred_at));
ALTER TABLE analysis.prediction_evaluations ENABLE ROW LEVEL SECURITY;
CREATE POLICY evaluation_visibility ON analysis.prediction_evaluations FOR SELECT
    TO sports_public_worker, model_training_worker USING (
        EXISTS (SELECT 1 FROM analysis.model_predictions p
            JOIN analysis.analysis_markets m USING (analysis_market_id)
            JOIN analysis.analysis_runs r USING (analysis_run_id)
            WHERE p.prediction_id = prediction_evaluations.prediction_id
                AND ml.evaluation_time_is_open(r.decision_time))
    );
CREATE POLICY evaluation_ingestion ON analysis.prediction_evaluations FOR INSERT
    TO sports_public_worker WITH CHECK (
        EXISTS (SELECT 1 FROM analysis.model_predictions p
            JOIN analysis.analysis_markets m USING (analysis_market_id)
            JOIN analysis.analysis_runs r USING (analysis_run_id)
            WHERE p.prediction_id = prediction_evaluations.prediction_id
                AND ml.evaluation_time_is_open(r.decision_time))
    );

CREATE FUNCTION ml.guard_evaluation_window() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE requested ml.evaluation_windows; requested_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'experiment_runs' THEN
        requested_id := NEW.validation_window_id;
    ELSE
        requested_id := NEW.evaluation_window_id;
    END IF;
    SELECT * INTO requested FROM ml.evaluation_windows WHERE window_id = requested_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'evaluation window missing' USING ERRCODE = '23503';
    END IF;
    -- Prevent relabeling a protected interval as TRAIN or DEVELOPMENT.
    IF requested.locked OR EXISTS (
        SELECT 1 FROM ml.evaluation_windows WHERE window_type = 'HOLDOUT' AND locked
            AND tstzrange(starts_at, ends_at, '[)') && tstzrange(requested.starts_at, requested.ends_at, '[)')
    ) THEN
        RAISE EXCEPTION 'evaluation overlaps a locked holdout' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_experiment_window BEFORE INSERT OR UPDATE ON ml.experiment_runs
    FOR EACH ROW EXECUTE FUNCTION ml.guard_evaluation_window();
CREATE TRIGGER guard_backtest_window BEFORE INSERT OR UPDATE ON ml.backtest_runs
    FOR EACH ROW EXECUTE FUNCTION ml.guard_evaluation_window();

-- A trained artifact can advance status, but its identity and provenance cannot
-- be rewritten once validation makes it eligible for a prospective deployment.
CREATE FUNCTION ml.guard_model_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.model_family_id, NEW.version, NEW.created_at) IS DISTINCT FROM
        (OLD.model_family_id, OLD.version, OLD.created_at) OR
        (OLD.status NOT IN ('TRAINING','CANDIDATE') AND
         (NEW.artifact_uri, NEW.artifact_hash, NEW.git_sha, NEW.feature_pipeline_version)
             IS DISTINCT FROM
         (OLD.artifact_uri, OLD.artifact_hash, OLD.git_sha, OLD.feature_pipeline_version)) THEN
        RAISE EXCEPTION 'validated model provenance is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.status NOT IN ('TRAINING','CANDIDATE') AND NEW.status IN ('TRAINING','CANDIDATE') THEN
        RAISE EXCEPTION 'validated version cannot return to mutable training' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_model_version BEFORE UPDATE ON ml.model_versions
    FOR EACH ROW EXECUTE FUNCTION ml.guard_model_version();
CREATE TRIGGER no_delete_model_version BEFORE DELETE ON ml.model_versions
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();

-- Runtime roles cannot rewrite published prediction provenance or probabilities.
CREATE TRIGGER immutable_prediction BEFORE UPDATE OR DELETE ON analysis.model_predictions
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_prediction_outcomes BEFORE UPDATE OR DELETE ON analysis.prediction_outcomes
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_edges BEFORE UPDATE OR DELETE ON analysis.prediction_edges
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_quotes BEFORE UPDATE OR DELETE ON market.selected_quotes
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_quote_outcomes BEFORE UPDATE OR DELETE ON market.selected_quote_outcomes
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_benchmarks BEFORE UPDATE OR DELETE ON market.market_benchmarks
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_benchmark_outcomes BEFORE UPDATE OR DELETE ON market.benchmark_outcomes
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_analysis_markets BEFORE UPDATE OR DELETE ON analysis.analysis_markets
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
