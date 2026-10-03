"""Proves ETLStore's real duplicate protection: replaying the SAME Kafka
message (same topic/partition/offset) is a no-op the second time."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

# consumer.py lives one directory up, in ETL/kafka/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from consumer import ETLStore, process_message  # noqa: E402

document = {
    "url": "https://example.gov.np/notices/999",
    "normalized_url": "https://example.gov.np/notices/999",
    "host": "example.gov.np",
    "title": "Idempotency Test",
    "text": "Testing same-offset replay.",
    "links": [],
    "anchor_texts": [],
    "country": "NP",
    "depth": 0,
    "status_code": 200,
    "content_type": "text/html; charset=utf-8",
    "content_hash": "b" * 64,
    "fetched_at": "2026-09-23T10:00:00+00:00",
    "fetch_duration_ms": 100,
}

message = SimpleNamespace(
    topic="crawled-documents",
    partition=0,
    offset=999,  # same offset both times, simulating a replayed message
    key=document["normalized_url"].encode("utf-8"),
    value=json.dumps(document).encode("utf-8"),
)

db_path = Path(__file__).resolve().parent.parent / "etl.sqlite3"
store = ETLStore(str(db_path))
print("First process:", process_message(store, message))   # expect: loaded
print("Second process:", process_message(store, message))  # expect: duplicate
store.close()