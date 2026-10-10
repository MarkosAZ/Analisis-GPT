-- Foundation: PostgreSQL 16+, executed transactionally by the migration owner.
-- UUIDs are generated internally, never copied from a provider identifier.
CREATE SCHEMA catalog;
CREATE SCHEMA provider;
CREATE SCHEMA event;
CREATE SCHEMA market;
CREATE SCHEMA analysis;
CREATE SCHEMA ml;
CREATE SCHEMA paper;
CREATE SCHEMA private_betting;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE catalog.sports (
    sport_id smallint PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE catalog.entities (
    entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type text NOT NULL CHECK (entity_type IN ('TEAM','PLAYER','COMPETITION','VENUE')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    active boolean NOT NULL DEFAULT true,
    UNIQUE (entity_id, entity_type)
);
CREATE TABLE catalog.competitions (
    competition_id uuid PRIMARY KEY,
    entity_type text NOT NULL DEFAULT 'COMPETITION' CHECK (entity_type = 'COMPETITION'),
    sport_id smallint NOT NULL REFERENCES catalog.sports,
    canonical_name text NOT NULL,
    country_code text,
    competition_type text NOT NULL DEFAULT 'LEAGUE',
    timezone text NOT NULL DEFAULT 'UTC',
    active boolean NOT NULL DEFAULT true,
    FOREIGN KEY (competition_id, entity_type) REFERENCES catalog.entities(entity_id, entity_type),
    UNIQUE (competition_id, sport_id)
);
CREATE TABLE catalog.seasons (
    season_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    competition_id uuid NOT NULL REFERENCES catalog.competitions,
    name text NOT NULL,
    starts_at date NOT NULL,
    ends_at date NOT NULL,
    CHECK (ends_at >= starts_at),
    UNIQUE (competition_id, name),
    UNIQUE (season_id, competition_id)
);
CREATE TABLE catalog.teams (
    team_id uuid PRIMARY KEY,
    entity_type text NOT NULL DEFAULT 'TEAM' CHECK (entity_type = 'TEAM'),
    sport_id smallint NOT NULL REFERENCES catalog.sports,
    canonical_name text NOT NULL,
    country_code text,
    active boolean NOT NULL DEFAULT true,
    FOREIGN KEY (team_id, entity_type) REFERENCES catalog.entities(entity_id, entity_type)
);
CREATE TABLE catalog.players (
    player_id uuid PRIMARY KEY,
    entity_type text NOT NULL DEFAULT 'PLAYER' CHECK (entity_type = 'PLAYER'),
    sport_id smallint NOT NULL REFERENCES catalog.sports,
    canonical_name text NOT NULL,
    birth_date date,
    active boolean NOT NULL DEFAULT true,
    FOREIGN KEY (player_id, entity_type) REFERENCES catalog.entities(entity_id, entity_type)
);
CREATE TABLE catalog.venues (
    venue_id uuid PRIMARY KEY,
    entity_type text NOT NULL DEFAULT 'VENUE' CHECK (entity_type = 'VENUE'),
    canonical_name text NOT NULL,
    city text,
    country_code text,
    timezone text NOT NULL DEFAULT 'UTC',
    roof_type text CHECK (roof_type IN ('OPEN','RETRACTABLE','DOME')),
    FOREIGN KEY (venue_id, entity_type) REFERENCES catalog.entities(entity_id, entity_type)
);
CREATE TABLE provider.providers (
    provider_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    provider_type text NOT NULL CHECK (provider_type IN ('SPORTS_DATA','ODDS','NEWS','WEATHER')),
    enabled boolean NOT NULL DEFAULT false
);
CREATE TABLE provider.entity_mappings (
    mapping_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id uuid NOT NULL REFERENCES provider.providers,
    entity_id uuid REFERENCES catalog.entities,
    provider_entity_type text NOT NULL,
    provider_entity_id text NOT NULL,
    provider_name text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    mapping_status text NOT NULL CHECK (mapping_status IN
        ('AUTO_CONFIRMED','MANUAL_CONFIRMED','PENDING_REVIEW','REJECTED')),
    mapping_method text NOT NULL,
    reviewed_at timestamptz,
    CHECK (mapping_status NOT IN ('AUTO_CONFIRMED','MANUAL_CONFIRMED') OR entity_id IS NOT NULL),
    CHECK (mapping_status <> 'MANUAL_CONFIRMED' OR reviewed_at IS NOT NULL),
    UNIQUE (provider_id, provider_entity_type, provider_entity_id)
);
CREATE TABLE event.events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sport_id smallint NOT NULL REFERENCES catalog.sports,
    competition_id uuid NOT NULL,
    season_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (competition_id, sport_id) REFERENCES catalog.competitions(competition_id, sport_id),
    FOREIGN KEY (season_id, competition_id) REFERENCES catalog.seasons(season_id, competition_id)
);
CREATE TABLE event.event_participants (
    event_id uuid NOT NULL REFERENCES event.events,
    team_id uuid NOT NULL REFERENCES catalog.teams,
    role text NOT NULL CHECK (role IN ('HOME','AWAY')),
    sort_order smallint NOT NULL CHECK (sort_order > 0),
    PRIMARY KEY (event_id, team_id),
    UNIQUE (event_id, role),
    UNIQUE (event_id, sort_order)
);
CREATE TABLE event.event_cycles (
    event_cycle_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES event.events,
    cycle_number integer NOT NULL CHECK (cycle_number > 0),
    scheduled_start_at timestamptz NOT NULL,
    actual_start_at timestamptz,
    timezone_event text NOT NULL DEFAULT 'UTC',
    venue_id uuid REFERENCES catalog.venues,
    status text NOT NULL CHECK (status IN
        ('SCHEDULED','TRACKING','LOCKED','FINALIZED','POSTPONED','CANCELLED','ABANDONED')),
    previous_cycle_id uuid UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    closed_at timestamptz,
    UNIQUE (event_id, cycle_number),
    UNIQUE (event_cycle_id, event_id),
    FOREIGN KEY (previous_cycle_id, event_id) REFERENCES event.event_cycles(event_cycle_id, event_id),
    CHECK ((cycle_number = 1) = (previous_cycle_id IS NULL)),
    CHECK (previous_cycle_id IS DISTINCT FROM event_cycle_id),
    CHECK (closed_at IS NULL OR closed_at >= created_at)
);
CREATE TABLE provider.event_refs (
    provider_id uuid NOT NULL REFERENCES provider.providers,
    event_cycle_id uuid NOT NULL REFERENCES event.event_cycles,
    provider_event_id text NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    PRIMARY KEY (provider_id, event_cycle_id),
    -- A provider can reuse its event ID after postponement; internal cycles remain distinct.
    CHECK (last_seen_at >= first_seen_at)
);
CREATE INDEX event_refs_lookup ON provider.event_refs(provider_id, provider_event_id);
CREATE TABLE event.tracking (
    event_cycle_id uuid PRIMARY KEY REFERENCES event.event_cycles,
    tracking_status text NOT NULL CHECK (tracking_status IN ('ACTIVE','PAUSED','CLOSED')),
    selected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_analysis_at timestamptz,
    last_odds_capture_at timestamptz,
    tracking_profile_version text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE event.event_results (
    event_cycle_id uuid PRIMARY KEY REFERENCES event.event_cycles,
    result_status text NOT NULL CHECK (result_status IN ('PENDING','CONFIRMED','VOID','UNDER_REVIEW')),
    home_score numeric CHECK (home_score >= 0),
    away_score numeric CHECK (away_score >= 0),
    actual_start_at timestamptz,
    completed_at timestamptz,
    result_data_uri text NOT NULL,
    confirmed_at timestamptz,
    occurred_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    available_at_source text NOT NULL CHECK (available_at_source IN ('OBSERVED','ESTIMATED')),
    CHECK (completed_at IS NULL OR actual_start_at IS NULL OR completed_at >= actual_start_at),
    CHECK (result_status <> 'CONFIRMED' OR confirmed_at IS NOT NULL)
);
CREATE TABLE market.bookmakers (
    bookmaker_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    jurisdiction text,
    is_primary boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX bookmakers_one_primary ON market.bookmakers(is_primary) WHERE is_primary;
CREATE TABLE market.market_definitions (
    market_code text PRIMARY KEY,
    sport_id smallint NOT NULL REFERENCES catalog.sports,
    display_name text NOT NULL,
    scope text NOT NULL CHECK (scope IN ('FULL_GAME','FIRST_HALF')),
    subject_type text NOT NULL CHECK (subject_type IN ('EVENT','TEAM','PLAYER')),
    outcome_structure text NOT NULL CHECK (outcome_structure IN ('TWO_WAY','THREE_WAY')),
    supports_line boolean NOT NULL,
    supports_push boolean NOT NULL,
    supports_asian boolean NOT NULL,
    active_for_prediction boolean NOT NULL DEFAULT false,
    CHECK (supports_line OR (NOT supports_push AND NOT supports_asian)),
    UNIQUE (market_code, sport_id)
);
CREATE TABLE market.odds_captures (
    capture_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_cycle_id uuid NOT NULL REFERENCES event.event_cycles,
    provider_id uuid NOT NULL REFERENCES provider.providers,
    capture_mode text NOT NULL CHECK (capture_mode IN ('API','BROWSER_EXTENSION','MANUAL_OBSERVATION')),
    fetched_at timestamptz NOT NULL,
    occurred_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    available_at_source text NOT NULL CHECK (available_at_source IN ('OBSERVED','ESTIMATED')),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    raw_uri text NOT NULL,
    parquet_uri text,
    adapter_version text NOT NULL,
    normalizer_version text NOT NULL,
    schema_version text NOT NULL,
    market_count integer NOT NULL CHECK (market_count >= 0),
    bookmaker_count integer NOT NULL CHECK (bookmaker_count >= 0),
    source_quality double precision NOT NULL CHECK (source_quality BETWEEN 0 AND 1),
    status text NOT NULL CHECK (status IN ('CAPTURED','NORMALIZED','FAILED')),
    CHECK (available_at_source <> 'OBSERVED' OR available_at >= fetched_at),
    UNIQUE (capture_id, event_cycle_id)
    -- content_hash is intentionally NOT unique: unchanged prices are new observations.
);
CREATE TABLE analysis.analysis_runs (
    analysis_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_cycle_id uuid NOT NULL REFERENCES event.event_cycles,
    run_mode text NOT NULL CHECK (run_mode IN ('LIVE','RECONSTRUCTED','BACKTEST')),
    trigger_type text NOT NULL CHECK (trigger_type IN ('MANUAL','SCHEDULED')),
    github_run_id bigint CHECK (github_run_id > 0),
    scheduled_slot timestamptz,
    decision_time timestamptz NOT NULL,
    pipeline_version text NOT NULL,
    feature_pipeline_version text NOT NULL,
    line_selector_version text NOT NULL,
    confidence_policy_version text NOT NULL,
    no_bet_policy_version text NOT NULL,
    git_sha char(40) NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    status text NOT NULL DEFAULT 'QUEUED' CHECK (status IN
        ('QUEUED','INGESTING','NORMALIZING','FEATURES','PREDICTING','EXPLAINING','PUBLISHING',
         'COMPLETED','COMPLETED_WITH_WARNINGS','FAILED_DATA','FAILED_MODEL','FAILED_TIMEOUT')),
    current_stage text CHECK (current_stage IN
        ('INGESTING','NORMALIZING','FEATURES','PREDICTING','EXPLAINING','PUBLISHING')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    officiality text NOT NULL DEFAULT 'PROVISIONAL' CHECK (officiality IN ('PROVISIONAL','OFFICIAL','NON_OFFICIAL')),
    officialized_at timestamptz,
    freshness text NOT NULL DEFAULT 'UNKNOWN' CHECK (freshness IN ('FRESH','STALE','UNKNOWN')),
    data_quality_score double precision CHECK (data_quality_score BETWEEN 0 AND 1),
    observed_data_pct double precision CHECK (observed_data_pct BETWEEN 0 AND 100),
    estimated_data_pct double precision CHECK (estimated_data_pct BETWEEN 0 AND 100),
    warnings jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(warnings) = 'array'),
    CHECK (trigger_type <> 'SCHEDULED' OR scheduled_slot IS NOT NULL),
    CHECK (trigger_type <> 'MANUAL' OR github_run_id IS NOT NULL),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    CHECK (officiality <> 'OFFICIAL' OR (run_mode = 'LIVE' AND officialized_at IS NOT NULL)),
    CHECK (observed_data_pct IS NULL OR estimated_data_pct IS NULL
        OR abs(observed_data_pct + estimated_data_pct - 100) < 0.000001),
    UNIQUE (analysis_run_id, event_cycle_id)
);
CREATE UNIQUE INDEX analysis_runs_scheduled_idempotency
    ON analysis.analysis_runs(event_cycle_id, scheduled_slot, pipeline_version)
    WHERE trigger_type = 'SCHEDULED';
CREATE UNIQUE INDEX analysis_runs_manual_idempotency
    ON analysis.analysis_runs(event_cycle_id, github_run_id, pipeline_version)
    WHERE trigger_type = 'MANUAL';
CREATE TABLE analysis.analysis_stages (
    analysis_run_id uuid NOT NULL REFERENCES analysis.analysis_runs,
    stage_code text NOT NULL CHECK (stage_code IN
        ('INGESTING','NORMALIZING','FEATURES','PREDICTING','EXPLAINING','PUBLISHING')),
    status text NOT NULL CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')),
    started_at timestamptz,
    heartbeat_at timestamptz,
    finished_at timestamptz,
    error_code text,
    error_summary text,
    PRIMARY KEY (analysis_run_id, stage_code),
    CHECK (finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at))
);
CREATE TABLE analysis.input_refs (
    input_ref_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id uuid NOT NULL REFERENCES analysis.analysis_runs,
    domain text NOT NULL CHECK (domain IN ('STATS','LINEUP','INJURY','NEWS','ODDS','WEATHER')),
    provider_id uuid NOT NULL REFERENCES provider.providers,
    object_uri text NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    fetched_at timestamptz NOT NULL,
    occurred_at timestamptz,
    available_at_min timestamptz NOT NULL,
    available_at_max timestamptz NOT NULL,
    available_at_source text NOT NULL CHECK (available_at_source IN ('OBSERVED','ESTIMATED','MIXED')),
    adapter_version text NOT NULL,
    normalizer_version text NOT NULL,
    schema_version text NOT NULL,
    CHECK (available_at_min <= available_at_max),
    UNIQUE (analysis_run_id, domain, provider_id, object_uri)
);
CREATE TABLE analysis.manifests (
    analysis_run_id uuid PRIMARY KEY REFERENCES analysis.analysis_runs,
    manifest_uri text NOT NULL,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE analysis.analysis_markets (
    analysis_market_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id uuid NOT NULL REFERENCES analysis.analysis_runs,
    market_code text NOT NULL REFERENCES market.market_definitions,
    subject_team_id uuid REFERENCES catalog.teams,
    subject_player_id uuid REFERENCES catalog.players,
    status text NOT NULL CHECK (status IN ('ELIGIBLE','NO_ELIGIBLE_LINE','INSUFFICIENT_ODDS','FAILED')),
    selected_line numeric(10,4),
    line_type text CHECK (line_type IN ('HALF_LINE','INTEGER_PUSH','ASIAN_QUARTER')),
    line_selector_version text NOT NULL,
    selection_reason text NOT NULL,
    selection_metrics jsonb NOT NULL DEFAULT '{}',
    candidate_snapshot_uri text,
    odds_capture_id uuid REFERENCES market.odds_captures,
    odds_age_seconds integer CHECK (odds_age_seconds >= 0),
    odds_freshness text NOT NULL CHECK (odds_freshness IN ('FRESH','STALE','UNKNOWN')),
    data_quality_score double precision CHECK (data_quality_score BETWEEN 0 AND 1),
    critical_context_missing text[] NOT NULL DEFAULT '{}',
    CHECK (num_nonnulls(subject_team_id, subject_player_id) <= 1),
    CHECK ((selected_line IS NULL) = (line_type IS NULL)),
    CHECK (line_type <> 'HALF_LINE' OR mod(abs(selected_line), 1) = 0.5),
    CHECK (line_type <> 'INTEGER_PUSH' OR mod(abs(selected_line), 1) = 0),
    CHECK (line_type <> 'ASIAN_QUARTER' OR mod(abs(selected_line), 1) IN (0.25,0.75)),
    CHECK (line_selector_version <> 'line_selector_v1' OR status <> 'ELIGIBLE'
        OR line_type IS NULL OR line_type = 'HALF_LINE'),
    UNIQUE NULLS NOT DISTINCT (analysis_run_id, market_code, subject_team_id, subject_player_id)
);
CREATE TABLE market.selected_quotes (
    quote_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_market_id uuid NOT NULL REFERENCES analysis.analysis_markets,
    bookmaker_id uuid NOT NULL REFERENCES market.bookmakers,
    captured_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    line_value numeric(10,4),
    overround double precision NOT NULL CHECK (overround > -1 AND overround < 'Infinity'::float8),
    devig_method text NOT NULL,
    UNIQUE (quote_id, analysis_market_id),
    UNIQUE (analysis_market_id, bookmaker_id),
    CHECK (available_at >= captured_at)
);
CREATE TABLE market.selected_quote_outcomes (
    quote_id uuid NOT NULL REFERENCES market.selected_quotes,
    outcome_code text NOT NULL,
    decimal_odds numeric(10,4) NOT NULL CHECK (decimal_odds > 1),
    implied_probability double precision NOT NULL CHECK (implied_probability > 0 AND implied_probability < 1),
    no_vig_probability double precision NOT NULL CHECK (no_vig_probability > 0 AND no_vig_probability < 1),
    PRIMARY KEY (quote_id, outcome_code),
    CHECK (abs(implied_probability - 1.0 / decimal_odds::float8) < 0.000001)
);
CREATE TABLE market.market_benchmarks (
    benchmark_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_market_id uuid NOT NULL REFERENCES analysis.analysis_markets,
    benchmark_type text NOT NULL CHECK (benchmark_type IN ('BETANO','MARKET_CONSENSUS')),
    devig_method text NOT NULL,
    calculated_at timestamptz NOT NULL,
    source_snapshot_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    freshness text NOT NULL CHECK (freshness IN ('FRESH','STALE','UNKNOWN')),
    overround double precision CHECK (overround > -1 AND overround < 'Infinity'::float8),
    UNIQUE (analysis_market_id, benchmark_type),
    UNIQUE (benchmark_id, analysis_market_id)
);
CREATE TABLE market.benchmark_outcomes (
    benchmark_id uuid NOT NULL REFERENCES market.market_benchmarks,
    outcome_code text NOT NULL,
    no_vig_probability double precision NOT NULL CHECK (no_vig_probability > 0 AND no_vig_probability < 1),
    fair_odds numeric(16,6) NOT NULL CHECK (fair_odds > 1),
    PRIMARY KEY (benchmark_id, outcome_code),
    CHECK (abs(fair_odds::float8 - 1 / no_vig_probability) < 0.00001)
);
CREATE TABLE ml.model_families (
    model_family_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    sport_id smallint NOT NULL REFERENCES catalog.sports,
    market_code text NOT NULL,
    model_role text NOT NULL CHECK (model_role IN ('STATISTICAL','GBM','NEURAL','CONSENSUS')),
    competition_id uuid REFERENCES catalog.competitions,
    FOREIGN KEY (market_code, sport_id) REFERENCES market.market_definitions(market_code, sport_id)
);
CREATE TABLE ml.model_versions (
    model_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_family_id uuid NOT NULL REFERENCES ml.model_families,
    version text NOT NULL,
    status text NOT NULL CHECK (status IN
        ('TRAINING','CANDIDATE','VALIDATED','PRODUCTION','DEGRADED','NO_VALIDATED','RETIRED')),
    artifact_uri text,
    artifact_hash text CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    git_sha char(40) NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    feature_pipeline_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    metrics_summary jsonb NOT NULL DEFAULT '{}',
    CHECK ((artifact_uri IS NULL) = (artifact_hash IS NULL)),
    CHECK (status NOT IN ('VALIDATED','PRODUCTION') OR artifact_uri IS NOT NULL),
    UNIQUE (model_family_id, version),
    UNIQUE (model_version_id, model_family_id)
);
CREATE TABLE ml.model_deployments (
    deployment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_family_id uuid NOT NULL REFERENCES ml.model_families,
    model_version_id uuid NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    deployment_reason text NOT NULL,
    prospective_track_start timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (model_version_id, model_family_id)
        REFERENCES ml.model_versions(model_version_id, model_family_id),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (prospective_track_start >= valid_from),
    UNIQUE (model_family_id, valid_from)
);
CREATE TABLE ml.evaluation_windows (
    window_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    window_type text NOT NULL CHECK (window_type IN ('TRAIN','DEVELOPMENT','HOLDOUT','PROSPECTIVE')),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    locked boolean NOT NULL,
    unlocked_at timestamptz,
    unlocked_by_run_id bigint CHECK (unlocked_by_run_id > 0),
    CHECK (ends_at > starts_at),
    CHECK (NOT locked OR window_type = 'HOLDOUT'),
    CHECK (window_type <> 'HOLDOUT' OR locked OR (unlocked_at IS NOT NULL AND unlocked_by_run_id IS NOT NULL)),
    CHECK (NOT locked OR (unlocked_at IS NULL AND unlocked_by_run_id IS NULL))
);
CREATE TABLE ml.experiment_runs (
    experiment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_family_id uuid NOT NULL REFERENCES ml.model_families,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    dataset_manifest_hash text NOT NULL CHECK (dataset_manifest_hash ~ '^[0-9a-f]{64}$'),
    validation_window_id uuid NOT NULL REFERENCES ml.evaluation_windows,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    metrics jsonb NOT NULL DEFAULT '{}',
    significance_tests jsonb NOT NULL DEFAULT '{}',
    git_sha char(40) NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    status text NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    UNIQUE (model_family_id, validation_window_id, attempt_number)
);
CREATE TABLE ml.backtest_runs (
    backtest_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES ml.model_versions,
    evaluation_window_id uuid NOT NULL REFERENCES ml.evaluation_windows,
    dataset_manifest_uri text NOT NULL,
    dataset_manifest_hash text NOT NULL CHECK (dataset_manifest_hash ~ '^[0-9a-f]{64}$'),
    method text NOT NULL CHECK (method = 'WALK_FORWARD'),
    available_at_source text NOT NULL CHECK (available_at_source IN ('OBSERVED','ESTIMATED','MIXED')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    metrics jsonb NOT NULL DEFAULT '{}',
    segment_metrics_uri text,
    results_uri text,
    git_sha char(40) NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    status text NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);
CREATE TABLE analysis.model_predictions (
    prediction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_market_id uuid NOT NULL REFERENCES analysis.analysis_markets,
    model_version_id uuid NOT NULL REFERENCES ml.model_versions,
    model_role text NOT NULL CHECK (model_role IN ('STATISTICAL','GBM','NEURAL','CONSENSUS')),
    generated_at timestamptz NOT NULL,
    distribution_family text,
    predicted_mean double precision,
    predicted_variance double precision CHECK (predicted_variance >= 0 AND predicted_variance < 'Infinity'::float8),
    predicted_mode double precision,
    distribution_summary jsonb,
    distribution_uri text,
    favored_outcome_code text NOT NULL,
    favored_probability double precision NOT NULL CHECK (favored_probability BETWEEN 0 AND 1),
    confidence_level text NOT NULL CHECK (confidence_level IN ('LOW','MEDIUM','HIGH')),
    confidence_policy_version text NOT NULL,
    ensemble_dispersion double precision CHECK (ensemble_dispersion >= 0 AND ensemble_dispersion < 'Infinity'::float8),
    ood_score double precision CHECK (ood_score >= 0 AND ood_score < 'Infinity'::float8),
    no_bet boolean NOT NULL,
    no_bet_policy_version text NOT NULL,
    no_bet_reasons text[] NOT NULL DEFAULT '{}',
    model_status_at_prediction text NOT NULL CHECK (model_status_at_prediction IN
        ('TRAINING','CANDIDATE','VALIDATED','PRODUCTION','DEGRADED','NO_VALIDATED','RETIRED')),
    explanation_summary jsonb NOT NULL DEFAULT '{}',
    UNIQUE (analysis_market_id, model_version_id),
    UNIQUE (prediction_id, analysis_market_id)
);
CREATE TABLE analysis.prediction_outcomes (
    prediction_id uuid NOT NULL REFERENCES analysis.model_predictions,
    outcome_code text NOT NULL,
    probability double precision NOT NULL CHECK (probability BETWEEN 0 AND 1),
    fair_odds numeric(16,6) CHECK (fair_odds >= 1),
    rank smallint NOT NULL CHECK (rank > 0),
    PRIMARY KEY (prediction_id, outcome_code),
    UNIQUE (prediction_id, rank),
    CHECK ((probability = 0 AND fair_odds IS NULL)
        OR (probability > 0 AND fair_odds IS NOT NULL AND abs(fair_odds::float8 - 1 / probability) < 0.00001))
);
CREATE TABLE analysis.prediction_edges (
    prediction_id uuid NOT NULL,
    benchmark_id uuid NOT NULL,
    outcome_code text NOT NULL,
    model_probability double precision NOT NULL CHECK (model_probability BETWEEN 0 AND 1),
    market_probability double precision NOT NULL CHECK (market_probability BETWEEN 0 AND 1),
    edge_pp double precision NOT NULL,
    is_value_side boolean NOT NULL,
    ev_per_unit double precision,
    PRIMARY KEY (prediction_id, benchmark_id, outcome_code),
    FOREIGN KEY (prediction_id, outcome_code) REFERENCES analysis.prediction_outcomes,
    FOREIGN KEY (benchmark_id, outcome_code) REFERENCES market.benchmark_outcomes,
    CHECK (abs(edge_pp - 100 * (model_probability - market_probability)) < 0.000001),
    CHECK (NOT is_value_side OR edge_pp > 0)
);
CREATE TABLE analysis.prediction_evaluations (
    prediction_id uuid PRIMARY KEY REFERENCES analysis.model_predictions,
    event_cycle_id uuid NOT NULL REFERENCES event.event_results,
    evaluated_at timestamptz NOT NULL,
    realized_value double precision,
    realized_outcome_code text,
    log_loss_component double precision CHECK (log_loss_component >= 0 AND log_loss_component < 'Infinity'::float8),
    brier_component double precision CHECK (brier_component >= 0 AND brier_component <= 2),
    absolute_error double precision CHECK (absolute_error >= 0 AND absolute_error < 'Infinity'::float8),
    squared_error double precision CHECK (squared_error >= 0 AND squared_error < 'Infinity'::float8),
    included_in_metrics boolean NOT NULL,
    exclusion_reason text,
    CHECK (included_in_metrics OR exclusion_reason IS NOT NULL)
);
CREATE TABLE paper.paper_policies (
    paper_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    selection_rule text NOT NULL CHECK (selection_rule = 'MAX_POSITIVE_EDGE'),
    odds_source_rule text NOT NULL CHECK (odds_source_rule IN ('UNDECIDED','BETANO_PRIMARY','BEST_AVAILABLE')),
    requires_no_bet_false boolean NOT NULL,
    stake_units numeric NOT NULL CHECK (stake_units = 1),
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    frozen boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (NOT frozen OR odds_source_rule <> 'UNDECIDED')
);
CREATE TABLE paper.paper_bets (
    paper_bet_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_policy_id uuid NOT NULL REFERENCES paper.paper_policies,
    prediction_id uuid NOT NULL,
    outcome_code text NOT NULL,
    bookmaker_id uuid NOT NULL REFERENCES market.bookmakers,
    line_value numeric(10,4),
    decimal_odds numeric(10,4) NOT NULL CHECK (decimal_odds > 1),
    stake_units numeric NOT NULL CHECK (stake_units = 1),
    placed_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','SETTLED','VOID','UNDER_REVIEW')),
    FOREIGN KEY (prediction_id, outcome_code) REFERENCES analysis.prediction_outcomes,
    UNIQUE (paper_policy_id, prediction_id)
);
CREATE TABLE paper.paper_bet_settlements (
    paper_bet_id uuid PRIMARY KEY REFERENCES paper.paper_bets,
    event_cycle_id uuid NOT NULL REFERENCES event.event_results,
    result text NOT NULL CHECK (result IN ('WIN','LOSS','PUSH','HALF_WIN','HALF_LOSS','VOID')),
    profit_units numeric NOT NULL,
    settlement_rule_version text NOT NULL,
    settled_at timestamptz NOT NULL,
    review_reason text
);
CREATE TABLE private_betting.real_bets (
    real_bet_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id uuid NOT NULL,
    analysis_market_id uuid NOT NULL REFERENCES analysis.analysis_markets,
    event_cycle_id uuid NOT NULL REFERENCES event.event_cycles,
    bookmaker_id uuid NOT NULL REFERENCES market.bookmakers,
    outcome_code text NOT NULL,
    line_value numeric(10,4),
    taken_odds numeric(10,4) NOT NULL CHECK (taken_odds > 1),
    stake_units numeric CHECK (stake_units > 0),
    stake_amount numeric CHECK (stake_amount > 0),
    currency text,
    placed_at timestamptz NOT NULL,
    automatic_odds_nearest numeric(10,4) CHECK (automatic_odds_nearest > 1),
    automatic_odds_captured_at timestamptz,
    automatic_odds_age_seconds integer CHECK (automatic_odds_age_seconds >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (prediction_id, analysis_market_id)
        REFERENCES analysis.model_predictions(prediction_id, analysis_market_id),
    FOREIGN KEY (prediction_id, outcome_code) REFERENCES analysis.prediction_outcomes,
    CHECK (stake_units IS NOT NULL OR stake_amount IS NOT NULL),
    CHECK ((stake_amount IS NULL) = (currency IS NULL)),
    CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    CHECK (automatic_odds_captured_at IS NULL OR automatic_odds_captured_at <= placed_at)
);
CREATE TABLE private_betting.review_queue (
    review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    real_bet_id uuid REFERENCES private_betting.real_bets,
    review_type text NOT NULL CHECK (review_type IN ('REAL_BET_SETTLEMENT','PRIVATE_BOOKMAKER_RULE')),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RESOLVED','REJECTED')),
    details jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    CHECK ((status = 'PENDING') = (resolved_at IS NULL))
);
CREATE SEQUENCE ops.lock_fence_sequence AS bigint;
CREATE TABLE ops.event_locks (
    event_cycle_id uuid PRIMARY KEY REFERENCES event.event_cycles,
    owner_analysis_run_id uuid NOT NULL,
    fencing_token bigint NOT NULL UNIQUE CHECK (fencing_token > 0),
    acquired_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    FOREIGN KEY (owner_analysis_run_id, event_cycle_id)
        REFERENCES analysis.analysis_runs(analysis_run_id, event_cycle_id),
    CHECK (heartbeat_at >= acquired_at AND expires_at > heartbeat_at)
);
CREATE TABLE ops.review_queue (
    review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_type text NOT NULL CHECK (review_type IN ('ENTITY_MAPPING','PAPER_SETTLEMENT','PROVIDER_DATA')),
    mapping_id uuid REFERENCES provider.entity_mappings,
    paper_bet_id uuid REFERENCES paper.paper_bets,
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RESOLVED','REJECTED')),
    -- Public-only diagnostic codes/references. Never put private betting data here.
    reason_code text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    CHECK ((status = 'PENDING') = (resolved_at IS NULL))
);
CREATE UNIQUE INDEX review_queue_mapping_pending ON ops.review_queue(mapping_id)
    WHERE status = 'PENDING' AND mapping_id IS NOT NULL;
CREATE TABLE ops.github_runs (
    github_run_id bigint NOT NULL CHECK (github_run_id > 0),
    run_attempt integer NOT NULL CHECK (run_attempt > 0),
    workflow text NOT NULL,
    git_sha char(40) NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    trigger_type text NOT NULL CHECK (trigger_type IN ('SCHEDULE','WORKFLOW_DISPATCH','PUSH','PULL_REQUEST')),
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    conclusion text CHECK (conclusion IN ('SUCCESS','FAILURE','CANCELLED','TIMED_OUT','SKIPPED')),
    PRIMARY KEY (github_run_id, run_attempt),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);
CREATE TABLE ops.cron_slots (
    workflow text NOT NULL,
    scheduled_slot timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('EXPECTED','FILLED','MISSED','LATE','SKIPPED')),
    github_run_id bigint,
    run_attempt integer,
    observed_at timestamptz,
    lateness_seconds integer CHECK (lateness_seconds >= 0),
    PRIMARY KEY (workflow, scheduled_slot),
    FOREIGN KEY (github_run_id, run_attempt) REFERENCES ops.github_runs,
    CHECK ((github_run_id IS NULL) = (run_attempt IS NULL))
);
CREATE TABLE ops.page_deployments (
    page_deployment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    git_sha char(40) NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    schema_version text NOT NULL,
    built_at timestamptz NOT NULL,
    deployed_at timestamptz,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    CHECK (deployed_at IS NULL OR deployed_at >= built_at)
);

-- Useful access paths, including those used by chronology and stale-run reconciliation.
CREATE INDEX cycles_status_start ON event.event_cycles(status, scheduled_start_at);
CREATE INDEX runs_cycle_decision ON analysis.analysis_runs(event_cycle_id, decision_time DESC);
CREATE INDEX runs_status_started ON analysis.analysis_runs(status, started_at);
CREATE INDEX captures_cycle_fetched ON market.odds_captures(event_cycle_id, fetched_at DESC);
CREATE INDEX predictions_market ON analysis.model_predictions(analysis_market_id);
CREATE INDEX paper_bets_placed ON paper.paper_bets(placed_at DESC);
CREATE INDEX deployments_family_start ON ml.model_deployments(model_family_id, valid_from DESC);
CREATE INDEX public_reviews_status_created ON ops.review_queue(status, created_at);
CREATE INDEX private_reviews_status_created ON private_betting.review_queue(status, created_at);
CREATE INDEX results_available ON event.event_results(available_at);
CREATE INDEX input_refs_run_available ON analysis.input_refs(analysis_run_id, available_at_max);

CREATE FUNCTION ops.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable record: append a new version instead' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER immutable_input_refs BEFORE UPDATE OR DELETE ON analysis.input_refs
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_manifests BEFORE UPDATE OR DELETE ON analysis.manifests
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
CREATE TRIGGER immutable_captures BEFORE UPDATE OR DELETE ON market.odds_captures
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();

CREATE FUNCTION event.guard_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE predecessor event.event_cycles;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.event_id, NEW.cycle_number, NEW.previous_cycle_id, NEW.scheduled_start_at)
            IS DISTINCT FROM (OLD.event_id, OLD.cycle_number, OLD.previous_cycle_id, OLD.scheduled_start_at) THEN
            RAISE EXCEPTION 'cycle identity and schedule are immutable; create a successor' USING ERRCODE = '23514';
        END IF;
        IF OLD.status IN ('FINALIZED','POSTPONED','CANCELLED','ABANDONED') AND NEW.status <> OLD.status THEN
            RAISE EXCEPTION 'terminal cycle cannot reopen' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.previous_cycle_id IS NOT NULL THEN
        SELECT * INTO predecessor FROM event.event_cycles WHERE event_cycle_id = NEW.previous_cycle_id FOR UPDATE;
        IF predecessor.event_id IS DISTINCT FROM NEW.event_id OR predecessor.status <> 'POSTPONED'
            OR predecessor.cycle_number + 1 <> NEW.cycle_number THEN
            RAISE EXCEPTION 'successor must follow a postponed cycle of the same event' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_cycle BEFORE INSERT OR UPDATE ON event.event_cycles
    FOR EACH ROW EXECUTE FUNCTION event.guard_cycle();

CREATE FUNCTION analysis.guard_input_time() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE decision timestamptz;
BEGIN
    SELECT decision_time INTO decision FROM analysis.analysis_runs
        WHERE analysis_run_id = NEW.analysis_run_id FOR SHARE;
    IF NEW.available_at_max > decision THEN
        RAISE EXCEPTION 'input unavailable at decision_time' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_input_time BEFORE INSERT ON analysis.input_refs
    FOR EACH ROW EXECUTE FUNCTION analysis.guard_input_time();

CREATE FUNCTION analysis.guard_run_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.event_cycle_id, NEW.decision_time, NEW.pipeline_version, NEW.trigger_type,
        NEW.github_run_id, NEW.scheduled_slot, NEW.run_mode, NEW.git_sha,
        NEW.feature_pipeline_version, NEW.line_selector_version,
        NEW.confidence_policy_version, NEW.no_bet_policy_version)
        IS DISTINCT FROM
       (OLD.event_cycle_id, OLD.decision_time, OLD.pipeline_version, OLD.trigger_type,
        OLD.github_run_id, OLD.scheduled_slot, OLD.run_mode, OLD.git_sha,
        OLD.feature_pipeline_version, OLD.line_selector_version,
        OLD.confidence_policy_version, OLD.no_bet_policy_version) THEN
        RAISE EXCEPTION 'analysis identity, decision and versions are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_run_identity BEFORE UPDATE ON analysis.analysis_runs
    FOR EACH ROW EXECUTE FUNCTION analysis.guard_run_identity();

CREATE FUNCTION analysis.guard_market_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run_row analysis.analysis_runs; capture_row market.odds_captures; definition market.market_definitions;
BEGIN
    SELECT * INTO run_row FROM analysis.analysis_runs WHERE analysis_run_id = NEW.analysis_run_id;
    SELECT * INTO definition FROM market.market_definitions WHERE market_code = NEW.market_code;
    IF NEW.line_selector_version <> run_row.line_selector_version THEN
        RAISE EXCEPTION 'line selector version differs from run' USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ELIGIBLE' AND definition.supports_line AND NEW.selected_line IS NULL THEN
        RAISE EXCEPTION 'line market requires selected line' USING ERRCODE = '23514';
    END IF;
    IF NOT definition.supports_line AND NEW.selected_line IS NOT NULL THEN
        RAISE EXCEPTION 'line not supported by market' USING ERRCODE = '23514';
    END IF;
    IF NEW.odds_capture_id IS NOT NULL THEN
        SELECT * INTO capture_row FROM market.odds_captures WHERE capture_id = NEW.odds_capture_id;
        IF capture_row.event_cycle_id <> run_row.event_cycle_id OR capture_row.available_at > run_row.decision_time THEN
            RAISE EXCEPTION 'capture belongs to another cycle or is unavailable at decision' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_market_provenance BEFORE INSERT OR UPDATE ON analysis.analysis_markets
    FOR EACH ROW EXECUTE FUNCTION analysis.guard_market_provenance();

CREATE FUNCTION market.guard_quote_time() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE decision timestamptz; selected numeric;
BEGIN
    SELECT r.decision_time, m.selected_line INTO decision, selected
        FROM analysis.analysis_markets m JOIN analysis.analysis_runs r USING (analysis_run_id)
        WHERE m.analysis_market_id = NEW.analysis_market_id;
    IF NEW.available_at > decision THEN
        RAISE EXCEPTION 'odds unavailable at decision_time' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'selected_quotes' THEN
        IF NEW.line_value IS DISTINCT FROM selected THEN
            RAISE EXCEPTION 'quote line differs from selected line' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_quote_time BEFORE INSERT OR UPDATE ON market.selected_quotes
    FOR EACH ROW EXECUTE FUNCTION market.guard_quote_time();
CREATE TRIGGER guard_benchmark_time BEFORE INSERT OR UPDATE ON market.market_benchmarks
    FOR EACH ROW EXECUTE FUNCTION market.guard_quote_time();

CREATE FUNCTION analysis.guard_evaluation_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prediction_cycle uuid; run_officiality text; cycle_status text;
BEGIN
    SELECT r.event_cycle_id, r.officiality, c.status INTO prediction_cycle, run_officiality, cycle_status
        FROM analysis.model_predictions p
        JOIN analysis.analysis_markets m USING (analysis_market_id)
        JOIN analysis.analysis_runs r USING (analysis_run_id)
        JOIN event.event_cycles c USING (event_cycle_id)
        WHERE p.prediction_id = NEW.prediction_id;
    IF prediction_cycle IS DISTINCT FROM NEW.event_cycle_id THEN
        RAISE EXCEPTION 'evaluation cannot cross event cycles' USING ERRCODE = '23514';
    END IF;
    IF NEW.included_in_metrics AND (run_officiality <> 'OFFICIAL' OR cycle_status <> 'FINALIZED') THEN
        RAISE EXCEPTION 'official finalized prediction required for live metrics' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_evaluation_cycle BEFORE INSERT OR UPDATE ON analysis.prediction_evaluations
    FOR EACH ROW EXECUTE FUNCTION analysis.guard_evaluation_cycle();

CREATE FUNCTION analysis.guard_edge() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prediction_market uuid; benchmark_market uuid; p double precision; q double precision;
BEGIN
    SELECT analysis_market_id INTO prediction_market FROM analysis.model_predictions WHERE prediction_id = NEW.prediction_id;
    SELECT analysis_market_id INTO benchmark_market FROM market.market_benchmarks WHERE benchmark_id = NEW.benchmark_id;
    SELECT probability INTO p FROM analysis.prediction_outcomes
        WHERE prediction_id = NEW.prediction_id AND outcome_code = NEW.outcome_code;
    SELECT no_vig_probability INTO q FROM market.benchmark_outcomes
        WHERE benchmark_id = NEW.benchmark_id AND outcome_code = NEW.outcome_code;
    IF prediction_market IS DISTINCT FROM benchmark_market OR p IS DISTINCT FROM NEW.model_probability
        OR q IS DISTINCT FROM NEW.market_probability THEN
        RAISE EXCEPTION 'edge must use matching market and stored outcome probabilities' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_edge BEFORE INSERT OR UPDATE ON analysis.prediction_edges
    FOR EACH ROW EXECUTE FUNCTION analysis.guard_edge();

CREATE FUNCTION ml.guard_deployment() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Serialize deployments within each family, including concurrent transactions.
    PERFORM 1 FROM ml.model_families WHERE model_family_id = NEW.model_family_id FOR UPDATE;
    IF TG_OP = 'INSERT' THEN
        IF NEW.valid_from < clock_timestamp() OR NEW.prospective_track_start < NEW.valid_from THEN
            RAISE EXCEPTION 'deployment must begin prospectively' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM ml.model_versions WHERE model_version_id = NEW.model_version_id
            AND status IN ('VALIDATED','PRODUCTION')) THEN
            RAISE EXCEPTION 'deployment requires a validated artifact' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF (to_jsonb(NEW) - 'valid_to') IS DISTINCT FROM (to_jsonb(OLD) - 'valid_to')
            OR OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL OR NEW.valid_to < clock_timestamp() THEN
            RAISE EXCEPTION 'deployment history is immutable except prospective closure' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM ml.model_deployments d WHERE d.model_family_id = NEW.model_family_id
        AND d.deployment_id <> NEW.deployment_id
        AND tstzrange(d.valid_from, d.valid_to, '[)') && tstzrange(NEW.valid_from, NEW.valid_to, '[)')) THEN
        RAISE EXCEPTION 'deployment periods overlap' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_deployment BEFORE INSERT OR UPDATE ON ml.model_deployments
    FOR EACH ROW EXECUTE FUNCTION ml.guard_deployment();
