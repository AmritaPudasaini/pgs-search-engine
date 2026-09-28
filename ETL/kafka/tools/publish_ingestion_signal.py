"""Publish a file-ready ingestion signal for the ETL pipeline."""

import json
from datetime import datetime, timezone

from kafka import KafkaProducer

signal = {
    "bucket": "etl-file-store",
    "object_key": "sample.html",  # must exist in ETL/airflow/data/local_dfs_store/
    "target_domain": "example.gov.np",
    "source_url": "https://example.gov.np/notices/sample",
    "title": "Sample Municipality Notice",
    "content_type": "text/html",
    "scraped_at": datetime.now(timezone.utc).isoformat(),
}

producer = KafkaProducer(
    bootstrap_servers=["localhost:9092"],  # host -> Kafka's external listener
    key_serializer=lambda k: k.encode("utf-8"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)

producer.send("scraped_files_topic", key=signal["target_domain"], value=signal)
producer.flush()
print("Sent 1 file-ready ingestion signal to topic 'scraped_files_topic'")
