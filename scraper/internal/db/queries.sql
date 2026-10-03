-- name: UpsertDocument :one
-- Idempotent write: a retried WriteDocument activity (Temporal at-least-once
-- semantics) lands on the same row instead of inserting a duplicate,
-- because normalized_url is unique -- one row per URL, always reflecting
-- its most recently crawled state. A retry with unchanged content is a
-- no-op update; a genuinely changed page (recrawled after RevisitAfter,
-- see CheckFreshness) has its fields refreshed in place rather than
-- accumulating a second row for the same URL.
INSERT INTO documents (
    url, normalized_url, category, title, body_text, links, depth,
    status_code, content_type, content_hash, fetch_duration_ms, fetch_error,
    fetched_at, json_ld, geo_lat, geo_lng, anchor_texts, crawl_run_id,
    canonical_url, final_url, sim_hash, meta_description, headings, host,
    country
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25
)
ON CONFLICT (normalized_url) DO UPDATE SET
    url               = EXCLUDED.url,
    category          = EXCLUDED.category,
    title             = EXCLUDED.title,
    body_text         = EXCLUDED.body_text,
    links             = EXCLUDED.links,
    depth             = EXCLUDED.depth,
    status_code       = EXCLUDED.status_code,
    content_type      = EXCLUDED.content_type,
    content_hash      = EXCLUDED.content_hash,
    fetch_duration_ms = EXCLUDED.fetch_duration_ms,
    fetch_error       = EXCLUDED.fetch_error,
    fetched_at        = EXCLUDED.fetched_at,
    json_ld           = EXCLUDED.json_ld,
    geo_lat           = EXCLUDED.geo_lat,
    geo_lng           = EXCLUDED.geo_lng,
    anchor_texts      = EXCLUDED.anchor_texts,
    crawl_run_id      = EXCLUDED.crawl_run_id,
    canonical_url     = EXCLUDED.canonical_url,
    final_url         = EXCLUDED.final_url,
    sim_hash          = EXCLUDED.sim_hash,
    meta_description  = EXCLUDED.meta_description,
    headings          = EXCLUDED.headings,
    host              = EXCLUDED.host,
    country           = EXCLUDED.country,
    updated_at        = now()
RETURNING id;

-- name: CreateCrawlRun :one
INSERT INTO crawl_runs (seed_count, max_depth, max_pages)
VALUES ($1, $2, $3)
RETURNING id;

-- name: UpdateCrawlRunStats :exec
-- Called after every page processed within a run (including mid-run, before
-- Continue-As-New) so a run's progress is visible while it's still going,
-- not just after it finishes.
UPDATE crawl_runs SET
    fetched       = $2,
    succeeded     = $3,
    failed        = $4,
    skipped       = $5,
    domain_capped = $6,
    updated_at    = now()
WHERE id = $1;

-- name: FinishCrawlRun :exec
UPDATE crawl_runs SET
    status        = $2,
    fetched       = $3,
    succeeded     = $4,
    failed        = $5,
    skipped       = $6,
    domain_capped = $7,
    error         = $8,
    finished_at   = now(),
    updated_at    = now()
WHERE id = $1;

-- name: GetCrawlRun :one
SELECT * FROM crawl_runs WHERE id = $1;

-- name: ListCrawlRuns :many
SELECT * FROM crawl_runs ORDER BY started_at DESC LIMIT $1 OFFSET $2;

-- name: CountDocuments :one
SELECT count(*) FROM documents;

-- name: CountDocumentsByCategory :many
SELECT category, count(*) AS total FROM documents GROUP BY category ORDER BY category;

-- name: ListFreshDocumentURLs :many
-- Given a batch of candidate normalized URLs, returns the subset that
-- already have a document fetched more recently than `since` -- the
-- revisit/freshness policy's core check: skip re-fetching a URL that was
-- crawled recently enough, but allow one that's stale or was never crawled
-- (never crawled simply won't appear in the result, which is what
-- "startable" means to the caller).
SELECT normalized_url FROM documents
WHERE normalized_url = ANY(sqlc.arg(normalized_urls)::text[])
  AND fetched_at > sqlc.arg(since)::timestamptz;

-- name: ListDocumentsByCategory :many
-- crawl_run_id and country are optional additional filters: pass NULL to
-- ignore either (all documents in the category), or a specific run's ID /
-- ISO 3166-1 alpha-2 country code to narrow further -- e.g. an ETL
-- consumer scoped to only Nepal-origin documents (country = 'NP').
SELECT * FROM documents
WHERE category = $1
  AND (sqlc.narg('crawl_run_id')::bigint IS NULL OR crawl_run_id = sqlc.narg('crawl_run_id'))
  AND (sqlc.narg('country')::text IS NULL OR country = sqlc.narg('country'))
ORDER BY fetched_at DESC LIMIT $2 OFFSET $3;
