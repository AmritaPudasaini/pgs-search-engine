# ETL Implementation And Workflow

## Current Scope

The ETL section is self-contained for development. It does not depend on the
scraper, real MinIO, or PostgreSQL application schemas. Kafka signals are
produced manually, files are read from the local ETL file store, transformed
records are written to JSONL, and an isolated OpenSearch service can index that
output.

## Implemented Workflow

```text
Kafka file-ready signal
  -> Airflow DAG: etl_ingestion_pipeline
  -> local file store: ETL/airflow/data/local_dfs_store/
  -> rule-based file intake check
  -> Spark-facing transformation logic
  -> JSONL output: ETL/airflow/data/processed/transformed_documents.jsonl
  -> OpenSearch ingestion: ETL/OpenSearch/opensearch/index_documents.py
```

## Docker Services

- `kafka`: local Kafka broker exposed on `localhost:9092`.
- `clamav`: ClamAV daemon used by the intake scanner (`clamav:3310`).
- `airflow-db`: Airflow metadata database.
- `redis`: Celery broker for Airflow workers.
- `airflow-webserver`: Airflow UI at `http://localhost:8080`.
- `airflow-scheduler`: schedules DAG work.
- `airflow-worker`: executes DAG tasks.
- `ingestion-signal-publisher`: one-shot utility that publishes a file-ready
  signal to Kafka.

All of them are defined in the repository-root `docker-compose.yml` (one image,
`ETL/Dockerfile`). Start everything from the repository root:

```bash
docker compose up -d --build
```

Publish a file-ready signal:

```bash
docker compose run --rm ingestion-signal-publisher
```

Then trigger `etl_ingestion_pipeline` in Airflow.

## Airflow DAGs

- `etl_ingestion_pipeline`: main ETL flow.
- `airflow_healthcheck`: confirms Airflow scheduling and worker execution.
- `document_extraction_check`: validates simple local HTML/TXT extraction
  through Airflow workers.

Main DAG tasks:

```text
poll_kafka_signal -> transform_document -> persist_transformed_document
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
`ETL/OpenSearch/opensearch/create_index.py` and covers the actual transformed
fields, including text, keyword, numeric, boolean, and object fields.

Start the OpenSearch service and index the output with the Windows commands in
`ETL/OpenSearch/OpenSearch.md`.

## File Intake Checks

Implemented in `ETL/spark/security_scanner.py`:

- Extension classification.
- Suspicious extension rejection.
- Unexpected extension rejection.
- Maximum size check.
- Filename length check.
- SHA256 audit hash.

This is a rule-based intake guard only. It is not a replacement for ClamAV.

## Verification Commands

From the repository root:

```bash
python -B ETL/kafka/test_consumer.py
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
docker compose run --rm ingestion-signal-publisher
docker compose exec -T airflow-scheduler airflow dags list
docker compose exec -T airflow-scheduler airflow dags list-runs -d etl_ingestion_pipeline
```

## Remaining Work

- Replace the local file store with MinIO once available.
- Add real ClamAV malware scanning.
- Add the final PostgreSQL write path.
- Add embeddings only if the existing transformation produces them.
- Replace seed geo rules with an official Nepal administrative gazetteer.
- Move from development orchestration to production Spark/Kafka streaming once
  the scraper contract and storage schemas are finalized.
