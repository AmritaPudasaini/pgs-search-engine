# search-engine-scraper — 6-Person Task Split

This document divides work on this repo — a Go web crawler orchestrated by
Temporal, writing to NDJSON or Postgres and served through a small read API
— across **6 people**, with **10 commits each** (60 commits total). Each
person owns a clear slice of the codebase so work doesn't collide. Copy your
section, work through the checklist top to bottom, and commit once per item
(squash later if you prefer a cleaner history).

This repo's scope is **scraping only** — indexing, ranking/search, and UI
are out of scope (see `docs/CRAWLER_ROADMAP.md`, "Explicitly out of scope").
Every item below stays inside that boundary and inside packages that
actually exist in this repo today.

Reference docs before starting:
- `README.md` — project layout, how it works, flags, database, scaling
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
   Go code; run `make run` + `make crawl SEEDS=...` against the real Docker
   stack before calling a Postgres-touching change done (see
   `docs/CRAWLER_ROADMAP.md` item 18 for why mocked tests alone aren't
   enough there).

---

## Person 1 — Build, Ops & Entry Points

Owns: `cmd/api/`, `cmd/scraper/`, `cmd/worker/`, `Dockerfile.*`,
`docker-compose.yml`, `k8s/`, `Makefile`.

1. [x] Audit `cmd/scraper/main.go` and `cmd/worker/main.go` flag parsing against
   the flag tables in `README.md`; fix any drift between the two
2. [x] Review `Dockerfile.worker` / `Dockerfile.scraper` / `Dockerfile.api`
   multi-stage builds for image size / layer caching improvements
3. [x] Review `docker-compose.yml` service dependencies (Postgres, Temporal,
   worker, api) and healthchecks/wait conditions
4. [x] Review `k8s/` manifests (Deployment, HPA, StatefulSet, Jobs) for
   correctness against current `cmd/worker` flags/env vars
5. [x] Verify `make scale SCALE=N` and `make down` behave as documented in
   `README.md`
6. [x] Add/verify a CI workflow: `go build ./...`, `go vet ./...`, `go test ./...`
7. [x] Add/verify `golangci-lint` (or equivalent) config and wire it into `make`
8. [x] Confirm `cmd/api/main.go` boots the API server independently of the
   worker/scraper (no accidental coupling)
9. [x] Cross-check `Makefile` targets (migrations, sqlc, local dev DB) actually
   match what's described in `docs/GETTING_STARTED.md`
10. [ ] Review and merge Person 2–6 branches; resolve structural conflicts —
    **blocked**: none of those branches exist yet in this repo. Do this
    once Person 2–6 have pushed their own branches; it's a merge/review
    step, not something to do standalone ahead of their work.

Items 1–9 landed as individual commits on `person1/search-engine-scaffold`
(one per checklist item, real fixes/additions each time — see that
branch's log for specifics: flag-table drift, Dockerfile cache mounts,
a k8s ConfigMap that was silently 9 migrations behind, `make help`
completeness, a CI workflow + golangci-lint wired in and verified
0 issues, a `cmd/api` independence guard, and two doc/path drift fixes).

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
7. Verify the run-tracking (`crawl_runs`) status transitions
   (`running`/`completed`/`failed`) are accurate for every exit path
8. Verify `docs/RESILIENCE.md`'s kill-9-mid-crawl claim still holds; re-run
   the test and update the doc if behavior changed
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
   resolution against tricky inputs (fragments, trailing slashes, ports)
7. Review `internal/simhash`'s near-duplicate threshold
   (`nearDupHammingThreshold`) and `minTextLenForNearDupCheck` guard
8. Add fixtures/tests for any HTML edge case not covered
   (malformed JSON-LD, nested `geo` under `Place`, ISO-8859-1 pages)
9. Benchmark `parser.Parse` on a large real page and note any hotspot
10. Document known parser limitations (e.g. div-level link-density gap)
    that aren't already captured in `docs/CRAWLER_ROADMAP.md`

---

## Person 4 — Storage, Schema & Data Integrity

Owns: `internal/storage/`, `internal/db/`, `internal/model/`,
`migrations/`.
Ref: `README.md` "Database", `docs/CRAWLER_ROADMAP.md` items 5–7, 17, 18.

1. Review `migrations/` (0001–0009) for correctness and reversibility
   (up/down pairs)
2. Confirm `sqlc generate` output in `internal/db/` matches
   `internal/db/queries.sql` (no stale generated code)
