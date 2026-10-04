# ETL

ETL for a Nepali/English search engine: takes a "file ready" signal from Kafka,
security-checks and transforms the file (text extraction, dedup, geo-tagging,
LaBSE embedding), writes the result as JSONL, and indexes it into OpenSearch.
It uses local sample files instead of the scraper's storage and JSONL instead
of PostgreSQL for now; the target design is described in `spark/README.md`.

## Layout

| Path | What it is |
| --- | --- |
| `airflow/` | DAGs (`dags/`), the local file store and the JSONL output (`data/`). |
| `spark/` | Transform, dedup, embedding (`transform.py`) and intake security checks (`security_scanner.py`, rule-based + ClamAV). |
| `kafka/` | `consumer.py` (scraper → ETL hand-off for `crawled-documents`) and `tools/` scripts that publish test messages. |
| `OpenSearch/` | Indexer that bulk-loads the JSONL output into the `pgs_documents` index. |
| `Dockerfile` | The one image every ETL container runs (see below). |

## Workflow

```text
Kafka scraped_files_topic (file-ready signal)
  -> Airflow DAG etl_ingestion_pipeline
       poll_kafka_signal -> transform_document -> persist_transformed_document
       (reads airflow/data/local_dfs_store/<object_key>, scans it with the
        rule checks + ClamAV, extracts text, dedups, embeds with LaBSE)
  -> airflow/data/processed/transformed_documents.jsonl
  -> opensearch-indexer -> OpenSearch index pgs_documents
```

Other DAGs: `airflow_healthcheck` (scheduler/worker smoke test) and
`document_extraction_check` (parses `data/sample.html` / `data/sample.txt`).

## Run it

Everything runs from the repository-root `docker-compose.yml`, from the
repository root:

```bash
cp .env.example .env                                  # once; set AIRFLOW_UID to `id -u`
docker compose up -d --build                          # Kafka, ClamAV, OpenSearch, Airflow, ...
docker compose run --rm ingestion-signal-publisher    # publish one file-ready signal
# Airflow UI http://localhost:8080 (login from .env): trigger etl_ingestion_pipeline
docker compose run --rm opensearch-indexer            # index the JSONL output
docker compose run --rm etl-spark-test                # standalone Spark check
```

| Container | What it does |
| --- | --- |
| `airflow-init`, `airflow-webserver`, `airflow-scheduler`, `airflow-worker` | Airflow 2.10 with CeleryExecutor; metadata in `airflow-db`, queue in `redis` |
| `clamav` | ClamAV daemon the scanner streams files to (`CLAMD_HOST=clamav`); the first start downloads signatures (a few minutes) |
| `kafka` | Broker: `kafka:29092` from containers, `localhost:9092` from the host |
| `opensearch` | OpenSearch 2.19 (`http://localhost:9200`); 2.x because the index mapping uses the `nmslib` k-NN engine, which 3.x refuses for new indexes |
| `etl-consumer` | `kafka/consumer.py consume` on `crawled-documents`, SQLite receipts in the `etl-data` volume |
| `ingestion-signal-publisher`, `opensearch-indexer`, `etl-spark-test` | One-shot tools (`docker compose run --rm <name>`) |

All of them run one image, `ETL/Dockerfile`: Airflow 2.10 + JDK + PySpark 3.5.3,
plus kafka-python, pypdf, sentence-transformers (CPU-only PyTorch) and clamd.
`airflow/{dags,logs,plugins,config,data}` and `spark/` are bind-mounted into the
Airflow containers, so DAG and `transform.py` edits apply without a rebuild. The
LaBSE model (~1.8 GB) downloads on the first embedding into the `etl-models`
volume.

The shared `pgs-db` package needs SQLAlchemy 2, which Airflow 2.10 cannot load,
so it lives in a separate interpreter, `/opt/etl-venv/bin/python` (with the Kafka
and OpenSearch clients). The Kafka consumer and the indexer run with it; an
Airflow task can use it via `@task.external_python(python="/opt/etl-venv/bin/python")`.
ETL containers get `DATABASE_URL` for the `pgs_etl` role.

Host-side scripts in `kafka/tools/` publish to `localhost:9092`; see
`kafka/tools/README.md`. The `etl-consumer` service consumes what they send to
`crawled-documents` (`docker compose logs -f etl-consumer`); stop it first
(`docker compose stop etl-consumer`) to run the consumer on the host instead.

## Known gaps

- **Local stand-ins:** `airflow/data/local_dfs_store/` stands in for the
  scraper's object storage, and the DAG writes JSONL instead of PostgreSQL.
  The database write path is `pgs_db.etl.save_transformed(...)` as `pgs_etl`
  (see `database/README.md` §8).
- **Airflow is in the live per-document path**, which the target design
  replaces with Spark consuming Kafka directly (Airflow only for batch jobs).
- **The Kafka signal shape** (`object_key`, `target_domain`, ...) is not yet a
  confirmed contract with the scraper.
