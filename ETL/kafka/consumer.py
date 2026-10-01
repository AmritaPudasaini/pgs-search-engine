"""Consume crawler documents from Kafka and load durable ETL receipts."""

import argparse
import json
import os
import re
import signal
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


SHA256 = re.compile(r"[0-9a-f]{64}")


def _is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_url(value, field):
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError(f"invalid {field}")


def _validate_string_list(value, field):
    # Go encodes an empty nil slice as null, so both null and [] are valid.
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"invalid {field}")


def validate_document(document):
    """Validate fields guaranteed by scraper's model.Document contract."""
    if not isinstance(document, dict):
        raise ValueError("document must be a JSON object")

    _validate_url(document.get("url"), "url")
    _validate_url(document.get("normalized_url"), "normalized_url")

    for field in ("title", "text", "content_type"):
        if not isinstance(document.get(field), str):
            raise ValueError(f"invalid {field}")

    content_hash = document.get("content_hash")
    if not isinstance(content_hash, str) or not SHA256.fullmatch(content_hash):
        raise ValueError("invalid content_hash")

    status_code = document.get("status_code")
    if not _is_integer(status_code) or not 200 <= status_code < 300:
        raise ValueError("invalid status_code")

    for field in ("depth", "fetch_duration_ms"):
        value = document.get(field)
        if not _is_integer(value) or value < 0:
            raise ValueError(f"invalid {field}")

    try:
        fetched_at = datetime.fromisoformat(document.get("fetched_at", "").replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid fetched_at") from exc
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must include timezone")

    links = document.get("links")
    _validate_string_list(links, "links")
    anchor_texts = document.get("anchor_texts")
    _validate_string_list(anchor_texts, "anchor_texts")
    if anchor_texts is not None and len(anchor_texts) != len(links or []):
        raise ValueError("anchor_texts must match links")

    headings = document.get("headings")
    if headings is not None:
        if not isinstance(headings, list):
            raise ValueError("invalid headings")
        for heading in headings:
            if (
                not isinstance(heading, dict)
                or not _is_integer(heading.get("level"))
                or not 1 <= heading["level"] <= 6
                or not isinstance(heading.get("text"), str)
            ):
                raise ValueError("invalid heading")

    _validate_string_list(document.get("json_ld"), "json_ld")

    geo = document.get("geo")
    if geo is not None:
        if not isinstance(geo, dict):
            raise ValueError("invalid geo")
        lat, lng = geo.get("lat"), geo.get("lng")
        if (
            isinstance(lat, bool)
            or not isinstance(lat, (int, float))
            or not -90 <= lat <= 90
            or isinstance(lng, bool)
            or not isinstance(lng, (int, float))
            or not -180 <= lng <= 180
        ):
            raise ValueError("invalid geo coordinates")

    return document


class ETLStore:
    """SQLite load target used before a Kafka offset is committed."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "topic TEXT NOT NULL, partition_id INTEGER NOT NULL, offset_id INTEGER NOT NULL, "
            "normalized_url TEXT NOT NULL, content_hash TEXT NOT NULL, body TEXT NOT NULL, "
            "loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY(topic, partition_id, offset_id))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS rejected ("
            "topic TEXT NOT NULL, partition_id INTEGER NOT NULL, offset_id INTEGER NOT NULL, "
            "reason TEXT NOT NULL, body BLOB, rejected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY(topic, partition_id, offset_id))"
        )

    def load(self, message, document):
        body = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO documents "
                "(topic, partition_id, offset_id, normalized_url, content_hash, body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message.topic,
                    message.partition,
                    message.offset,
                    document["normalized_url"],
                    document["content_hash"],
                    body,
                ),
            )
        return cursor.rowcount == 1

    def reject(self, message, reason):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO rejected "
                "(topic, partition_id, offset_id, reason, body) VALUES (?, ?, ?, ?, ?)",
                (message.topic, message.partition, message.offset, reason, message.value),
            )

    def close(self):
        self.db.close()


def process_message(store, message):
    """Validate and load one message. Invalid records go to rejected."""
    try:
        document = validate_document(json.loads(message.value))
        expected_key = document["normalized_url"].encode("utf-8")
        if message.key != expected_key:
            raise ValueError("Kafka key must equal normalized_url")
        fresh = store.load(message, document)
        return {
            "status": "loaded" if fresh else "duplicate",
            "normalized_url": document["normalized_url"],
            "partition": message.partition,
            "offset": message.offset,
        }
    except (AttributeError, TypeError, UnicodeDecodeError, ValueError) as exc:
        store.reject(message, str(exc))
        return {
            "status": "rejected",
            "reason": str(exc),
            "partition": message.partition,
            "offset": message.offset,
        }


def export_documents(path):
    """Yield loaded documents without changing the receipt database."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        for (body,) in connection.execute(
            "SELECT body FROM documents ORDER BY topic, partition_id, offset_id"
        ):
            yield json.loads(body)
    finally:
        connection.close()


def consume(args):
    from kafka import KafkaConsumer, OffsetAndMetadata, TopicPartition

    consumer = KafkaConsumer(
        args.topic,
        bootstrap_servers=[item.strip() for item in args.brokers.split(",") if item.strip()],
        group_id=args.group,
        client_id="search-engine-etl",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_records=1,
    )
    store = ETLStore(args.database)
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    consumed = 0
    try:
        while running:
            for batch in consumer.poll(timeout_ms=1000, max_records=1).values():
                for message in batch:
                    result = process_message(store, message)
                    print(json.dumps(result, ensure_ascii=False), flush=True)

                    # Commit only after document or rejection is durable.
                    consumer.commit(
                        {
                            TopicPartition(message.topic, message.partition): OffsetAndMetadata(
                                message.offset + 1, "", getattr(message, "leader_epoch", -1)
                            )
                        }
                    )
                    consumed += 1
                    if args.max_messages and consumed >= args.max_messages:
                        running = False
    finally:
        consumer.close(autocommit=False)
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("consume", "export"), nargs="?", default="consume")
    parser.add_argument("--brokers", default=os.getenv("KAFKA_BROKERS", "localhost:9092"))
    parser.add_argument("--topic", default=os.getenv("KAFKA_TOPIC", "crawled-documents"))
    parser.add_argument("--group", default=os.getenv("KAFKA_GROUP", "search-engine-etl-v1"))
    parser.add_argument("--database", default=os.getenv("ETL_DATABASE", "/data/etl.sqlite3"))
    parser.add_argument("--max-messages", type=int, default=0)
    args = parser.parse_args()
    if args.max_messages < 0:
        parser.error("max-messages must be nonnegative")

    if args.mode == "export":
        for document in export_documents(args.database):
            print(json.dumps(document, ensure_ascii=False))
    else:
        consume(args)


if __name__ == "__main__":
    main()
