"""Temporal activities of the ETL worker. The worker process is the Spark
driver: it holds one long-lived SparkSession on the standalone cluster
(``SPARK_MASTER``), and each activity submits one site's job to it."""

from __future__ import annotations

import os
import sys
import threading

from temporalio import activity

SPARK_LIB = os.environ.get("SPARK_LIB", "/opt/airflow/spark_lib")
if SPARK_LIB not in sys.path:
    sys.path.insert(0, SPARK_LIB)

import site_pipeline  # noqa: E402  (needs SPARK_LIB on sys.path)

PROCESSED_OUTPUT = os.environ.get(
    "ETL_PROCESSED_OUTPUT", "/opt/airflow/data/processed/transformed_documents.jsonl"
)

_spark = None
_spark_lock = threading.Lock()


def _session():
    """The shared SparkSession, recreated if its SparkContext has stopped (for
    example after the Spark master restarted)."""
    global _spark
    with _spark_lock:
        jsc = _spark.sparkContext._jsc if _spark is not None else None
        if jsc is None or jsc.sc().isStopped():
            _spark = site_pipeline.create_spark_session("pgs-etl-worker")
        return _spark


def stop_session() -> None:
    with _spark_lock:
        if _spark is not None:
            _spark.stop()


@activity.defn(name="run_site_pipeline")
def run_site_pipeline(event: dict) -> dict:
    activity.logger.info("site %s (run %s)", event.get("target_domain"), event.get("crawl_run_id"))
    return site_pipeline.run_site_pipeline(event, PROCESSED_OUTPUT, spark=_session())
