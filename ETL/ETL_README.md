# ETL

ETL for a Nepali/English search engine. This folder is self-contained for
development: it uses local sample files instead of the scraper, JSONL as the
intermediate output instead of PostgreSQL, an optional local OpenSearch index,
and Kafka signals to simulate the scraper handoff.

## Current Workflow

```text
manual Kafka signal -> local file store -> transform -> JSONL output
```

The implementation follows the text architecture direction: transformation
logic lives in Spark-facing code, Airflow is the orchestrator for this
runnable phase, and the isolated OpenSearch step consumes the resulting JSONL.

## Run The Stack

From `ETL/`:

```bash
docker compose up --build
```

Airflow UI: http://localhost:8080

Login:

```text
airflow / airflow
```

To send a sample file-ready signal:

```bash
docker compose run --rm ingestion-signal-publisher
```

Then trigger the `etl_ingestion_pipeline` DAG in Airflow. The DAG reads
`airflow/data/local_dfs_store/sample.html`, transforms it, marks duplicate
status against prior local output, and appends the transformed document to:

```text
ETL/airflow/data/processed/transformed_documents.jsonl
```

To index those transformed records after the DAG succeeds:

```bash
docker compose up -d opensearch
docker compose run --rm opensearch-indexer
```

## What Is Implemented

- One root Docker Compose stack in `ETL/docker-compose.yml` for Kafka, Airflow,
  and OpenSearch.
- Manual Kafka file-ready signal publishing with the
  `ingestion-signal-publisher` compose service.
- Local DFS stand-in at `airflow/data/local_dfs_store/`.
- Rule-based file intake checks in `spark/security_scanner.py` for extension,
  size, filename, and SHA256 audit metadata.
- Shared transform logic in `spark/transform.py`:
  - HTML text extraction.
  - PDF text extraction through `pypdf` in Docker.
  - Language detection for English, Nepali, mixed, and unknown text.
  - SHA256 exact content fingerprinting.
  - SimHash fuzzy fingerprinting.
  - Seed geo-tagging rules for Kathmandu, Pokhara, and Janakpur.
  - Exact and fuzzy duplicate marking.
- Local unit tests for the Kafka receipt consumer and Spark transform logic.
- OpenSearch indexing from the existing transformed JSONL output with stable
  document IDs and explicit text/keyword mappings. See
  [`OpenSearch/OpenSearch.md`](OpenSearch/OpenSearch.md).

## Tests

From the repository root:

```bash
python -B ETL/kafka/test_consumer.py
python -B ETL/spark/test_security_scanner.py
python -B ETL/spark/test_transform.py
python -B ETL/spark/test_spark.py
```

`test_spark.py` runs the PySpark smoke test when PySpark is installed. On a
plain host without PySpark, it prints a message and exits successfully; the
Spark Docker image still runs it with PySpark installed.

## Future Work

- Replace local DFS with MinIO once that setup exists.
- Add ClamAV malware scanning. The current rule-based file scanner is an intake
  guard, not antivirus.
- Add the final PostgreSQL schema and write path.
- Add embeddings only if a future transform step produces them.
- Replace the seed geo rules with an official Nepal administrative
  gazetteer.
- Add production-grade Spark streaming from Kafka once the scraper contract is
  finalized.