CREATE TRIGGER no_delete_deployment BEFORE DELETE ON ml.model_deployments
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();

CREATE FUNCTION paper.guard_policy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'policy history cannot be deleted' USING ERRCODE = '23514';
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.valid_from < clock_timestamp() THEN
            RAISE EXCEPTION 'policy activation must be prospective' USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.frozen THEN
        IF (to_jsonb(NEW) - 'valid_to') IS DISTINCT FROM (to_jsonb(OLD) - 'valid_to')
            OR OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL OR NEW.valid_to < clock_timestamp() THEN
            RAISE EXCEPTION 'frozen policy requires a new version' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.frozen AND NEW.valid_from < clock_timestamp() THEN
        RAISE EXCEPTION 'cannot freeze policy retroactively' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_policy BEFORE INSERT OR UPDATE OR DELETE ON paper.paper_policies
    FOR EACH ROW EXECUTE FUNCTION paper.guard_policy();

CREATE FUNCTION paper.guard_bet() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE policy paper.paper_policies; prediction analysis.model_predictions;
BEGIN
    SELECT * INTO policy FROM paper.paper_policies WHERE paper_policy_id = NEW.paper_policy_id FOR SHARE;
    SELECT * INTO prediction FROM analysis.model_predictions WHERE prediction_id = NEW.prediction_id;
    IF NOT policy.frozen OR NEW.placed_at < policy.valid_from OR
        (policy.valid_to IS NOT NULL AND NEW.placed_at >= policy.valid_to) THEN
        RAISE EXCEPTION 'paper policy not active at placement' USING ERRCODE = '23514';
    END IF;
    IF policy.requires_no_bet_false AND prediction.no_bet THEN
        RAISE EXCEPTION 'paper policy excludes NO BET predictions' USING ERRCODE = '23514';
    END IF;
    IF NEW.placed_at < prediction.generated_at THEN
        RAISE EXCEPTION 'paper bet predates prediction' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM analysis.prediction_edges e WHERE e.prediction_id = NEW.prediction_id
        AND e.outcome_code = NEW.outcome_code AND e.edge_pp > 0 AND e.is_value_side) THEN
        RAISE EXCEPTION 'paper bet requires positive edge value side' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status') THEN
        RAISE EXCEPTION 'paper bet decision is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_paper_bet BEFORE INSERT OR UPDATE ON paper.paper_bets
    FOR EACH ROW EXECUTE FUNCTION paper.guard_bet();
