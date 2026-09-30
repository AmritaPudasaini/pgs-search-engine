-- crawl_runs is the per-crawl health/validation record other teams can
-- check before consuming a batch of documents: was this run complete, how
-- many pages succeeded vs failed vs were skipped, and when did it run.
CREATE TABLE crawl_runs (
    id            BIGSERIAL PRIMARY KEY,
    -- running: in progress (including mid-Continue-As-New segments).
    -- completed: finished normally (ran out of queue/budget).
    -- failed: the workflow itself errored out (not the same as individual
    -- page fetch failures, which are just counted in `failed`).
    status        TEXT NOT NULL DEFAULT 'running',
    seed_count    INTEGER NOT NULL DEFAULT 0,
    max_depth     INTEGER NOT NULL DEFAULT 0,
    max_pages     INTEGER NOT NULL DEFAULT 0,
    fetched       INTEGER NOT NULL DEFAULT 0,
    succeeded     INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    domain_capped INTEGER NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT '',
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_crawl_runs_status ON crawl_runs (status);
