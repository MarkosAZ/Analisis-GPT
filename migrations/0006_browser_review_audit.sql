-- Review references are public capture IDs only, never page/account contents.
ALTER TABLE ops.review_queue ADD COLUMN browser_observation_id uuid
    REFERENCES provider.browser_observations;
CREATE UNIQUE INDEX review_queue_browser_pending ON ops.review_queue(browser_observation_id)
    WHERE status = 'PENDING' AND browser_observation_id IS NOT NULL;
CREATE TRIGGER immutable_tracking_commands BEFORE UPDATE OR DELETE ON ops.tracking_commands
    FOR EACH ROW EXECUTE FUNCTION ops.reject_mutation();