3. Review `internal/storage/postgres.go`'s `UpsertDocument` — confirm the
   `nonNilStrings` nil-slice-to-empty-array coalescing still covers every
   `TEXT[]` column
4. Review the `UNIQUE (normalized_url)` constraint and upsert `SET` clause
   for completeness (every updatable field actually gets updated)
5. Review `storage.RunRecorder` / `NoopRunRecorder` and
   `storage.FreshnessChecker` / `NoopFreshnessChecker` interface pairs for
   parity between the Postgres and NDJSON backends
6. Review `internal/model.Document` field-by-field against
   `internal/api/openapi.yaml` for drift
7. Add a `postgres_test.go` case for any write path not yet covered
   (nil slices, empty JSON-LD, duplicate canonical URL collapse)
8. Verify NDJSON writer output matches the documented `model.Document`
   shape in `README.md`
9. Load-test `ListFreshDocumentURLs` (`CheckFreshness` batching) against a
   large `documents` table
10. Document the Postgres schema (table + key columns) in a short
    `docs/SCHEMA.md` if one doesn't already exist

---

## Person 5 — API & Observability

Owns: `internal/api/`, `internal/metrics/`, `internal/envflag/`.
Ref: `README.md` §API, `docs/CRAWLER_ROADMAP.md` items 5, 6, 7, 16.

1. Review `internal/api/server.go` route handlers against
   `internal/api/openapi.yaml`; fix any mismatch
2. Review `GET /api/v1/crawl-runs` and `GET /api/v1/crawl-runs/{id}`
   response shapes and error handling
3. Review `GET /api/v1/documents` filtering (`category`, `crawl_run_id`)
   including the no-op-when-omitted behavior
4. Add API-level tests (httptest.Server) for pagination/filter edge cases
5. Review `internal/metrics` counter/histogram definitions
   (`crawler_pages_fetched_total`, `crawler_fetch_duration_seconds`,
   `crawler_rate_limited_total`) for label cardinality issues
6. Verify `cmd/worker`'s `--metrics-address` serving is resilient to a
   port conflict (best-effort goroutine, doesn't take down the crawler)
7. Add a Grafana/Prometheus example query doc (pages/sec, error rate,
   429-by-host) referencing the metrics in item 5
8. Review `internal/envflag` for correct flag-to-env-var name derivation
   (dashes to underscores, upper-casing) against every flag in `README.md`
9. Add a health check endpoint on `cmd/api` if one doesn't already exist,
   for use by `docker-compose.yml`/`k8s/` liveness probes
10. Keep `internal/api/openapi.yaml` in sync as other people's PRs land;
    this is the last item so it can absorb late-breaking API changes

---

## Person 6 — Cross-Cutting: Activities, Testing & Docs

Owns: `internal/activities/` (the glue layer other packages plug into),
overall test coverage, `docs/`.
Ref: all of `docs/CRAWLER_ROADMAP.md`.

1. Review `internal/activities/activities.go`'s `ProcessPage` outcome
   classification (success/client_error/server_error/rate_limited/
   network_error/parse_error/skipped_robots/skipped_non_html) for
   completeness
2. Review 429 handling (`parseRetryAfter`, `NextRetryDelay`, RFC 9110
   `Retry-After` parsing, the 5-minute cap)
3. Review `DiscoverSitemapURLs` and `CheckFreshness` activities for
   correct batching/error semantics (best-effort, never fails the crawl)
4. Run `go test ./... -race` across the whole repo; fix any race found
5. Measure test coverage per package (`go test -cover ./...`) and add
   tests to the weakest-covered package
6. Update `docs/GETTING_STARTED.md` if any flag/command from other
   people's PRs changed the fastest-path instructions
7. Update `docs/CRAWLER_ROADMAP.md`'s "Remaining gaps" section with
   anything found during this task-split's work
8. Verify `docs/RESILIENCE.md`'s claims still hold after all 6 branches
   merge (re-run the kill-9 test on `main`)
9. Write a `docs/TESTING.md` describing how to run unit vs. integration
   (Docker-stack) tests and when each is required
10. Final pass: read every other person's diff against `main` for
    cross-package inconsistencies before closing out the split

---

## Commit count summary

| Person | Area | Commits |
| --- | --- | --- |
| 1 | Build, ops & entry points | 10 |
| 2 | Discovery, frontier & workflow | 10 |
| 3 | Fetch, parse & dedup | 10 |
| 4 | Storage, schema & data integrity | 10 |
| 5 | API & observability | 10 |
| 6 | Cross-cutting: activities, testing & docs | 10 |
| **Total** | | **60** |
