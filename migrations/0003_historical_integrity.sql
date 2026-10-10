-- Close historical-integrity gaps at the persistence boundary. No live policy
-- is activated here; the added constraints apply to future operational writers.
ALTER TABLE event.event_cycles ADD CONSTRAINT terminal_cycle_dates CHECK (
    (status IN ('FINALIZED','POSTPONED','CANCELLED','ABANDONED')) = (closed_at IS NOT NULL)
    AND (status <> 'FINALIZED' OR actual_start_at IS NOT NULL)
    AND (actual_start_at IS NULL OR closed_at IS NULL OR actual_start_at <= closed_at)
);
ALTER TABLE ml.model_deployments ADD CONSTRAINT track_starts_at_activation
    CHECK (prospective_track_start = valid_from);

CREATE FUNCTION analysis.guard_prediction_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run_row analysis.analysis_runs; market_row analysis.analysis_markets;
        version_row ml.model_versions; family_row ml.model_families;
BEGIN
    SELECT * INTO market_row FROM analysis.analysis_markets WHERE analysis_market_id = NEW.analysis_market_id;
    SELECT * INTO run_row FROM analysis.analysis_runs WHERE analysis_run_id = market_row.analysis_run_id;
    SELECT * INTO version_row FROM ml.model_versions WHERE model_version_id = NEW.model_version_id;
    SELECT * INTO family_row FROM ml.model_families WHERE model_family_id = version_row.model_family_id;
    IF NEW.generated_at < run_row.decision_time OR version_row.created_at > run_row.decision_time
        OR version_row.feature_pipeline_version <> run_row.feature_pipeline_version
        OR family_row.market_code <> market_row.market_code OR family_row.model_role <> NEW.model_role
        OR NEW.confidence_policy_version <> run_row.confidence_policy_version
        OR NEW.no_bet_policy_version <> run_row.no_bet_policy_version THEN
        RAISE EXCEPTION 'prediction provenance does not match its decision' USING ERRCODE = '23514';
    END IF;
    IF run_row.run_mode = 'LIVE' AND NEW.model_status_at_prediction = 'PRODUCTION' AND NOT EXISTS (
        SELECT 1 FROM ml.model_deployments WHERE model_version_id = NEW.model_version_id
            AND valid_from <= run_row.decision_time AND (valid_to IS NULL OR run_row.decision_time < valid_to)
    ) THEN
        RAISE EXCEPTION 'live production attribution requires deployment at decision_time' USING ERRCODE = '23514';
    END IF;
    IF NEW.model_status_at_prediction IN ('TRAINING','CANDIDATE','NO_VALIDATED') AND NOT NEW.no_bet THEN
        RAISE EXCEPTION 'unvalidated model requires NO BET' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_prediction_provenance BEFORE INSERT ON analysis.model_predictions
    FOR EACH ROW EXECUTE FUNCTION analysis.guard_prediction_provenance();

