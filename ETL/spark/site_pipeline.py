"""PySpark ETL pipeline for one crawled website.

The scraper publishes one ``site_crawl_completed`` event to Kafka when it has
finished crawling a website (see scraper/internal/storage/site_events.go).
The ``etl_ingestion_pipeline`` DAG collects these events in batches and hands
each batch to Temporal (ETL/temporal), whose ETL worker is the Spark driver and
runs ``run_site_pipeline`` once per site on the Spark cluster. Everything
after the crawl happens here, in order:

1. list the site's Document JSON objects under ``documents_prefix``;
2. per page, in Spark tasks: read the stored HTML from S3, run the intake
   security checks (rule checks + ClamAV), extract and normalize the text;
3. on the driver: mark exact/near duplicates (against earlier output and
   within the site), embed the new documents with LaBSE, append the records
   to the JSONL output.

S3 settings come from the environment: ``S3_ENDPOINT`` (empty for AWS),
``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY`` and ``AWS_REGION``. The Spark
master is ``SPARK_MASTER`` (default ``local[*]``; ``spark://spark-master:7077``
in docker-compose).
"""

from __future__ import annotations

import json
import os
import posixpath
import socket
import sys
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path

SITE_EVENT_TYPE = "site_crawl_completed"
REQUIRED_EVENT_FIELDS = ("crawl_run_id", "target_domain", "bucket", "documents_prefix")
_MODULE_DIR = Path(__file__).resolve().parent
# Read the existing output, dedup, embed and append as one step, so sites
# processed concurrently in one driver process can't interleave.
_OUTPUT_LOCK = threading.Lock()
# Passed to the executors, which read S3 and call ClamAV.
_EXECUTOR_ENV = (
    "S3_ENDPOINT", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "CLAMD_HOST", "CLAMD_PORT",
)


class ScannerUnavailable(RuntimeError):
    """ClamAV could not scan a file. The run fails so it is retried later,
    instead of rejecting every page of the site as unscanned."""


def validate_event(event: object) -> dict:
    """Return the event if it is a site-crawled event the pipeline can run."""
    if not isinstance(event, dict) or event.get("event_type") != SITE_EVENT_TYPE:
        raise ValueError(f"not a {SITE_EVENT_TYPE} event")
    missing = [field for field in REQUIRED_EVENT_FIELDS if not event.get(field)]
    if missing:
        raise ValueError(f"site event is missing {', '.join(missing)}")
    if not str(event["documents_prefix"]).endswith("/"):
        raise ValueError("documents_prefix must end with '/'")
    return event


def s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT") or None,
        region_name=os.environ.get("AWS_REGION") or None,
    )


def list_document_keys(client, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []) if obj["Key"].endswith(".json"))
    return sorted(keys)


def _read(client, bucket: str, key: str) -> bytes:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


def process_page(client, event: dict, document_key: str) -> dict:
    """Scan, extract and transform one stored page. Returns
    ``{"status": "transformed", "record": ...}`` or ``{"status": "rejected", ...}``."""
    from security_scanner import inspect_bytes
    from transform import extract_html_text, normalize_text, transform_document

    bucket = event["bucket"]
    document = json.loads(_read(client, bucket, document_key))
    # The rendered capture holds JavaScript-built content the raw HTML lacks.
    html_key = document.get("rendered_html_key") or document.get("html_key")
    if html_key:
        object_key = posixpath.join(event.get("key_prefix") or "", html_key)
        content = _read(client, bucket, object_key)
        filename = posixpath.basename(html_key)
    else:
        # No raw HTML stored for this page: use the text the scraper extracted.
        object_key = document_key
        content = (document.get("text") or "").encode("utf-8")
        filename = posixpath.basename(document_key).removesuffix(".json") + ".txt"

    scan = inspect_bytes(filename, content)
    if scan["clamav_status"] == "ERROR":
        raise ScannerUnavailable(f"ClamAV could not scan s3://{bucket}/{object_key}")
    source_url = document.get("final_url") or document.get("url") or ""
    if not scan["accepted"]:
        return {
            "status": "rejected",
            "source_url": source_url,
            "object_key": object_key,
            "security_scan": scan,
        }

    raw = content.decode("utf-8", errors="ignore")
    text = extract_html_text(raw) if filename.endswith((".html", ".htm")) else normalize_text(raw)
    record = transform_document(
        source_url=source_url,
        text=text,
        title=document.get("title") or "",
        target_domain=event["target_domain"],
        object_key=f"s3://{bucket}/{object_key}",
        with_embedding=False,
    )
    record["crawl_run_id"] = event["crawl_run_id"]
    record["fetched_at"] = document.get("fetched_at")
    record["security_scan"] = scan
    return {"status": "transformed", "record": record}


def _process_partition(event: dict, document_keys: Iterable[str]) -> Iterator[dict]:
    client = s3_client()  # one client per Spark task, not per page
    for key in document_keys:
        yield process_page(client, event, key)


