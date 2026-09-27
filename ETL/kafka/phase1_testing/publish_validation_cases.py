"""Publish one of each outcome: loaded, duplicate, and several rejection
reasons, so you can see consumer.py's full validation path in action."""

import hashlib
import json
from datetime import datetime, timezone

from kafka import KafkaProducer

BASE_TEXT = (
    "Kathmandu Metropolitan City This is a dummy notice used to test "
    "text extraction in Airflow. Contact: info@example.gov.np"
)


def base_document(url_suffix=1):
    text = f"{BASE_TEXT} (case {url_suffix})"
    return {
        "url": f"https://example.gov.np/notices/{url_suffix}",
        "normalized_url": f"https://example.gov.np/notices/{url_suffix}",
        "host": "example.gov.np",
        "title": "Sample Municipality Notice",
        "text": text,
        "headings": [{"level": 1, "text": "Kathmandu Metropolitan City"}],
        "links": [],
        "anchor_texts": [],
        "country": "NP",
        "depth": 0,
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_duration_ms": 120,
    }


producer = KafkaProducer(
    bootstrap_servers=["localhost:9092"],
    key_serializer=lambda k: k if isinstance(k, bytes) else k.encode("utf-8"),
    value_serializer=lambda v: v if isinstance(v, bytes) else json.dumps(v, ensure_ascii=False).encode("utf-8"),
)


def send(label, key, value):
    producer.send("crawled-documents", key=key, value=value)
    print(f"sent: {label}")


# 1. LOADED — a fresh, fully valid document.
doc1 = base_document(url_suffix=101)
send("valid (should be 'loaded')", doc1["normalized_url"], doc1)

# 2. Same document again as a NEW Kafka message (different offset).
#    Correctly still 'loaded' -- content-level dedup is Spark's job, not
#    this consumer's. See test_idempotency.py for the real duplicate case.
send("exact repeat, new offset (should be 'loaded' again)", doc1["normalized_url"], doc1)

# 3. REJECTED — Kafka key doesn't match normalized_url.
doc3 = base_document(url_suffix=102)
send("wrong key (should be 'rejected')", "not-the-normalized-url", doc3)

# 4. REJECTED — bad content_hash (not 64 hex chars).
doc4 = base_document(url_suffix=103)
doc4["content_hash"] = "not-a-real-hash"
send("bad content_hash (should be 'rejected')", doc4["normalized_url"], doc4)

# 5. REJECTED — bad status_code (outside 200-299).
doc5 = base_document(url_suffix=104)
doc5["status_code"] = 500
send("bad status_code (should be 'rejected')", doc5["normalized_url"], doc5)

# 6. REJECTED — fetched_at missing a timezone.
doc6 = base_document(url_suffix=105)
doc6["fetched_at"] = "2026-09-23T10:00:00"  # no +00:00 / Z
send("fetched_at with no timezone (should be 'rejected')", doc6["normalized_url"], doc6)

# 7. REJECTED — links/anchor_texts length mismatch.
doc7 = base_document(url_suffix=106)
doc7["links"] = ["https://example.gov.np/about"]
doc7["anchor_texts"] = []  # should be 1 item, not 0
send("links/anchor_texts mismatch (should be 'rejected')", doc7["normalized_url"], doc7)

# 8. REJECTED — not valid JSON at all (raw garbage bytes).
send("invalid JSON (should be 'rejected')", "case-108", b"this is not json")

producer.flush()
print("\nAll 8 test messages sent.")