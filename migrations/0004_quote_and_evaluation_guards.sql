ALTER TABLE market.market_benchmarks ADD CONSTRAINT benchmark_source_time
    CHECK (source_snapshot_at <= available_at AND source_snapshot_at <= calculated_at);

CREATE FUNCTION market.check_proportional_quote() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid := NEW.quote_id; quote market.selected_quotes; implied_sum double precision;
BEGIN
    SELECT * INTO quote FROM market.selected_quotes WHERE quote_id=target;
    SELECT sum(implied_probability) INTO implied_sum FROM market.selected_quote_outcomes WHERE quote_id=target;
    IF implied_sum IS NULL OR abs(quote.overround-(implied_sum-1)) > 0.000001 THEN
        RAISE EXCEPTION 'quote overround must match original prices' USING ERRCODE = '23514';
    END IF;
    IF quote.devig_method='PROPORTIONAL_V1' AND EXISTS (
        SELECT 1 FROM market.selected_quote_outcomes WHERE quote_id=target
            AND abs(no_vig_probability-implied_probability/implied_sum)>0.000001
    ) THEN
        RAISE EXCEPTION 'quote probabilities must match the declared de-vig method' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER proportional_quote AFTER INSERT ON market.selected_quotes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION market.check_proportional_quote();
CREATE CONSTRAINT TRIGGER proportional_quote_outcomes AFTER INSERT ON market.selected_quote_outcomes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION market.check_proportional_quote();

-- A decision just before a holdout starts must not expose the result of an event
-- inside it. Both the decision window and the sporting cycle protect the label.
ALTER POLICY evaluation_visibility ON analysis.prediction_evaluations USING (
    ml.cycle_evaluation_is_open(event_cycle_id) AND EXISTS (
        SELECT 1 FROM analysis.model_predictions p JOIN analysis.analysis_markets m USING(analysis_market_id)
            JOIN analysis.analysis_runs r USING(analysis_run_id)
        WHERE p.prediction_id=prediction_evaluations.prediction_id
            AND ml.evaluation_time_is_open(r.decision_time)));
ALTER POLICY evaluation_ingestion ON analysis.prediction_evaluations WITH CHECK (
    ml.cycle_evaluation_is_open(event_cycle_id) AND EXISTS (
        SELECT 1 FROM analysis.model_predictions p JOIN analysis.analysis_markets m USING(analysis_market_id)
            JOIN analysis.analysis_runs r USING(analysis_run_id)
        WHERE p.prediction_id=prediction_evaluations.prediction_id
            AND ml.evaluation_time_is_open(r.decision_time)));
