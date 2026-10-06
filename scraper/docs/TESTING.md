# Testing

Two tiers of tests exist in this repo. Run the first on every change; run
the second before calling a storage-touching change done.

## Unit tests (no external services)

```bash
make test          # go test ./...
go test ./... -race
go test -cover ./...
```

These use `httptest` servers and in-memory fakes only, so they need no
Docker, Temporal, database, or network access. They cover the fetcher
(politeness, DNS cache, HTTP/3 fallback), robots, sitemap, parser,
normalize, simhash, seeds, the activities layer (outcome classification,
`Retry-After` parsing, raw-HTML saving), and the workflow (via Temporal's
test environment).

Required: before every commit that touches Go code, together with
`go build ./...`, `go vet ./...` and `gofmt -l .` (`make vet` runs the last
two).

## Integration tests (real storage backend)

Mocked storage cannot catch bugs that only appear on a real write -- see
`docs/CRAWLER_ROADMAP.md` item 18, where a nil slice broke the first real
Postgres insert although every mocked test passed.

From the repository root:

```bash
docker compose --profile scraper up -d --build                                  # bring up the stack
docker compose exec airflow-scheduler airflow dags trigger scraper_crawl_schedule  # run a real crawl
docker compose logs -f scraper-worker                                           # confirm no write errors
docker compose --profile scraper down                                           # tear down
```

Required: before calling any change to `internal/storage/`, `internal/db/`,
or the write path in `internal/activities/` done.

The scraper has no migrations of its own: `database/` (Alembic) owns the
schema; sqlc generates the Go models from `../database/sql/scraper_schema.sql`,
which is exported from the pgs_db models (`make sqlc`). With the root stack's `postgres` up and migrated
(`docker compose up -d db-migrate db-roles` from the repository root),
`make test-db` runs the Postgres writer against the real schema as the
`pgs_scraper` role.

## Known coverage gaps

Measured with `go test -cover ./...`: `cmd/*`, `internal/api`,
`internal/envflag` and `internal/db` have no tests, and `internal/storage`
sits near 18%. New tests should go there first.
