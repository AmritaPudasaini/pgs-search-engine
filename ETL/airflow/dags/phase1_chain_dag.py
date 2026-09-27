"""Phase 1 chain test: Kafka signal -> fetch from (dummy) DFS -> Spark
transform. Proves Airflow, Kafka, and Spark work together end to end.
Real dedup/geo-tagging is separate, later work (Spark Transformation)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException

DFS_ROOT = Path("/opt/airflow/data/local_dfs_store")  # stand-in for the MinIO raw bucket
SPARK_LIB = "/opt/airflow/spark_lib"  # mounted from ETL/spark, see docker-compose.yaml
KAFKA_BOOTSTRAP = "kafka:29092"  # container-to-container address
KAFKA_TOPIC = "scraped_files_topic"  # matches spark/README.md's event-bus topic name


@dag(
    dag_id="phase1_kafka_dfs_spark_chain",
    schedule=None,  # triggered manually for Phase 1 testing
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["phase1", "etl", "kafka", "spark"],
)
def phase1_chain():
    @task
    def poll_kafka_signal() -> dict:
        """Pull one 'file ready' signal off Kafka. Stands in for the
        completion signal the scraper will eventually emit after
        writing to MinIO."""
        from kafka import KafkaConsumer

        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=[KAFKA_BOOTSTRAP],
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            group_id="phase1-chain-dag",
            consumer_timeout_ms=8000,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        for message in consumer:
            consumer.close()
            return message.value
        consumer.close()
        raise AirflowSkipException("No new file-ready signal on Kafka")

    @task
    def fetch_from_dfs(signal: dict) -> dict:
        """Read the referenced file from the local dummy folder, standing
        in for a MinIO GetObject call."""
        file_path = DFS_ROOT / signal["object_key"]
        if not file_path.exists():
            raise FileNotFoundError(f"{file_path} not found in dummy DFS folder")
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        return {
            "object_key": signal["object_key"],
            "target_domain": signal.get("target_domain", "unknown"),
            "content": content,
        }

    @task
    def run_spark_transform(fetched: dict) -> dict:
        """Runs the shared Spark transformation logic (ETL/spark/transform.py)
        against the fetched document, inside Airflow's embedded PySpark.
        Same logic as spark/test_spark.py -- kept in one place so both
        environments stay in sync."""
        if SPARK_LIB not in sys.path:
            sys.path.insert(0, SPARK_LIB)
        from transform import analyze_text
        from pyspark.sql import SparkSession

        spark = (
            SparkSession.builder.master("local[1]")
            .appName("phase1-chain-test")
            .getOrCreate()
        )
        transformed = analyze_text(spark, fetched["content"])
        transformed.show(truncate=80)  # visible in this task's Airflow logs
        result = transformed.collect()[0]
        spark.stop()

        return {
            "object_key": fetched["object_key"],
            "target_domain": fetched["target_domain"],
            "char_count": result["char_count"],
            "word_count": result["word_count"],
        }

    @task
    def log_result(result: dict) -> None:
        print(f"Phase 1 chain OK: {json.dumps(result, indent=2)}")

    log_result(run_spark_transform(fetch_from_dfs(poll_kafka_signal())))


phase1_chain()