# search-engine-scraper — 6-Person Task Split

This document divides work on this repo — a Go web crawler orchestrated by
Temporal, writing crawled documents as objects in **S3** and served through
a small read API — across **6 people**, with **10 commits each** (60
commits total). Each person owns a clear slice of the codebase so work
doesn't collide. Copy your section, work through the checklist top to
bottom, and commit once per item (squash later if you prefer a cleaner
history).

## Scope

This repo's scope is **scraping only**. Indexing, ranking/search, and UI
are out of scope — that is a separate team/repo consuming this crawler's
output (see `docs/CRAWLER_ROADMAP.md`, "Explicitly out of scope"). Nothing
in this task split adds indexing, a ranking algorithm, or a search UI.
Every item below stays inside packages that exist in this repo today, or
are called out explicitly as new.

**Storage is S3-only for this split.** The Postgres backend
(`internal/db/`, `migrations/`, `--storage=postgres`) is being retired in
favor of an S3-backed `storage.Writer`. Object keys are content-addressed —
`{crawl_run_id}/{sha256(normalized_url)}.json` — so concurrent workers
writing the same document overwrite the same key with identical bytes; no
central DB is needed for replica-safe dedupe. Run metadata (status,
counts) lives in a per-run manifest object, `{crawl_run_id}/_run.json`,
read-modify-written by whichever worker owns that run. NDJSON-to-local-file
remains only as a `--storage=ndjson` dev fallback with no freshness/listing
support (same as today).

Reference docs before starting:
- `README.md` — project layout, how it works, flags, scaling
- `docs/GETTING_STARTED.md` — fastest path to a running crawl
- `docs/CRAWLER_ROADMAP.md` — what's been fixed and why, known limitations
- `docs/RESILIENCE.md` — crash-recovery verification
- `internal/api/openapi.yaml` — the API contract

## How to work

1. Clone the repo and `cd` into it.
2. Create your own branch off `main`: `git checkout -b <your-name>/<area>`
3. Work through your 10-item checklist below, one commit per item.
4. Push your branch: `git push -u origin <your-name>/<area>`
5. Open a pull request into `main` when done, or as you go.
6. Run `go build ./...` and `go test ./...` before every commit that touches
   Go code. Run `make run` + `make crawl SEEDS=...` against a local S3
   stack (LocalStack, see Person 1) before calling an S3-touching change
   done — mocked S3 tests alone aren't enough to catch bucket/IAM/key
   issues.

---

## Person 1 — Build, Ops & Entry Points

Owns: `cmd/api/`, `cmd/scraper/`, `cmd/worker/`, `Dockerfile.*`,
`docker-compose.yml`, `k8s/`, `Makefile`.

1. Audit `cmd/scraper/main.go` and `cmd/worker/main.go` flag parsing against
   the flag tables in `README.md`; fix any drift between the two
2. Review `Dockerfile.worker` / `Dockerfile.scraper` / `Dockerfile.api`
   multi-stage builds for image size / layer caching improvements
3. Replace the Postgres service in `docker-compose.yml` with a LocalStack
   (or MinIO) container providing an S3-compatible endpoint for local dev;
   wire `--s3-endpoint`, `--s3-bucket`, `--aws-region` into the
   worker/api service definitions
4. Review `k8s/` manifests: drop the Postgres `StatefulSet`/`Secret`
   (`01-postgres.yaml`), add IAM role/service-account wiring (IRSA or
   equivalent) so worker/api pods can reach the real S3 bucket without
   static credentials
5. Verify `make scale SCALE=N` and `make down` behave as documented,
   updating both for the LocalStack service in place of Postgres
6. Add/verify a CI workflow: `go build ./...`, `go vet ./...`, `go test
   ./...`
7. Add/verify `golangci-lint` (or equivalent) config and wire it into `make`
8. Confirm `cmd/api/main.go` boots the API server independently of the
   worker/scraper (no accidental coupling), reading only from S3