CREATE TRIGGER no_delete_paper_bet BEFORE DELETE ON paper.paper_bets
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();

CREATE FUNCTION paper.guard_settlement_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prediction_cycle uuid;
BEGIN
    SELECT r.event_cycle_id INTO prediction_cycle FROM paper.paper_bets b
        JOIN analysis.model_predictions p USING (prediction_id)
        JOIN analysis.analysis_markets m USING (analysis_market_id)
        JOIN analysis.analysis_runs r USING (analysis_run_id)
        WHERE b.paper_bet_id = NEW.paper_bet_id;
    IF prediction_cycle IS DISTINCT FROM NEW.event_cycle_id THEN
        RAISE EXCEPTION 'paper settlement cannot cross event cycles' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_settlement_cycle BEFORE INSERT OR UPDATE ON paper.paper_bet_settlements
    FOR EACH ROW EXECUTE FUNCTION paper.guard_settlement_cycle();

CREATE FUNCTION provider.queue_ambiguous_mapping() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.mapping_status = 'PENDING_REVIEW' THEN
        INSERT INTO ops.review_queue(review_type, mapping_id, reason_code)
            VALUES ('ENTITY_MAPPING', NEW.mapping_id, 'AMBIGUOUS_MAPPING')
            ON CONFLICT (mapping_id) WHERE status = 'PENDING' AND mapping_id IS NOT NULL DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER queue_ambiguous_mapping AFTER INSERT OR UPDATE ON provider.entity_mappings
    FOR EACH ROW EXECUTE FUNCTION provider.queue_ambiguous_mapping();

