"""Publish a dummy 'file ready in DFS' signal, standing in for what the
scraper will eventually emit once it writes to MinIO."""

import json
from datetime import datetime, timezone

from kafka import KafkaProducer

signal = {
    "bucket": "dummy-dfs",
    "object_key": "sample.html",  # must exist in ETL/airflow/data/dummy_dfs/
    "target_domain": "example.gov.np",
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
print("Sent 1 dummy file-ready signal to topic 'scraped_files_topic'")