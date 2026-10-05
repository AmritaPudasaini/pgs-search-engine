-- Queries against the shared schema, owned by database/ (pgs_db models + Alembic);
-- sqlc reads it from database/sql/scraper_schema.sql, exported from those models. The writes are the statements of
-- database/docs/scraper-db-contract.md.

-- name: UpsertCrawledDocument :one
-- Keyed on (normalized_url, content_hash): a retried WriteDocument activity
-- (Temporal at-least-once) or a re-crawl of unchanged content updates the same
-- row; changed content adds a new version row. domain_id is resolved from the
-- host, without www. (domains are stored that way, see pgs_db site_host); NULL for
-- a host that isn't a registered domain -- the page still stores.
-- inserted is true only for a genuinely new row.
INSERT INTO crawled_documents (
    crawl_run_id, domain_id, url, normalized_url, final_url, canonical_url, host, category,
    title, meta_description, meta_keywords, open_graph, text, headings, json_ld,
    emails, phones, address, social_links, links, anchor_texts,
    internal_links, external_links, image_links, video_links,
    geo_lat, geo_lng, country, sim_hash, depth, status_code, content_type,
    content_hash, fetched_at, fetch_duration_ms, error
) VALUES (
    sqlc.narg('crawl_run_id'),
    (SELECT d.id FROM domains d WHERE d.domain = regexp_replace(lower(sqlc.narg('host')::text), '^www\.', '')),
    sqlc.arg('url'), sqlc.arg('normalized_url'), sqlc.narg('final_url'), sqlc.narg('canonical_url'),
    sqlc.narg('host'), sqlc.narg('category'),
    sqlc.narg('title'), sqlc.narg('meta_description'), sqlc.narg('meta_keywords'),
    sqlc.narg('open_graph'), sqlc.narg('text'), sqlc.narg('headings'), sqlc.narg('json_ld'),
    sqlc.narg('emails'), sqlc.narg('phones'), sqlc.narg('address'), sqlc.narg('social_links'),
    sqlc.narg('links'), sqlc.narg('anchor_texts'),
    sqlc.narg('internal_links'), sqlc.narg('external_links'), sqlc.narg('image_links'),
    sqlc.narg('video_links'),
    sqlc.narg('geo_lat'), sqlc.narg('geo_lng'), sqlc.narg('country'), sqlc.narg('sim_hash'),
    sqlc.arg('depth'), sqlc.narg('status_code'), sqlc.narg('content_type'),
    sqlc.arg('content_hash'), sqlc.arg('fetched_at'), sqlc.narg('fetch_duration_ms'),
    sqlc.narg('error')
)
ON CONFLICT (normalized_url, content_hash) DO UPDATE SET
    crawl_run_id      = EXCLUDED.crawl_run_id,
    domain_id         = EXCLUDED.domain_id,
    url               = EXCLUDED.url,
    final_url         = EXCLUDED.final_url,
    canonical_url     = EXCLUDED.canonical_url,
    host              = EXCLUDED.host,
    category          = EXCLUDED.category,
    title             = EXCLUDED.title,
    meta_description  = EXCLUDED.meta_description,
    meta_keywords     = EXCLUDED.meta_keywords,
    open_graph        = EXCLUDED.open_graph,
    text              = EXCLUDED.text,
    headings          = EXCLUDED.headings,
    json_ld           = EXCLUDED.json_ld,
    emails            = EXCLUDED.emails,
    phones            = EXCLUDED.phones,
    address           = EXCLUDED.address,
    social_links      = EXCLUDED.social_links,
    links             = EXCLUDED.links,
    anchor_texts      = EXCLUDED.anchor_texts,
    internal_links    = EXCLUDED.internal_links,
    external_links    = EXCLUDED.external_links,
    image_links       = EXCLUDED.image_links,
    video_links       = EXCLUDED.video_links,
    geo_lat           = EXCLUDED.geo_lat,
    geo_lng           = EXCLUDED.geo_lng,
    country           = EXCLUDED.country,
    sim_hash          = EXCLUDED.sim_hash,
    depth             = EXCLUDED.depth,
    status_code       = EXCLUDED.status_code,
    content_type      = EXCLUDED.content_type,
    fetched_at        = EXCLUDED.fetched_at,
    fetch_duration_ms = EXCLUDED.fetch_duration_ms,
    error             = EXCLUDED.error
RETURNING id, (xmax = 0)::boolean AS inserted;

-- name: CreateCrawlRun :one
INSERT INTO crawl_runs (
    status, started_at, seed_count, max_depth, max_pages,
    fetched_count, succeeded_count, failed_count, skipped_count, unique_url_count
) VALUES ('RUNNING', now(), $1, $2, $3, 0, 0, 0, 0, 0)
RETURNING id;

-- name: UpdateCrawlRunStats :exec
-- Called during a run (including before a Continue-As-New), so a run's progress
-- is visible while it is still going.
UPDATE crawl_runs SET
    fetched_count       = $2,
    succeeded_count     = $3,
    failed_count        = $4,
    skipped_count       = $5,
    domain_capped_count = $6
WHERE id = $1;

-- name: FinishCrawlRun :exec
-- status is 'completed' or 'failed' (any case; a trigger upper-cases it). error is
-- NULL for a run that completed.
UPDATE crawl_runs SET
    status              = sqlc.arg('status'),
    fetched_count       = sqlc.arg('fetched_count'),
    succeeded_count     = sqlc.arg('succeeded_count'),
    failed_count        = sqlc.arg('failed_count'),
    skipped_count       = sqlc.arg('skipped_count'),
    domain_capped_count = sqlc.arg('domain_capped_count'),
    error               = sqlc.narg('error'),
    finished_at         = now()
WHERE id = sqlc.arg('id');

-- name: GetCrawlRun :one
SELECT * FROM crawl_runs WHERE id = $1;

-- name: ListCrawlRuns :many
SELECT * FROM crawl_runs ORDER BY started_at DESC LIMIT $1 OFFSET $2;

-- name: CountDocuments :one
SELECT count(*) FROM crawled_documents;

-- name: CountDocumentsByCategory :many
SELECT coalesce(category, '')::text AS category, count(*) AS total
FROM crawled_documents GROUP BY 1 ORDER BY 1;

-- name: ListFreshDocumentURLs :many
-- The subset of the candidate URLs with any version fetched after `since`: the
-- revisit policy skips those; a URL never crawled simply isn't returned.
SELECT DISTINCT normalized_url FROM crawled_documents
WHERE normalized_url = ANY(sqlc.arg(normalized_urls)::text[])
  AND fetched_at > sqlc.arg(since)::timestamptz;

-- name: ListDocumentsByCategory :many
-- crawl_run_id and country are optional filters: NULL ignores them.
SELECT * FROM crawled_documents
WHERE category = sqlc.arg('category')::text
  AND (sqlc.narg('crawl_run_id')::bigint IS NULL OR crawl_run_id = sqlc.narg('crawl_run_id'))
  AND (sqlc.narg('country')::text IS NULL OR country = sqlc.narg('country'))
ORDER BY fetched_at DESC LIMIT sqlc.arg('limit') OFFSET sqlc.arg('offset');