-- A complete probability vector is committed with its parent in one transaction.
-- Partial inserts cannot leave an apparently valid two-way/three-way market.
CREATE FUNCTION analysis.check_probability_vector() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid; expected integer; actual integer; total double precision;
BEGIN
    IF TG_TABLE_NAME IN ('model_predictions','prediction_outcomes') THEN
        target := NEW.prediction_id;
        SELECT CASE d.outcome_structure WHEN 'TWO_WAY' THEN 2 ELSE 3 END INTO expected
            FROM analysis.model_predictions p JOIN analysis.analysis_markets m USING (analysis_market_id)
            JOIN market.market_definitions d USING (market_code) WHERE p.prediction_id = target;
        SELECT count(*), sum(probability) INTO actual,total FROM analysis.prediction_outcomes WHERE prediction_id = target;
        IF NOT EXISTS (SELECT 1 FROM analysis.model_predictions p JOIN analysis.prediction_outcomes o
            ON o.prediction_id = p.prediction_id AND o.outcome_code = p.favored_outcome_code
            WHERE p.prediction_id = target AND abs(o.probability-p.favored_probability) < 0.000001
            AND NOT EXISTS (SELECT 1 FROM analysis.prediction_outcomes other
                WHERE other.prediction_id = target AND other.probability > o.probability)) THEN
            RAISE EXCEPTION 'favored outcome must match the model distribution' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME IN ('selected_quotes','selected_quote_outcomes') THEN
        target := NEW.quote_id;
        SELECT CASE d.outcome_structure WHEN 'TWO_WAY' THEN 2 ELSE 3 END INTO expected
            FROM market.selected_quotes q JOIN analysis.analysis_markets m USING (analysis_market_id)
            JOIN market.market_definitions d USING (market_code) WHERE q.quote_id = target;
        SELECT count(*), sum(no_vig_probability) INTO actual,total FROM market.selected_quote_outcomes WHERE quote_id = target;
    ELSE
        target := NEW.benchmark_id;
        SELECT CASE d.outcome_structure WHEN 'TWO_WAY' THEN 2 ELSE 3 END INTO expected
            FROM market.market_benchmarks b JOIN analysis.analysis_markets m USING (analysis_market_id)
            JOIN market.market_definitions d USING (market_code) WHERE b.benchmark_id = target;
        SELECT count(*), sum(no_vig_probability) INTO actual,total FROM market.benchmark_outcomes WHERE benchmark_id = target;
    END IF;
    IF expected IS NULL OR actual <> expected OR total IS NULL OR abs(total - 1) > 0.000001 THEN
        RAISE EXCEPTION 'market requires a complete normalized probability vector' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER complete_prediction AFTER INSERT ON analysis.model_predictions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis.check_probability_vector();
CREATE CONSTRAINT TRIGGER complete_prediction_outcomes AFTER INSERT ON analysis.prediction_outcomes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis.check_probability_vector();
CREATE CONSTRAINT TRIGGER complete_quote AFTER INSERT ON market.selected_quotes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis.check_probability_vector();
CREATE CONSTRAINT TRIGGER complete_quote_outcomes AFTER INSERT ON market.selected_quote_outcomes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis.check_probability_vector();
CREATE CONSTRAINT TRIGGER complete_benchmark AFTER INSERT ON market.market_benchmarks
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis.check_probability_vector();
CREATE CONSTRAINT TRIGGER complete_benchmark_outcomes AFTER INSERT ON market.benchmark_outcomes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analysis.check_probability_vector();

