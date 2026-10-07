"""Temporal workflow for one batch of crawled sites.

The ``etl_ingestion_pipeline`` Airflow DAG starts one ``EtlBatchWorkflow`` per
batch of ``site_crawl_completed`` events and waits for it; the ETL worker
(worker.py) runs it. Each site is one ``run_site_pipeline`` activity, so a
site that fails is retried on its own, a bounded number of sites at a time.

Workflow code runs in Temporal's sandbox: only temporalio and the standard
library are imported here; the activity is referenced by name.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

TASK_QUEUE = "etl-task-queue"
DEFAULT_SITE_CONCURRENCY = 4

# ValueError: a malformed event; retrying can't fix it. Everything else (S3,
# ClamAV or Spark unavailable) is retried with backoff.
SITE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=10,
    non_retryable_error_types=["ValueError"],
)


@workflow.defn(name="EtlBatchWorkflow")
class EtlBatchWorkflow:
    @workflow.run
    async def run(self, batch: dict) -> dict:
        events: list[dict] = batch["events"]
        concurrency = int(batch.get("site_concurrency", DEFAULT_SITE_CONCURRENCY))
        limit = asyncio.Semaphore(max(1, concurrency))

        async def site(event: dict) -> dict:
            async with limit:
                return await workflow.execute_activity(
                    "run_site_pipeline",
                    event,
                    start_to_close_timeout=timedelta(hours=2),
                    retry_policy=SITE_RETRY,
                )

        results = await asyncio.gather(*(site(event) for event in events), return_exceptions=True)
        failed = [
            f"{event['target_domain']} (run {event['crawl_run_id']}): {result}"
            for event, result in zip(events, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failed:
            # The batch's Kafka offsets stay uncommitted, so Airflow re-runs it;
            # sites that already succeeded are skipped then (see run_site_pipeline).
            raise ApplicationError(
                f"{len(failed)} of {len(events)} site(s) failed: " + "; ".join(failed),
                non_retryable=True,
            )
        return {"sites": len(events), "summaries": list(results)}
