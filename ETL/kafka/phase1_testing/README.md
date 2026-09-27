# Phase 1 Testing — Kafka + ETL Consumer

Proves the scraper -> Kafka -> ETL consumer handoff works end to end,
using dummy `Document` JSON shaped exactly like the scraper's
`model.Document` (Go), since real scraper output wasn't available yet.

## Prerequisites

From `ETL/kafka/`:

    docker compose up -d          # starts the local Kafka broker
    pip install -r requirements.txt

## How to run each test

All commands below are run from `ETL/kafka/` (one level above this
folder), so `consumer.py` can be found.

### 1. Single dummy document (happy path)

    python phase1_testing/produce_dummy.py
    python consumer.py consume --database ./etl.sqlite3 --max-messages 1

Expected: one line with `"status": "loaded"`.

### 2. Full outcome coverage (loaded / rejected paths)

    python phase1_testing/produce_test_cases.py
    python consumer.py consume --database ./etl.sqlite3 --max-messages 8

Expected: 2 `loaded` lines (cases 1-2, two separate valid Kafka messages
with identical content — see note below) and 6 `rejected` lines, each
with a different `reason` (bad key, bad hash, bad status code, missing
timezone, mismatched links/anchor_texts, invalid JSON).

### 3. Real duplicate detection (offset-level idempotency)

    python phase1_testing/test_idempotency.py

Expected: `First process: ... loaded` then `Second process: ... duplicate`.

## Note on "duplicate" vs content-level dedup

`ETLStore`'s primary key is `(topic, partition, offset)` — it prevents
**re-processing the same Kafka message twice** (e.g. a crash/restart
before the offset was committed). It does NOT do content-level
deduplication — two different Kafka messages with identical
`content_hash` both get `loaded`, correctly, by this consumer.

Content-level dedup (SHA256 exact match + SimHash fuzzy match across
the whole corpus) is Spark's responsibility per the architecture spec,
and is tested separately in the Spark transformation phase.

## Checking results directly

    sqlite3 etl.sqlite3 "SELECT normalized_url, content_hash FROM documents;"
    sqlite3 etl.sqlite3 "SELECT offset_id, reason FROM rejected ORDER BY offset_id;"

## Known gaps for later phases
- No MinIO/raw-storage step yet — once a message is consumed off Kafka,
  the raw document only survives in the SQLite receipt table.
- ETL -> Postgres write path not built yet, pending schema sync with the
  database team.