"""ETL ingestion pipeline DAG.

This keeps the workflow self-contained inside ETL while the scraper, MinIO,
PostgreSQL schema, OpenSearch mapping, and ClamAV pieces are still separate
future work.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException


DFS_ROOT = Path("/opt/airflow/data/local_dfs_store")
PROCESSED_OUTPUT = Path("/opt/airflow/data/processed/transformed_documents.jsonl")
SPARK_LIB = "/opt/airflow/spark_lib"
KAFKA_BOOTSTRAP = "kafka:29092"
KAFKA_TOPIC = "scraped_files_topic"


def _load_existing_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


@dag(
    dag_id="etl_ingestion_pipeline",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["etl", "ingestion", "kafka", "spark"],
)
def etl_ingestion_pipeline():
    @task
    def poll_kafka_signal() -> dict:
        from kafka import KafkaConsumer

        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=[KAFKA_BOOTSTRAP],
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            group_id="etl-ingestion-pipeline",
            consumer_timeout_ms=8000,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
        try:
            for message in consumer:
                signal = message.value
                if "object_key" not in signal:
                    raise ValueError("Kafka signal must include object_key")
                return signal
        finally:
            consumer.close()
        raise AirflowSkipException("No new file-ready signal on Kafka")

    @task
    def transform_document(signal: dict) -> dict:
        if SPARK_LIB not in sys.path:
            sys.path.insert(0, SPARK_LIB)

        from transform import mark_duplicates, transform_file

        transformed = transform_file(signal, DFS_ROOT)
        existing = _load_existing_records(PROCESSED_OUTPUT)
        marked = mark_duplicates([*existing, transformed])
        return marked[-1]

    @task
    def persist_transformed_document(record: dict) -> dict:
        if SPARK_LIB not in sys.path:
            sys.path.insert(0, SPARK_LIB)

        from transform import append_jsonl

        append_jsonl(PROCESSED_OUTPUT, [record])
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return {
            "document_id": record["document_id"],
            "output": str(PROCESSED_OUTPUT),
            "duplicate": record["duplicate"],
            "duplicate_type": record["duplicate_type"],
        }

    persist_transformed_document(transform_document(poll_kafka_signal()))


etl_ingestion_pipeline()
