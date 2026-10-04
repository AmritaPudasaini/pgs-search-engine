# Getting started

The fastest path to a running crawl: one command brings up the project stack
with the scraper (Temporal, Temporal Web UI, LocalStack S3, headless Chrome, a
worker and the documents API). It all runs from the repository-root
`docker-compose.yml` (profile `scraper`); the `make` targets below wrap it.

## Prerequisites

- Docker Desktop installed and running (on Windows, use it from WSL with
  *Settings → Resources → WSL Integration* enabled). Check with:
  ```bash
  docker info >/dev/null 2>&1 && echo "docker running" || echo "docker NOT running — start Docker Desktop first"
  ```
- A `.env` in the repository root: `cp .env.example .env` (once).

## 1. Start everything

```bash
cd scraper
make run
```

This builds the images and runs in the foreground — leave it running and
watch the logs. First run takes a while to pull base images; after that,
rebuilds are fast (Docker layer caching). If you'd rather it run in the
background, use `make up` instead.

## 2. Start a crawl

In a second terminal:

```bash
make crawl SEEDS=https://example.com
```

or, for a broader multi-category crawl seeded from `configs/seeds.example.txt`:

```bash
make crawl SEEDS_FILE=configs/seeds.example.txt
```

(`make crawl` runs `docker compose run --rm scraper-cli ...` from the root
compose file.)

## 3. Watch it happen

- **Temporal Web UI**: http://localhost:8233 — see the workflow, its
  activities, retries, and (if you kill a worker mid-crawl) how it resumes.
- **Crawled pages**: the worker uploads each page's complete HTML and metadata
  to the `crawled-pages` bucket. Browse it at http://localhost:8081 (open
  `crawled-pages`, then `html/<host>/`), or use the documents API + Swagger UI
  at http://localhost:8082/docs.
- **ETL hand-off**: the worker also publishes each document to the Kafka topic
  `crawled-documents`, which the stack's `etl-consumer` reads
  (`docker compose logs -f etl-consumer` from the repository root).

## 4. Scale it up

More worker replicas, same task queue, zero coordination code:

```bash
make scale SCALE=5
```

Each replica independently polls Temporal and writes to the same bucket.
To pin each host to one worker instead, see `docs/SCALING.md`.

## 5. Tear down

```bash
make down
```

Stops and removes the stack's containers. Volumes are kept, because the stack is
shared with the other services; LocalStack itself keeps no data across restarts.

## Troubleshooting

- **`docker compose build` fails on `go mod download` with a Go version
  error**: `go.mod`'s `go` directive and the `GO_VERSION` build argument in
  `scraper/Dockerfile` must be kept in sync — if you bumped one, bump the other.
- **The worker waits after `make run`**: expected. It starts only once
  Temporal's health check passes (its `default` namespace exists) and S3 is up,
  which takes ~30s on a cold start.
- **Temporal container exits immediately**: check
  `docker compose logs temporal temporal-db` — a common cause is an invalid
  `DB=` value (must be `postgres12` for this image, not `postgresql`).
- **Port conflicts**: every host port is set in the root `.env`
  (`TEMPORAL_UI_PORT`, `S3_PORT`, `S3_BROWSER_PORT`, `SCRAPER_API_PORT`, ...).
- **Anything else**: paste the exact terminal output; a fresh failure usually
  points at something environment-specific (Docker Hub connectivity, port
  conflicts, stale containers from a previous run — try `make down` first).

## No-Docker option

Prefer running plain Go binaries against a local Temporal dev server
instead of containers? See the main [README](../README.md)'s "Quick start
(running locally, no Docker)" section.