def create_spark_session(app_name: str):
    """A SparkSession on ``SPARK_MASTER`` with this package's modules shipped to
    the executors. On a standalone cluster the executors connect back to this
    process (the driver), so it advertises its own container IP."""
    from pyspark.sql import SparkSession

    master = os.environ.get("SPARK_MASTER", "local[*]")
    builder = (
        SparkSession.builder.master(master)
        .appName(app_name)
        .config("spark.pyspark.python", sys.executable)
        .config("spark.scheduler.mode", "FAIR")  # concurrent sites share the cluster fairly
    )
    if master.startswith("spark://"):
        builder = (
            builder.config("spark.driver.host", socket.gethostbyname(socket.gethostname()))
            .config("spark.driver.bindAddress", "0.0.0.0")
            .config("spark.executor.memory", os.environ.get("SPARK_EXECUTOR_MEMORY", "1g"))
            .config("spark.executor.cores", os.environ.get("SPARK_EXECUTOR_CORES", "1"))
        )
        if os.environ.get("SPARK_CORES_MAX"):
            builder = builder.config("spark.cores.max", os.environ["SPARK_CORES_MAX"])
        for name in _EXECUTOR_ENV:
            if os.environ.get(name):
                builder = builder.config(f"spark.executorEnv.{name}", os.environ[name])
    spark = builder.getOrCreate()
    for module in ("security_scanner.py", "transform.py", "site_pipeline.py"):
        spark.sparkContext.addPyFile(str(_MODULE_DIR / module))
    return spark


def _already_processed(path: Path, crawl_run_id: int, target_domain: str) -> bool:
    """Whether the output already holds this site's records from this run (a
    retried batch must not append them twice)."""
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if f'"{target_domain}"' not in line:  # cheap pre-filter
                continue
            record = json.loads(line)
            site = (record.get("crawl_run_id"), record.get("target_domain"))
            if site == (crawl_run_id, target_domain):
                return True
    return False


def _load_existing_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def dedupe_and_embed(records: list[dict], existing: list[dict]) -> list[dict]:
    """Mark duplicates against ``existing`` and each other; embed only new text
    (a duplicate reuses its canonical document's vector)."""
    from transform import add_embeddings, mark_duplicates

    marked = mark_duplicates([*existing, *records])[len(existing):]
    add_embeddings([record for record in marked if not record["duplicate"]])

    by_id = {doc["document_id"]: doc for doc in existing}
    by_id.update({doc["document_id"]: doc for doc in marked if not doc["duplicate"]})
    for record in marked:
        canonical = by_id.get(record["duplicate_of"]) if record["duplicate"] else None
        if canonical and canonical.get("embedding"):
            for field in ("embedding", "embedding_model", "embedding_dim"):
                record[field] = canonical.get(field)
    return marked


def run_site_pipeline(event: dict, output_path: str | Path, spark=None) -> dict:
    """Run the whole ETL for one crawled site and append its records to
    ``output_path`` (JSONL). ``spark`` is a session to run on (the ETL worker's
    long-lived one); without it a session is created and stopped. Returns a
    summary."""
    from transform import append_jsonl

    event = validate_event(event)
    output = Path(output_path)
    if _already_processed(output, event["crawl_run_id"], event["target_domain"]):
        return {
            "crawl_run_id": event["crawl_run_id"],
            "target_domain": event["target_domain"],
            "already_processed": True,
        }
    keys = list_document_keys(s3_client(), event["bucket"], event["documents_prefix"])
    summary = {
        "crawl_run_id": event["crawl_run_id"],
        "target_domain": event["target_domain"],
        "crawl_status": event.get("status"),
        "documents": len(keys),
        "transformed": 0,
        "duplicates": 0,
        "rejected": 0,
        "output": str(output),
    }
    if not keys:
        return summary

    own_session = spark is None
    if own_session:
        spark = create_spark_session(f"pgs-etl-{event['target_domain']}-{event['crawl_run_id']}")
    try:
        sc = spark.sparkContext
        sc.setJobGroup(f"{event['crawl_run_id']}/{event['target_domain']}", "PGS site ETL")
        slices = max(1, min(len(keys), sc.defaultParallelism * 4))
        results = (
            sc.parallelize(keys, slices)
            .mapPartitions(lambda part: _process_partition(event, part))
            .collect()
        )
    finally:
        if own_session:
            spark.stop()

    records = [result["record"] for result in results if result["status"] == "transformed"]
    rejected = [result for result in results if result["status"] == "rejected"]
    for item in rejected:
        findings = item["security_scan"]["findings"]
        print(f"rejected by intake checks: {item['source_url']} {findings}")

    with _OUTPUT_LOCK:
        marked = dedupe_and_embed(records, _load_existing_records(output))
        append_jsonl(output, marked)
    summary.update(
        transformed=len(marked),
        duplicates=sum(1 for record in marked if record["duplicate"]),
        rejected=len(rejected),
    )
    return summary
