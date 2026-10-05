"""ETL Temporal worker: runs EtlBatchWorkflow and its run_site_pipeline
activities on the ``etl-task-queue`` task queue, as the Spark driver.

    TEMPORAL_ADDRESS=temporal:7233 SPARK_MASTER=spark://spark-master:7077 python worker.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from concurrent.futures import ThreadPoolExecutor

from etl_activities import run_site_pipeline, stop_session
from etl_workflows import DEFAULT_SITE_CONCURRENCY, TASK_QUEUE, EtlBatchWorkflow
from temporalio.client import Client
from temporalio.worker import Worker


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    concurrency = int(os.environ.get("ETL_SITE_CONCURRENCY", DEFAULT_SITE_CONCURRENCY))
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    # Activities are synchronous (Spark calls block), so they run in threads; one
    # thread per site that may run at once.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[EtlBatchWorkflow],
            activities=[run_site_pipeline],
            activity_executor=pool,
            max_concurrent_activities=concurrency,
        )
        logging.info("ETL worker on task queue %s (%d site(s) at once)", TASK_QUEUE, concurrency)
        async with worker:
            await stop.wait()
    stop_session()


if __name__ == "__main__":
    asyncio.run(main())
