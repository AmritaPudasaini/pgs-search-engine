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

From the repository root (the scraper runs in the root `docker-compose.yml`;
the Go project itself has only its `Dockerfile`):

```bash
docker compose --profile scraper up --build
```

This builds the images and runs in the foreground — leave it running and
watch the logs. First run takes a while to pull base images; after that,
rebuilds are fast (Docker layer caching). Add `-d` to run it in the background.

## 2. Start a crawl

Crawls are started by Airflow, not by hand: the `scraper_crawl_schedule` DAG
reads every website from the `domains` table every 30 minutes
(`SCRAPER_CRAWL_SCHEDULE`) and starts one whole-domain crawl for all of them
on Temporal. To crawl right away:

```bash
docker compose exec airflow-scheduler airflow dags trigger scraper_crawl_schedule
```

For an ad-hoc crawl of other URLs, run the client from the host against the
published Temporal port: `go run ./cmd/scraper --seeds=https://example.com`.

## 3. Watch it happen

- **Temporal Web UI**: http://localhost:8233 — see the workflow, its
  activities, retries, and (if you kill a worker mid-crawl) how it resumes.
- **Crawled pages**: the worker uploads each page's complete HTML and metadata
  to the `crawled-pages` bucket. Browse it at http://localhost:8081 (open
  `crawled-pages`, then `html/<host>/`), or use the documents API + Swagger UI
  at http://localhost:8082/docs.
- **ETL hand-off**: when a website's crawl finishes, the worker publishes one
  `site_crawl_completed` event for it to the Kafka topic `scraped_files_topic`
  (nothing per page). It names the site's documents prefix,
  `<crawl_run_id>/<host>/`; the Airflow DAG `etl_ingestion_pipeline` picks it
  up and runs the PySpark pipeline for that site.

## 4. Scale it up

More worker replicas, same task queue, zero coordination code:

```bash
docker compose --profile scraper up -d --scale scraper-worker=5
```

Each replica independently polls Temporal and writes to the same bucket.
To pin each host to one worker instead, see `docs/SCALING.md`.

## 5. Tear down

```bash
docker compose --profile scraper down
```

Stops and removes the stack's containers. Everything under the repository's
`./data/` is kept; LocalStack's S3 objects do not survive a restart.

## Troubleshooting

- **`docker compose build` fails on `go mod download` with a Go version
  error**: `go.mod`'s `go` directive and the `GO_VERSION` build argument in
  `scraper/Dockerfile` must be kept in sync — if you bumped one, bump the other.
- **The worker waits after `docker compose up`**: expected. It starts only once
  Temporal's health check passes (its `default` namespace exists) and S3 is up,
  which takes ~30s on a cold start.
- **Temporal container exits immediately**: check
  `docker compose logs temporal db-roles` — a common cause is an invalid
  `DB=` value (must be `postgres12` for this image, not `postgresql`).
- **Port conflicts**: every host port is set in the root `.env`
  (`TEMPORAL_UI_PORT`, `S3_PORT`, `S3_BROWSER_PORT`, `SCRAPER_API_PORT`, ...).
- **Anything else**: paste the exact terminal output; a fresh failure usually
  points at something environment-specific (Docker Hub connectivity, port
  conflicts, stale containers from a previous run — try
  `docker compose --profile scraper down` first).

## No-Docker option

Prefer running plain Go binaries against a local Temporal dev server
instead of containers? See the main [README](../README.md)'s "Quick start
(running locally, no Docker)" section.
