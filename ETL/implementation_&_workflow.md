# ETL Implementation And Workflow

## Current Scope

The ETL starts where the scraper stops: when the crawl of one website has
finished, the scraper publishes one `site_crawl_completed` event to Kafka, and
Airflow runs the PySpark pipeline for that whole site. Pages are read from the
scraper's S3 bucket (LocalStack locally), transformed records are written to
JSONL (not yet PostgreSQL), and an OpenSearch service can index that output.

## Implemented Workflow

```text
Airflow DAG scraper_crawl_schedule (every 30 min)
  -> Temporal CrawlDomainsWorkflow over every website in `domains` (Go scraper worker)
  -> Kafka scraped_files_topic: one site_crawl_completed event per crawled website
  -> Airflow DAG etl_ingestion_pipeline: once 100 events are waiting
  -> Temporal EtlBatchWorkflow (etl-worker = Spark driver), one activity per site
  -> PySpark pipeline ETL/spark/site_pipeline.py on the Spark cluster, in order:
       the site's pages from S3 (<key_prefix>/<crawl_run_id>/<host>/)
       -> rule-based intake check + ClamAV scan
       -> text extraction and transformation
       -> dedup, LaBSE embedding
  -> JSONL output: ETL/airflow/data/processed/transformed_documents.jsonl
  -> OpenSearch ingestion: ETL/open_search/opensearch/index_documents.py
```

## Docker Services

- `kafka`: local Kafka broker exposed on `localhost:9092`.
- `clamav`: ClamAV daemon used by the intake scanner (`clamav:3310`).
- `db-roles`: creates Airflow's and Temporal's databases and roles in the
  shared `postgres` server.
- `airflow-webserver`: Airflow UI at `http://localhost:8080`.
- `airflow-scheduler`: schedules the DAGs and runs their tasks (LocalExecutor).
- `temporal`, `temporal-ui`: workflow engine (UI at
  `http://localhost:8233`).
- `etl-worker`: Temporal worker for `EtlBatchWorkflow`, the Spark driver.
- `spark-master`, `spark-worker`: Spark standalone cluster (UI at
  `http://localhost:8090`).

All of them are defined in the repository-root `docker-compose.yml` (one image,
`ETL/Dockerfile`). Start everything from the repository root:

```bash
docker compose --profile scraper up -d --build
docker compose exec airflow-scheduler airflow dags trigger scraper_crawl_schedule   # crawl now
```

## Airflow DAGs

- `scraper_crawl_schedule`: starts the crawl of every website every 30 minutes.
- `etl_ingestion_pipeline`: main ETL flow, in batches of 100 crawled sites.
- `airflow_healthcheck`: confirms Airflow scheduling and task execution.
- `document_extraction_check`: validates simple local HTML/TXT extraction.

Main DAG tasks:

```text
poll_batch -> process_batch (EtlBatchWorkflow on Temporal) -> commit_offsets
```

## Transformation Features

Implemented in `ETL/spark/transform.py`:

- HTML text extraction.
- PDF text extraction through `pypdf`.
- Language detection for English, Nepali, mixed, and unknown text.
- SHA256 exact content fingerprinting.
- SimHash fuzzy fingerprinting.
- Seed geo-tagging rules for Kathmandu, Pokhara, and Janakpur.
- Duplicate marking using exact SHA256 first, then SimHash distance.

## OpenSearch Step 6

The OpenSearch integration reads the existing transformed JSONL; it
does not create another transformation pipeline. `document_id` from
`ETL/spark/transform.py` is used as the OpenSearch `_id`, making repeated
ingestion idempotent. The index mapping is defined in
`ETL/open_search/opensearch/create_index.py` and covers the actual transformed
fields, including text, keyword, numeric, boolean, and object fields.

Start the OpenSearch service and index the output with the Windows commands in
`ETL/open_search/OpenSearch.md`.

## File Intake Checks

Implemented in `ETL/spark/security_scanner.py`:

- Extension classification.
- Suspicious extension rejection.
- Unexpected extension rejection.
- Maximum size check.
- Filename length check.
- SHA256 audit hash.

These rule checks run together with the ClamAV scan (`inspect_bytes`), as the
first step of the per-site pipeline.

## Verification Commands

From the repository root:

```bash
python -B ETL/spark/test_site_pipeline.py
python -B ETL/spark/test_security_scanner.py
python -B ETL/spark/test_transform.py
python -B ETL/spark/test_spark.py
```

From the repository root:

```bash
docker compose config --quiet
```

When the stack is running:

```bash
docker compose ps
docker compose exec -T airflow-scheduler airflow dags list
docker compose exec -T airflow-scheduler airflow dags list-runs -d etl_ingestion_pipeline
```

## Remaining Work

- Add the final PostgreSQL write path.
- Add embeddings only if the existing transformation produces them.
- Replace seed geo rules with an official Nepal administrative gazetteer.
- Move from development orchestration to production Spark/Kafka streaming once
  the scraper contract and storage schemas are finalized.
