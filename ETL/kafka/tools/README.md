# Kafka Utilities

These scripts simulate the scraper side of the ETL handoff while the scraper
itself is not part of this local ETL setup.

## Start Kafka

Preferred:

```bash
# from the repository root
docker compose up -d --build
```

Kafka is exposed on `localhost:9092`.

## Send A File-Ready Signal

This is the main signal used by the Airflow DAG `etl_ingestion_pipeline`.

```bash
# from the repository root
docker compose run --rm ingestion-signal-publisher
```

The signal points to `ETL/airflow/data/local_dfs_store/sample.html` and is
published to `scraped_files_topic`.

If you prefer running the host Python script directly, install this folder's
requirements first:

```bash
cd ETL/kafka
pip install -r requirements.txt
python tools/publish_ingestion_signal.py
```

## Test The Durable Receipt Consumer

The receipt consumer validates full crawler `Document` JSON messages and stores
loaded/rejected receipts in SQLite. It is separate from content-level
deduplication, which belongs to `ETL/spark/transform.py`.

```bash
cd ETL/kafka
python tools/publish_crawler_document.py
python consumer.py consume --database ./etl.sqlite3 --max-messages 1
```

For validation coverage:

```bash
python tools/publish_validation_documents.py
python consumer.py consume --database ./etl.sqlite3 --max-messages 8
```

For offset-level idempotency:

```bash
python tools/validate_consumer_idempotency.py
```

## Local Unit Test

From the repository root:

```bash
python -B ETL/kafka/test_consumer.py
```