-- Explicit quote and benchmark references preserve the actual public simulation
-- inputs. placed_at is simulated decision time, not the later ledger insert time.
ALTER TABLE paper.paper_bets ADD COLUMN quote_id uuid NOT NULL REFERENCES market.selected_quotes;
ALTER TABLE paper.paper_bets ADD COLUMN benchmark_id uuid NOT NULL REFERENCES market.market_benchmarks;
CREATE OR REPLACE FUNCTION paper.guard_bet() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE policy paper.paper_policies; prediction analysis.model_predictions;
        market_row analysis.analysis_markets; run_row analysis.analysis_runs;
        quote market.selected_quotes; offered numeric; winner text;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status') THEN
            RAISE EXCEPTION 'paper bet decision is immutable' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO policy FROM paper.paper_policies WHERE paper_policy_id = NEW.paper_policy_id FOR SHARE;
    SELECT * INTO prediction FROM analysis.model_predictions WHERE prediction_id = NEW.prediction_id;
    SELECT * INTO market_row FROM analysis.analysis_markets WHERE analysis_market_id = prediction.analysis_market_id;
    SELECT * INTO run_row FROM analysis.analysis_runs WHERE analysis_run_id = market_row.analysis_run_id;
    IF NOT policy.frozen OR run_row.decision_time < policy.valid_from OR
        (policy.valid_to IS NOT NULL AND run_row.decision_time >= policy.valid_to)
        OR NEW.placed_at <> run_row.decision_time THEN
        RAISE EXCEPTION 'paper policy must be active at simulated decision time' USING ERRCODE = '23514';
    END IF;
    IF run_row.run_mode <> 'LIVE' OR run_row.officiality <> 'OFFICIAL'
        OR market_row.status <> 'ELIGIBLE' OR (policy.requires_no_bet_false AND prediction.no_bet) THEN
        RAISE EXCEPTION 'paper track requires an eligible official prediction' USING ERRCODE = '23514';
    END IF;
    SELECT e.outcome_code INTO winner FROM analysis.prediction_edges e
        JOIN market.market_benchmarks b USING (benchmark_id)
        WHERE e.prediction_id = NEW.prediction_id AND e.benchmark_id = NEW.benchmark_id
            AND b.analysis_market_id = prediction.analysis_market_id AND e.edge_pp > 0
        ORDER BY e.edge_pp DESC, e.outcome_code COLLATE "C" LIMIT 1;
    IF winner IS DISTINCT FROM NEW.outcome_code THEN
        RAISE EXCEPTION 'paper selection requires maximum positive edge' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO quote FROM market.selected_quotes WHERE quote_id = NEW.quote_id;
    SELECT decimal_odds INTO offered FROM market.selected_quote_outcomes
        WHERE quote_id = NEW.quote_id AND outcome_code = NEW.outcome_code;
    IF quote.analysis_market_id IS DISTINCT FROM prediction.analysis_market_id
        OR quote.bookmaker_id IS DISTINCT FROM NEW.bookmaker_id OR offered IS DISTINCT FROM NEW.decimal_odds
        OR NEW.line_value IS DISTINCT FROM market_row.selected_line THEN
        RAISE EXCEPTION 'paper price must match a comparable stored quote' USING ERRCODE = '23514';
    END IF;
    IF policy.odds_source_rule = 'BETANO_PRIMARY' AND NOT EXISTS (
        SELECT 1 FROM market.bookmakers WHERE bookmaker_id = NEW.bookmaker_id AND code = 'BETANO_PE' AND is_primary
    ) THEN
        RAISE EXCEPTION 'paper source requires the primary Betano quote' USING ERRCODE = '23514';
    END IF;
    IF policy.odds_source_rule = 'BEST_AVAILABLE' AND EXISTS (
        SELECT 1 FROM market.selected_quotes q JOIN market.selected_quote_outcomes o USING (quote_id)
        WHERE q.analysis_market_id = prediction.analysis_market_id AND o.outcome_code = NEW.outcome_code
            AND o.decimal_odds > NEW.decimal_odds
    ) THEN
        RAISE EXCEPTION 'paper price is not the best stored eligible quote' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION private_betting.guard_cycle_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prediction_cycle uuid;
BEGIN
    SELECT r.event_cycle_id INTO prediction_cycle FROM analysis.analysis_markets m
        JOIN analysis.analysis_runs r USING (analysis_run_id) WHERE m.analysis_market_id = NEW.analysis_market_id;
    IF prediction_cycle IS DISTINCT FROM NEW.event_cycle_id THEN
        RAISE EXCEPTION 'private reference cannot cross event cycles' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER private_cycle_reference BEFORE INSERT OR UPDATE ON private_betting.real_bets
    FOR EACH ROW EXECUTE FUNCTION private_betting.guard_cycle_reference();

