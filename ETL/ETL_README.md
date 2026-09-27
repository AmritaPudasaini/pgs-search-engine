# ETL

Consumes crawled content from Kafka, transforms it with Spark (dedup,
geo-tagging, embedding), and hands the result off for storage. Also
runs scheduled batch maintenance via Airflow.

## Layout

| Path | What it is |
| --- | --- |
| `airflow/` | Orchestration. Docker Compose stack + DAGs. |
| `kafka/` | Consumer that reads crawled documents off Kafka and validates them. |
| `spark/` | Shared Spark transformation logic (Docker image + jobs). |

## Architecture (target)

```
Kafka (scraped_files_topic) -> Spark (parse, dedup, geo-tag, embed) -> Postgres + OpenSearch
```

Airflow runs *alongside* this, on a schedule, for batch maintenance
(nightly dedup, index cleanup) — it is not meant to sit in the live
per-document path in the final design. See `spark/README.md` for the
full architecture spec. **Phase 1 (below) currently routes documents
through Airflow to prove the pieces work together — that's a testing
stand-in, not the final wiring.**

## Local setup

You need Kafka and Airflow running; both share one Docker network so
Airflow can reach Kafka by container name.

```bash
# 1. One-time: create the shared network
docker network create pgs-etl-dag

# 2. Start Kafka
cd ETL/kafka
docker compose up -d

# 3. Start Airflow (builds a custom image with PySpark + kafka-python
#    baked in, and mounts ETL/spark/ so DAGs can import transform.py)
cd ../airflow
docker compose build
docker compose up -d
```

Airflow UI: http://localhost:8080 (login: `airflow` / `airflow`).
Give the webserver ~30-40s after `up -d` to pass its healthcheck.

## What's here so far (Phase 1 — proving the tools work together)

Real scraper data and a real MinIO instance aren't available yet, so
this phase uses stand-ins:
- `airflow/data/local_dfs_store/` stands in for MinIO.
- Small hand-built JSON messages stand in for what the scraper will
  eventually publish (its real output format isn't finalized yet).

### Kafka consumer (`kafka/`)

`kafka/consumer.py` validates and loads a scraped `Document` JSON off
Kafka into a local SQLite store — this is the scraper→ETL handoff,
tested independently of the chain below. Full test coverage and
how-to-run instructions: `kafka/phase1_testing/README.md`.

Scripts in `kafka/phase1_testing/`:
| Script | What it does |
| --- | --- |
| `publish_sample_document.py` | Publishes one valid dummy `Document` |
| `publish_validation_cases.py` | Publishes 8 cases covering loaded/rejected paths |
| `test_consumer_idempotency.py` | Proves same-offset replay is a no-op |
| `publish_dfs_ready_signal.py` | Publishes a "file ready" signal (used by the chain DAG below) |

### Airflow chain DAG (`airflow/dags/phase1_chain_dag.py`)

Proves Airflow, Kafka, and Spark can pass data to each other end to
end. Four tasks, run in sequence:

```
poll_kafka_signal -> fetch_from_dfs -> run_spark_transform -> log_result
```

1. **poll_kafka_signal** — reads one "file ready" message off topic
   `scraped_files_topic` (8s timeout; skips the run if nothing's there).
2. **fetch_from_dfs** — reads the referenced file from
   `local_dfs_store/`, standing in for a MinIO `GetObject` call.
3. **run_spark_transform** — runs `spark/transform.py`'s
   `analyze_text()` on the fetched content, inside Airflow's embedded
   PySpark. This is a **placeholder** (char/word count) — see Known
   gaps below.
4. **log_result** — prints the result to the task's Airflow logs.

### Running it

```bash
cd ETL/kafka
python phase1_testing/publish_dfs_ready_signal.py
```
Then in the Airflow UI: unpause `phase1_kafka_dfs_spark_chain`, trigger
it (▶), and open the `run_spark_transform` task's logs — you'll see an
actual Spark DataFrame table (`raw_text | char_count | word_count`)
printed, confirming the signal made it through Kafka, the local DFS
stand-in, and real PySpark execution, and back out through
`log_result`.

### Shared Spark logic (`spark/`)

`spark/transform.py` holds `analyze_text()` — the one place Spark
transformation logic lives. Both `spark/test_spark.py` (standalone,
run via the `spark/Dockerfile` image) and the Airflow chain DAG
(`run_spark_transform`, run via Airflow's embedded PySpark) import and
call this same function, so there's one implementation, not two
copies that could drift apart.

```bash
# Run the standalone Spark test directly (no Airflow needed):
cd ETL/spark
docker build -t pgs-spark-test .
docker run --rm pgs-spark-test
```

## Known gaps (intentional, for later phases)

- **`analyze_text()` is a placeholder** — char/word counts only. Real
  DOM/PDF parsing, content dedup (SHA256 exact + SimHash fuzzy match),
  and geo-tagging (province/district/municipality) are separate, later
  work (Spark Transformation / Spark Malware Test tasks). This is the
  one function to replace — the Kafka/Airflow wiring around it doesn't
  need to change.
- **Two Spark "environments" currently exist** — PySpark embedded
  directly in the Airflow image (used by the chain DAG) and the
  separate `spark/Dockerfile` image (used standalone). Both now run the
  same logic via `transform.py`, but production will likely want real
  Spark cluster/executor parallelism rather than PySpark embedded in a
  single Airflow task — worth deciding before scaling past dummy data.
- **No MinIO instance yet** — `local_dfs_store/` is a stand-in;
  `fetch_from_dfs` reads a local path, not MinIO's API.
- **Airflow is in the live per-document path right now** (as tested
  above), which contradicts the target architecture where Spark
  consumes Kafka directly and Airflow only runs scheduled batch jobs.
  This chain DAG is an integration proof, not the intended final wiring.
- **Kafka signal shape is unconfirmed** — `scraped_files_topic` and its
  fields (`object_key`, `target_domain`, etc.) come from
  `spark/README.md`'s spec, not a confirmed contract with the scraper
  team. The scraper's current code doesn't actually emit this yet.
- **No Postgres/OpenSearch write path yet** — pending schema sync with
  the database team.
- **Malware scanning (ClamAV) not implemented yet.**

## For contributors

- Picking up **Spark Transformation** or **Spark Malware Test**? Start
  in `spark/transform.py` — replace `analyze_text()` with real logic.
  Both the standalone test and the Airflow chain pick it up
  automatically once it's updated.
- Picking up the **database write path**? See `fetch_from_dfs` and
  `run_spark_transform` in `airflow/dags/phase1_chain_dag.py` for where
  a real write step would plug in after transformation.
- Questions about the Kafka message contract (what the scraper
  actually sends) should go to whoever owns `scraper/` — the current
  signal shape here is a guess based on the architecture doc, not a
  confirmed agreement.
