# Getting started

The fastest path to a running crawl: one command brings up the whole stack
(Postgres, Temporal, Temporal Web UI, one worker).

## Prerequisites

- Docker Desktop installed and running. Check with:
  ```bash
  docker info >/dev/null 2>&1 && echo "docker running" || echo "docker NOT running — start Docker Desktop first"
  ```

## 1. Start everything

```bash
cd scraper
make run
```

This builds the worker/scraper images and runs in the foreground — leave
it running and watch the logs. First run takes a minute or two to pull
base images; after that, rebuilds are fast (Docker layer caching). If
you'd rather it run in the background, use `make up` instead.

## 2. Start a crawl

In a second terminal:

```bash
make crawl SEEDS=https://example.com
```

or, for a broader multi-category crawl seeded from `configs/seeds.example.txt`:

```bash
make crawl SEEDS_FILE=configs/seeds.example.txt
```

## 3. Watch it happen

- **Temporal Web UI**: http://localhost:8233 — see the workflow, its
  activities, retries, and (if you kill a worker mid-crawl) how it resumes.
- **Query the results directly in Postgres:**
  ```bash
  docker compose exec postgres psql -U temporal -d scraper -c \
    "SELECT url, category, status_code, title FROM documents;"
  ```

## 4. Scale it up

More worker replicas, same task queue, zero coordination code:

```bash
make scale SCALE=5
```

Each replica independently polls Temporal and writes to the same Postgres
table — the `normalized_url` unique constraint means
concurrent replicas can't produce duplicate rows (see `docs/RESILIENCE.md`
and the main README's "Database" section).

## 5. Tear down

```bash
make down
```

Stops everything and wipes the Postgres volume.

## Troubleshooting

- **`docker compose build` fails on `go mod download` with a Go version
  error**: `go.mod`'s `go` directive and the `golang:*-alpine` tag in
  `Dockerfile.worker`/`Dockerfile.scraper` must be kept in sync — if you
  bumped one, bump the other.
- **Worker container restarts once or twice on a cold `make run`**: expected.
  `depends_on: temporal: condition: service_started` only waits for
  Temporal's container to start, not for its gRPC server to finish schema
  setup. The worker's `restart: on-failure` policy self-heals this within
  a few seconds — no action needed unless it keeps restarting past ~30s.
- **Temporal container exits immediately**: check `docker compose logs
  temporal` — a common cause is an invalid `DB=` value in
  `docker-compose.yml` (must be `postgres12` for this image, not
  `postgresql`).
- **Anything else**: paste the exact terminal output; don't guess and
  retry blindly — these container images and this compose file were
  verified working end-to-end (see the main README's Docker section), so
  a fresh failure usually points at something environment-specific (Docker
  Hub connectivity, port conflicts, stale volumes from a previous run —
  try `make down` first).

## No-Docker option

Prefer running plain Go binaries against a local Temporal dev server
instead of containers? See the main [README](../README.md)'s "Quick start
(running locally, no Docker)" section.
