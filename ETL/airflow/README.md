# Airflow In ETL

Airflow schedules the crawl and the ETL; the work itself runs on Temporal and
Spark. It runs from the repository-root `docker-compose.yml` (image:
`ETL/Dockerfile`) with the LocalExecutor, so there is no Celery worker and no
Redis: `airflow-scheduler` decides when tasks run and runs them itself (they
only read Kafka or the `domains` table and start/await Temporal workflows),
and `airflow-webserver` is the UI. Airflow's metadata is the `airflow` database
in the shared `postgres` server, created by `db-roles`; on every start the
scheduler migrates it and creates the admin login (both idempotent) before
scheduling, and the webserver waits until the scheduler is healthy.

From the repository root:

```bash
cp .env.example .env      # once; AIRFLOW_UID must be your `id -u`
docker compose up -d --build
```

Airflow UI: http://localhost:8080, login `AIRFLOW_ADMIN_USERNAME` /
`AIRFLOW_ADMIN_PASSWORD` from `.env` (default `airflow` / `airflow`). The
webserver is "healthy" in `docker compose ps` after ~30-60s.

## Main DAG

`etl_ingestion_pipeline`

Tasks:

```text
poll_batch -> process_batch -> commit_offsets
```

Every 2 minutes the DAG checks Kafka topic `scraped_files_topic` (one
`site_crawl_completed` event per website whose crawl finished). Once
`ETL_BATCH_SIZE` (100) events are waiting, or the oldest has waited
`ETL_BATCH_MAX_WAIT_MINUTES` (60), it starts one `EtlBatchWorkflow` on Temporal
for the batch, waits for it, and then commits the events. The `etl-worker`
runs the workflow as the Spark driver on the Spark cluster. See
`../ETL_README.md` for the flow.

`scraper_crawl_schedule`

Every 30 minutes (`SCRAPER_CRAWL_SCHEDULE`) it reads the websites from the
`domains` table (PAUSED ones are left out) and starts one
`CrawlDomainsWorkflow` for all of them on Temporal, which the Go scraper worker
runs. The workflow ID is fixed, so a tick while the last crawl is still running
is skipped.

## Sample Run

With the stack up (`docker compose --profile scraper up -d`), from the
repository root:

```bash
docker compose exec airflow-scheduler airflow dags trigger scraper_crawl_schedule
```

Each finished website sends its event; `etl_ingestion_pipeline` runs the batch
when it is full (set `ETL_BATCH_SIZE` lower in `.env` to try it with a few
sites). The `process_batch` task log ends with each site's summary; the
Temporal UI (http://localhost:8233) shows the workflows.

## Notes

The healthcheck and extraction-check DAGs are support workflows; the ingestion
pipeline is the main ETL workflow.

- `dags/`, `plugins/`, `config/`, `data/` and `../spark` are bind-mounted
  into the Airflow containers, so edits apply without a rebuild; new DAGs
  appear within 30-60 seconds and start unpaused.
- Task logs are in `data/airflow-logs/` at the repository root (the
  `data-airflow-logs` volume), owned by `AIRFLOW_UID`: set it in `.env` to your
  `id -u` so you can read them.
- Port 8080 taken: set `AIRFLOW_PORT` in `.env`.
- A task fails with a ClamAV connection error: on its first start `clamav`
  downloads its signatures (a few minutes); wait until `docker compose ps`
  shows it healthy.
- Reset only Airflow's database:
  `docker compose exec postgres dropdb -U pgs --force airflow`, then
  `docker compose up -d` (`db-roles` recreates it). (The stack's state is in `./data/` at the
  repository root; deleting `data/postgres` resets every database.)