-- Protect labels and stored evaluation output, including a differently named
-- window overlapping the final holdout. Windows themselves remain admin-owned.
CREATE FUNCTION ml.evaluation_window_is_open(target uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT EXISTS (SELECT 1 FROM ml.evaluation_windows requested WHERE requested.window_id = target
        AND NOT requested.locked AND NOT EXISTS (SELECT 1 FROM ml.evaluation_windows protected
            WHERE protected.window_type = 'HOLDOUT' AND protected.locked
                AND tstzrange(protected.starts_at,protected.ends_at,'[)')
                    && tstzrange(requested.starts_at,requested.ends_at,'[)')));
$$;
GRANT EXECUTE ON FUNCTION ml.evaluation_window_is_open(uuid) TO sports_public_worker, model_training_worker;
ALTER TABLE ml.experiment_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY experiment_visibility ON ml.experiment_runs FOR SELECT TO sports_public_worker, model_training_worker
    USING (ml.evaluation_window_is_open(validation_window_id));
CREATE POLICY experiment_write ON ml.experiment_runs FOR INSERT TO model_training_worker
    WITH CHECK (ml.evaluation_window_is_open(validation_window_id));
CREATE POLICY experiment_update ON ml.experiment_runs FOR UPDATE TO model_training_worker
    USING (ml.evaluation_window_is_open(validation_window_id)) WITH CHECK (ml.evaluation_window_is_open(validation_window_id));
ALTER TABLE ml.backtest_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY backtest_visibility ON ml.backtest_runs FOR SELECT TO sports_public_worker, model_training_worker
    USING (ml.evaluation_window_is_open(evaluation_window_id));
CREATE POLICY backtest_write ON ml.backtest_runs FOR INSERT TO model_training_worker
    WITH CHECK (ml.evaluation_window_is_open(evaluation_window_id));
CREATE POLICY backtest_update ON ml.backtest_runs FOR UPDATE TO model_training_worker
    USING (ml.evaluation_window_is_open(evaluation_window_id)) WITH CHECK (ml.evaluation_window_is_open(evaluation_window_id));
CREATE FUNCTION ml.cycle_evaluation_is_open(target uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT EXISTS (SELECT 1 FROM event.event_cycles c WHERE c.event_cycle_id = target
        AND ml.evaluation_time_is_open(coalesce(c.actual_start_at,c.scheduled_start_at)));
$$;
GRANT EXECUTE ON FUNCTION ml.cycle_evaluation_is_open(uuid) TO sports_public_worker, model_training_worker, private_bets_worker;
ALTER POLICY result_visibility ON event.event_results
    USING (ml.evaluation_time_is_open(occurred_at) AND ml.cycle_evaluation_is_open(event_cycle_id));
ALTER TABLE paper.paper_bet_settlements ENABLE ROW LEVEL SECURITY;
CREATE POLICY paper_settlement_visibility ON paper.paper_bet_settlements FOR SELECT TO sports_public_worker
    USING (ml.cycle_evaluation_is_open(event_cycle_id));
CREATE POLICY paper_settlement_write ON paper.paper_bet_settlements FOR INSERT TO sports_public_worker
    WITH CHECK (ml.cycle_evaluation_is_open(event_cycle_id));

-- Refresh the clock after acquiring any blocking row lock. A delayed runner
-- cannot renew a lease that expired while it was waiting for another transaction.
CREATE OR REPLACE FUNCTION ops.acquire_event_lock(cycle uuid, owner_run uuid, ttl interval)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE token bigint; moment timestamptz;
BEGIN
    IF ttl IS NULL OR ttl <= interval '0 seconds' OR ttl > interval '1 hour' THEN
        RAISE EXCEPTION 'lock TTL must be positive and at most one hour' USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(cycle::text,719846023102));
    PERFORM 1 FROM ops.event_locks WHERE event_cycle_id = cycle FOR UPDATE;
    moment := clock_timestamp();
    INSERT INTO ops.event_locks(event_cycle_id,owner_analysis_run_id,fencing_token,acquired_at,heartbeat_at,expires_at)
        VALUES(cycle,owner_run,nextval('ops.lock_fence_sequence'),moment,moment,moment+ttl)
        ON CONFLICT(event_cycle_id) DO UPDATE SET owner_analysis_run_id=EXCLUDED.owner_analysis_run_id,
            fencing_token=EXCLUDED.fencing_token,acquired_at=EXCLUDED.acquired_at,
            heartbeat_at=EXCLUDED.heartbeat_at,expires_at=EXCLUDED.expires_at
        WHERE ops.event_locks.expires_at <= moment RETURNING fencing_token INTO token;
    RETURN token;
END;
$$;
CREATE OR REPLACE FUNCTION ops.heartbeat_event_lock(cycle uuid, owner_run uuid, fence bigint, ttl interval)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE moment timestamptz; affected integer;
BEGIN
    IF ttl IS NULL OR ttl <= interval '0 seconds' OR ttl > interval '1 hour' THEN
        RAISE EXCEPTION 'lock TTL must be positive and at most one hour' USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM ops.event_locks WHERE event_cycle_id = cycle FOR UPDATE;
    moment := clock_timestamp();
    UPDATE ops.event_locks SET heartbeat_at=moment,expires_at=moment+ttl WHERE event_cycle_id=cycle
        AND owner_analysis_run_id=owner_run AND fencing_token=fence AND expires_at>moment;
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected=1;
END;
$$;
