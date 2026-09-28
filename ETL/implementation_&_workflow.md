# ETL Implementation And Workflow

## Current Scope

The ETL section is self-contained for development. It does not depend on the
scraper, real MinIO, PostgreSQL application schemas, or OpenSearch yet. Kafka
signals are produced manually, files are read from the local ETL file store, and
transformed records are written to JSONL output for inspection.

## Implemented Workflow

```text
Kafka file-ready signal
  -> Airflow DAG: etl_ingestion_pipeline
  -> local file store: ETL/airflow/data/local_dfs_store/
  -> rule-based file intake check
  -> Spark-facing transformation logic
  -> JSONL output: ETL/airflow/data/processed/transformed_documents.jsonl
```

## Docker Services

- `kafka`: local Kafka broker exposed on `localhost:9092`.
- `postgres`: Airflow metadata database.
- `redis`: Celery broker for Airflow workers.
- `airflow-webserver`: Airflow UI at `http://localhost:8080`.
- `airflow-scheduler`: schedules DAG work.
- `airflow-worker`: executes DAG tasks.
- `ingestion-signal-publisher`: one-shot utility that publishes a file-ready
  signal to Kafka.

Start everything from `ETL/`:

```bash
docker compose up --build
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

From `ETL/`:

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
- Add OpenSearch indexing and embeddings.
- Replace seed geo rules with an official Nepal administrative gazetteer.
- Move from development orchestration to production Spark/Kafka streaming once
  the scraper contract and storage schemas are finalized.