9. Cross-check `Makefile` targets (bucket bootstrap/creation for local
   LocalStack, `make devs3-up` or similar) match what's described in
   `docs/GETTING_STARTED.md`; remove any remaining `migrate`/`sqlc` targets
10. Review and merge Person 2–6 branches; resolve structural conflicts

---

## Person 2 — Discovery, Frontier & Workflow

Owns: `internal/workflows/`, `internal/seeds/`, `internal/sitemap/`,
`internal/robots/`.
Ref: `README.md` "How it works", `docs/CRAWLER_ROADMAP.md` items 6, 11, 12.

1. Review `CrawlWorkflow`'s frontier (queue + seen-set) logic in
   `crawl_workflow.go` for correctness under `MaxConcurrentPerHost` and
   `MaxPagesPerDomain`
2. Review Continue-As-New handoff: confirm `Seen`, `DomainCounts`,
   `SimHashes` carry forward correctly across segments
3. Review priority-based scheduling (`[category priority]` seed-list syntax)
   against `internal/seeds` parsing
4. Review `internal/sitemap` parsing (urlset + sitemapindex) and its caps
   (`maxChildSitemaps`, `maxSitemapURLs`)
5. Review `internal/robots` sitemap-directive collection and crawl-delay
   handling
6. Add/extend workflow-level tests in `crawl_workflow_test.go` for any
   scheduling edge case not yet covered
7. Verify the run-tracking status transitions (`running`/`completed`/
   `failed`) are accurate for every exit path now that the manifest object
   in S3 (`{crawl_run_id}/_run.json`), not a Postgres row, is the source of
   truth
8. Verify `docs/RESILIENCE.md`'s kill-9-mid-crawl claim still holds against
   the S3 backend; re-run the test and update the doc if behavior changed
9. Document how to add a new seed-list category (update `README.md` or a
   new doc under `docs/`)
10. Write/expand tests for `internal/seeds` file parsing (malformed
    sections, missing priority, duplicate URLs)

---

## Person 3 — Fetch, Parse & Dedup

Owns: `internal/fetcher/`, `internal/parser/`, `internal/normalize/`,
`internal/simhash/`.
Ref: `docs/CRAWLER_ROADMAP.md` items 2, 3, 4, 8–10, 13–15.

1. Review `internal/fetcher` politeness (per-domain rate limit, UA, body
   size cap, timeouts) and redirect-chain tracking
   (`FinalURL`/`RedirectChain`)
2. Review `internal/parser` HTML extraction (title, text, links, JSON-LD,
   OpenGraph/meta geo fields, anchor texts, canonical URL)
3. Review boilerplate stripping (`boilerplateTags`, link-density threshold)
   for false positives/negatives on real pages
4. Review charset/encoding detection (`charset.NewReader` precedence) with
   a non-UTF-8 fixture
5. Review `<meta name="robots">` / `X-Robots-Tag` directive parsing
   (`ParseRobotsDirectives`) for edge cases (bot-scoped prefixes, `none`
   shorthand)
6. Review `internal/normalize` URL canonicalization + relative-link
   resolution against tricky inputs (fragments, trailing slashes, ports) —
   this is what feeds the S3 object key hash, so a normalization bug now
   means two different keys for the same logical document
7. Review `internal/simhash`'s near-duplicate threshold
   (`nearDupHammingThreshold`) and `minTextLenForNearDupCheck` guard
8. Add fixtures/tests for any HTML edge case not covered
   (malformed JSON-LD, nested `geo` under `Place`, ISO-8859-1 pages)
9. Benchmark `parser.Parse` on a large real page and note any hotspot
10. Document known parser limitations (e.g. div-level link-density gap)
    that aren't already captured in `docs/CRAWLER_ROADMAP.md`

---

## Person 4 — S3 Storage & Data Integrity

Owns: `internal/storage/`, `internal/model/`. (`internal/db/` and
`migrations/` are being deleted as part of the Postgres retirement — see
item 1, and the coordination note below.)
Ref: `README.md` "Database" section (being replaced), item 7 below.

