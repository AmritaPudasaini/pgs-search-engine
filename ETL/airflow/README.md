# Airflow In ETL

Airflow orchestrates the ETL development workflow. It runs from the
repository-root `docker-compose.yml` (image: `ETL/Dockerfile`), with
CeleryExecutor: `airflow-scheduler` decides when tasks run, `airflow-worker`
executes them via the `redis` queue, `airflow-webserver` is the UI, and
`airflow-db` holds Airflow's metadata. `airflow-init` migrates that database
and creates the admin login, then exits (exit code 0 is expected).

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
poll_kafka_signal -> transform_document -> persist_transformed_document
```

The DAG consumes one manual signal from Kafka topic `scraped_files_topic`, reads
the matching file from `/opt/airflow/data/local_dfs_store`, runs the shared
transform logic mounted from `ETL/spark` (including the ClamAV scan, at
`clamav:3310`), and appends the transformed output to
`/opt/airflow/data/processed/transformed_documents.jsonl`.

## Sample Run

With the stack up, from the repository root:

```bash
docker compose run --rm ingestion-signal-publisher
```

Trigger `etl_ingestion_pipeline` in the Airflow UI and inspect the
`persist_transformed_document` task log for the transformed record.

## Notes

The healthcheck and extraction-check DAGs are support workflows; the ingestion
pipeline is the main ETL workflow.

- `dags/`, `logs/`, `plugins/`, `config/`, `data/` and `../spark` are
  bind-mounted into the Airflow containers, so edits apply without a rebuild;
  new DAGs appear within 30-60 seconds and start unpaused.
- `logs/` must be writable by the containers: set `AIRFLOW_UID` in `.env` to
  your `id -u` (a "Permission denied" on `logs/` means it doesn't match).
- Port 8080 taken: set `AIRFLOW_PORT` in `.env`.
- A task fails with a ClamAV connection error: on its first start `clamav`
  downloads its signatures (a few minutes); wait until `docker compose ps`
  shows it healthy.
- Reset only Airflow's database (e.g. after changing the executor):
  `docker compose rm -sf airflow-db && docker volume rm pgs-search-engine_airflow-db-data`,
  then `docker compose up -d`. (`docker compose down -v` wipes every volume of
  the stack.)