-- Durable, atomic leases. Tokens never repeat, including after deletion/release.
CREATE FUNCTION ops.acquire_event_lock(cycle uuid, owner_run uuid, ttl interval)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE token bigint; moment timestamptz := clock_timestamp();
BEGIN
    IF ttl <= interval '0 seconds' OR ttl > interval '1 hour' OR ttl IS NULL THEN
        RAISE EXCEPTION 'lock TTL must be positive and at most one hour' USING ERRCODE = '22023';
    END IF;
    INSERT INTO ops.event_locks(event_cycle_id, owner_analysis_run_id, fencing_token, acquired_at, heartbeat_at, expires_at)
        VALUES (cycle, owner_run, nextval('ops.lock_fence_sequence'), moment, moment, moment + ttl)
        ON CONFLICT (event_cycle_id) DO UPDATE SET
            owner_analysis_run_id = EXCLUDED.owner_analysis_run_id,
            fencing_token = EXCLUDED.fencing_token,
            acquired_at = EXCLUDED.acquired_at,
            heartbeat_at = EXCLUDED.heartbeat_at,
            expires_at = EXCLUDED.expires_at
        WHERE ops.event_locks.expires_at <= moment
        RETURNING fencing_token INTO token;
    RETURN token;
END;
$$;
CREATE FUNCTION ops.heartbeat_event_lock(cycle uuid, owner_run uuid, fence bigint, ttl interval)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE moment timestamptz := clock_timestamp(); affected integer;
BEGIN
    IF ttl <= interval '0 seconds' OR ttl > interval '1 hour' OR ttl IS NULL THEN
        RAISE EXCEPTION 'lock TTL must be positive and at most one hour' USING ERRCODE = '22023';
    END IF;
    UPDATE ops.event_locks SET heartbeat_at = moment, expires_at = moment + ttl
        WHERE event_cycle_id = cycle AND owner_analysis_run_id = owner_run
        AND fencing_token = fence AND expires_at > moment;
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected = 1;
END;
$$;
CREATE FUNCTION ops.release_event_lock(cycle uuid, owner_run uuid, fence bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE affected integer;
BEGIN
    DELETE FROM ops.event_locks WHERE event_cycle_id = cycle AND owner_analysis_run_id = owner_run
        AND fencing_token = fence AND expires_at > clock_timestamp();
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected = 1;
END;
$$;

INSERT INTO catalog.sports(sport_id, code, name) VALUES
    (1, 'FOOTBALL', 'Fútbol'), (2, 'BASKETBALL', 'Básquet'), (3, 'BASEBALL', 'Béisbol');
INSERT INTO market.bookmakers(code, name, jurisdiction, is_primary)
    VALUES ('BETANO_PE', 'Betano Perú', 'PE', true);
-- Infrastructure only: prediction activation requires a validated model and later phase.
INSERT INTO market.market_definitions
    (market_code,sport_id,display_name,scope,subject_type,outcome_structure,supports_line,supports_push,supports_asian)
VALUES
    ('FOOTBALL_TOTAL_GOALS',1,'Goles totales','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('FOOTBALL_BTTS',1,'Ambos equipos anotan','FULL_GAME','EVENT','TWO_WAY',false,false,false),
    ('FOOTBALL_TOTAL_CORNERS',1,'Corners totales','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('FOOTBALL_FIRST_HALF_CORNERS',1,'Corners primer tiempo','FIRST_HALF','EVENT','TWO_WAY',true,true,true),
    ('FOOTBALL_TOTAL_CARDS',1,'Tarjetas totales','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('FOOTBALL_SHOTS',1,'Remates totales','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('FOOTBALL_SHOTS_ON_TARGET',1,'Tiros al arco','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('BASKETBALL_TOTAL',2,'Puntos totales','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('BASKETBALL_HANDICAP',2,'Handicap','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('BASKETBALL_FIRST_HALF_TOTAL',2,'Puntos primer tiempo','FIRST_HALF','EVENT','TWO_WAY',true,true,true),
    ('BASKETBALL_FIRST_HALF_HANDICAP',2,'Handicap primer tiempo','FIRST_HALF','EVENT','TWO_WAY',true,true,true),
    ('BASKETBALL_PLAYER_POINTS',2,'Puntos jugador','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_REBOUNDS',2,'Rebotes jugador','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_ASSISTS',2,'Asistencias jugador','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_THREES',2,'Triples anotados jugador','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_THREE_ATTEMPTS',2,'Intentos de tres jugador','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_POINTS_REBOUNDS_ASSISTS',2,'Puntos + rebotes + asistencias','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_POINTS_REBOUNDS',2,'Puntos + rebotes','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_POINTS_ASSISTS',2,'Puntos + asistencias','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASKETBALL_PLAYER_REBOUNDS_ASSISTS',2,'Rebotes + asistencias','FULL_GAME','PLAYER','TWO_WAY',true,true,false),
    ('BASEBALL_WINNER',3,'Ganador','FULL_GAME','EVENT','TWO_WAY',false,false,false),
    ('BASEBALL_RUN_LINE',3,'Run line','FULL_GAME','EVENT','TWO_WAY',true,true,true),
    ('BASEBALL_TOTAL',3,'Carreras totales','FULL_GAME','EVENT','TWO_WAY',true,true,true);