> **Coordination blocker found (2026-09-29):** `internal/db/` isn't only
> `internal/storage/postgres.go`'s dependency — `cmd/api/main.go` and
> `internal/api/server.go` (Person 1's and Person 5's files) construct the
> API server directly from a `pgxpool.Pool` + `db.Queries`
> (`api.NewServer(db.New(pool))`), so deleting `internal/db/` here breaks
> `go build ./...` for code this branch doesn't own and can't fix without
> doing Person 5's item 1 (`Rework internal/api/server.go ... to read from
> S3`) preemptively. Item 1 below is adjusted: **add** the S3 backend and
> leave `internal/db/`/`migrations/`/`postgres.go` in place for now: this
> branch only deletes them, and updates `cmd/worker`'s `--storage=postgres`
> case, once Person 5's API rework has landed. This is an expand-then-
> contract migration, not a same-PR swap.

1. ~~Delete `internal/db/`, `migrations/`, `postgres.go`/
   `postgres_test.go`; remove `sqlc` from the toolchain and `Makefile`~~
   **Deferred** — see the coordination note above. Instead: wire
   `--storage=s3` into `cmd/worker` as a new, additional option (items
   2-4 below), leaving `--storage=postgres` and everything it depends on
   untouched until Person 5's API rework lands.
2. Implement `storage.S3Writer` (new `s3_writer.go`) satisfying the
   existing `Writer` interface: `PutObject` to
   `{crawl_run_id}/{sha256(normalized_url)}.json`, content-type
   `application/json`, with retry/backoff on throttling
3. Implement an S3-backed `FreshnessChecker`: batched `HeadObject` calls
   (bounded concurrency) returning `LastModified` per key, replacing the
   Postgres `ListFreshDocumentURLs` query; document the added S3 API-call
   cost per crawl compared to the old single query
4. Implement an S3-backed `RunRecorder`: read-modify-write the
   `{crawl_run_id}/_run.json` manifest (status, counts, timestamps) with a
   conditional `PutObject` (`If-Match` on ETag) to avoid lost updates from
   concurrent workers on the same run
5. Review `internal/model.Document` field-by-field against
   `internal/api/openapi.yaml` for drift now that the JSON shape written to
   S3 *is* the API's read shape
6. Add `s3_writer_test.go` / `s3_freshness_test.go` against a LocalStack
   container (nil-slice fields, empty JSON-LD, oversized documents,
   duplicate-key overwrite is a no-op)
7. Verify duplicate-content-hash collapse: two different `normalized_url`s
   whose content hashes to the same simhash should NOT collide on the S3
   key (key is derived from URL, not content) — write a test proving that
8. Add a bucket layout doc: key scheme, manifest object shape, lifecycle
   policy recommendation (e.g. expire stale run manifests), in
   `docs/SCHEMA.md`
9. Load-test listing/paginating a large `crawl_run_id` prefix with
   `ListObjectsV2` (1M+ objects) and note pagination/latency behavior
10. Verify NDJSON dev-fallback writer (`--storage=ndjson`) still works
    unchanged and is clearly documented as having no freshness/listing
    support (same limitation as before, just no longer "the alternative to
    Postgres" — now "the alternative to S3")

---

## Person 5 — API & Observability

Owns: `internal/api/`, `internal/metrics/`, `internal/envflag/`.
Ref: `README.md` §API, `docs/CRAWLER_ROADMAP.md` items 6, 16.

1. Rework `internal/api/server.go` route handlers to read from S3
   (`ListObjectsV2` + `GetObject`) instead of Postgres; keep the same
   `openapi.yaml` response shapes so downstream consumers see no change
2. Review `GET /api/v1/crawl-runs` and `GET /api/v1/crawl-runs/{id}`:
   list run manifests via `ListObjectsV2` on the run-manifest prefix and
   `GetObject` a single `_run.json`; update error handling for S3-specific
   failure modes (throttling, missing key vs. Postgres "no rows")
3. Review `GET /api/v1/documents` filtering (`category`, `crawl_run_id`):
   `crawl_run_id` maps directly to an S3 key prefix; `category` requires
   either a manifest-side index or a documented full-prefix-scan cost —
   pick one and write down the tradeoff
4. Add API-level tests (httptest.Server) against a LocalStack-backed S3,
   including pagination/filter edge cases and S3 continuation tokens
5. Review `internal/metrics` counter/histogram definitions
   (`crawler_pages_fetched_total`, `crawler_fetch_duration_seconds`,
   `crawler_rate_limited_total`); add S3 write/throttle counters
   (`crawler_s3_put_total`, `crawler_s3_throttled_total`)
6. Verify `cmd/worker`'s `--metrics-address` serving is resilient to a
   port conflict (best-effort goroutine, doesn't take down the crawler)
7. Add a Grafana/Prometheus example query doc (pages/sec, error rate,
   429-by-host, S3 throttle rate) referencing the metrics in item 5
8. Review `internal/envflag` for correct flag-to-env-var name derivation
   (dashes to underscores, upper-casing) against every flag in `README.md`,
   including the new `--s3-*` flags
9. Add a health check endpoint on `cmd/api` if one doesn't already exist,
   including an S3 reachability check (e.g. `HeadBucket`), for use by
   `docker-compose.yml`/`k8s/` liveness probes
10. Keep `internal/api/openapi.yaml` in sync as other people's PRs land
    (update the `description` field that currently says "without a direct
    Postgres connection"); this is the last item so it can absorb
    late-breaking API changes

---

## Person 6 — Cross-Cutting: Activities, Testing & Docs

Owns: `internal/activities/` (the glue layer other packages plug into),
overall test coverage, `docs/`.
Ref: all of `docs/CRAWLER_ROADMAP.md`.

1. Review `internal/activities/activities.go`'s `ProcessPage` outcome
   classification (success/client_error/server_error/rate_limited/
   network_error/parse_error/skipped_robots/skipped_non_html) for
   completeness, and add an `s3_error` outcome for write failures distinct
   from parse/fetch failures
2. Review 429 handling (`parseRetryAfter`, `NextRetryDelay`, RFC 9110
   `Retry-After` parsing, the 5-minute cap) — unrelated to the storage
   swap, still worth a pass
3. Review `DiscoverSitemapURLs` and `CheckFreshness` activities for correct
   batching/error semantics against the new S3-backed `FreshnessChecker`
   (best-effort, never fails the crawl even if S3 is briefly unreachable)
4. Run `go test ./... -race` across the whole repo; fix any race found
5. Measure test coverage per package (`go test -cover ./...`) and add
   tests to the weakest-covered package
6. Update `docs/GETTING_STARTED.md` for the LocalStack-based local setup
   and the new `--storage=s3` flags, removing every remaining Postgres
   instruction
7. Update `docs/CRAWLER_ROADMAP.md`'s "Remaining gaps" section with
   anything found during this task-split's work, and add a dated note that
   item 5, 6, 7, 17, 18 (the Postgres-era items) describe a backend this
   repo no longer uses
8. Verify `docs/RESILIENCE.md`'s claims still hold after all 6 branches
   merge (re-run the kill-9 test on `main` against S3)
9. Write a `docs/TESTING.md` describing how to run unit vs. integration
   (LocalStack-backed) tests and when each is required
10. Final pass: read every other person's diff against `main` for
    cross-package inconsistencies, and grep the whole repo for leftover
    `postgres`/`sqlc`/`migrations` references before closing out the split

---

## Commit count summary

| Person | Area | Commits |
| --- | --- | --- |
| 1 | Build, ops & entry points | 10 |
| 2 | Discovery, frontier & workflow | 10 |
| 3 | Fetch, parse & dedup | 10 |
| 4 | S3 storage & data integrity | 10 |
| 5 | API & observability | 10 |
| 6 | Cross-cutting: activities, testing & docs | 10 |
| **Total** | | **60** |
