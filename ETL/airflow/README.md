# Airflow Docker Setup (Phase 1 - Dummy Test)

## What this is
A local Airflow environment used to prove the orchestration layer works
before it's connected to the real ETL pipeline (Spark, Kafka, real data).
Runs using CeleryExecutor, so tasks are handled by a separate worker
container via a Redis queue - matching how a real, scaled-up setup
would work, instead of running everything on one process.

## What's inside
- The containers are defined in the repository-root `docker-compose.yml`
  (image: `ETL/Dockerfile`): airflow-db (Airflow's internal PostgreSQL),
  redis (task queue broker), airflow-init (one-time setup),
  airflow-webserver (the dashboard), airflow-scheduler (decides when tasks
  run), airflow-worker (actually executes tasks).
- `dags/dummy_test_dag.py` - original test DAG, two tasks that just
  print text, proving basic scheduling works.
- `dags/dummy_file_parser_dag.py` - reads real files (`data/sample.html`,
  `data/sample.txt`), strips HTML tags, prints extracted text and word
  counts. Simulates the real "text extraction" step Spark will do later.
- `data/sample.html`, `data/sample.txt` - dummy input files used only
  for testing. Not real project data.
- The repository-root `.env` (copied from `.env.example`) sets AIRFLOW_UID
  (your `id -u` on Linux/WSL, for file permissions in `logs/`), the admin
  login and the Airflow secrets.
- `logs/`, `plugins/`, `config/` - empty folders Airflow writes into at
  runtime. Don't add anything here manually.

## Prerequisites
- Docker Desktop installed and running.
- At least 4 GB RAM / 4 CPUs allocated to Docker (Docker Desktop >
  Settings > Resources).
- Port 8080 free on your machine.

## First-time setup
From the repository root (not this folder):

    cp .env.example .env
    docker compose up -d --build

First run downloads several images (Postgres, Redis, Airflow) - can
take a few minutes. `airflow-init` creates the database tables and the
admin login, then exits (this is expected, not an error).

## Check it's running
    docker compose ps

You should see `airflow-db`, `redis`, `airflow-webserver`,
`airflow-scheduler`, `airflow-worker` "running" (they become "healthy"
after ~30-60s), plus `airflow-init` "exited (0)" (correct - it's a
one-time job, not meant to keep running), alongside the rest of the stack.

## Verify it works
1. Open http://localhost:8080
2. Log in with `AIRFLOW_ADMIN_USERNAME` / `AIRFLOW_ADMIN_PASSWORD`
   from `.env` (default `airflow` / `airflow`)
3. Find `dummy_file_parser_dag` in the list, toggle it on (un-pause)
4. Click the play button to trigger it manually
5. Confirm both `extract_html` and `extract_txt` tasks turn green
6. Click each task > Logs, confirm you see the extracted text and a
   word count printed - not just a green checkmark

(`dummy_test_dag` still works the same way too, if you want to re-check
the original basic test.)

## Stop everything
    docker compose down

## Stop AND wipe all data (rarely needed, but required after changing
## the executor type or if things get into a broken state)
    docker compose down -v      # wipes EVERY volume of the stack, not just Airflow's

To reset only Airflow's database:

    docker compose rm -sf airflow-db && docker volume rm pgs-search-engine_airflow-db-data

## What this does NOT do yet
The containers can reach Kafka (`kafka:29092`), the project's PostgreSQL
(`DATABASE_URL`, role `pgs_etl`) and OpenSearch (`opensearch:9200`), but
no DAG writes to PostgreSQL/OpenSearch yet. Real scheduled jobs (nightly
deduplication, index optimization, cleanup) get added once Spark/Kafka
are ready and we know how to trigger their real jobs.

## Common issues
- **Port 8080 in use**: set `AIRFLOW_PORT=8081` in the root `.env`, then
  use that port instead.
- **airflow-worker not showing as running**: check
  `docker compose logs airflow-worker` for the actual error - usually a
  typo in the Redis connection string or Redis not being healthy yet.
- **DAG doesn't show up**: wait 30-60 seconds and refresh, the scheduler
  scans the dags folder periodically, not instantly.
- **Switched executors and things act weird**: reset Airflow's database
  (above), then `docker compose up -d` again.
- **Permission denied on `logs/`**: `AIRFLOW_UID` in `.env` must match
  `id -u`.