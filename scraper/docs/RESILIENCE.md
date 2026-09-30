# Resilience: verified crash-recovery behavior

This documents an actual test run (not a hypothetical) proving the worker
can crash mid-crawl without losing or duplicating work, thanks to Temporal.

## Setup

```bash
temporal server start-dev &
./bin/worker --output=data/output/documents.ndjson &
./bin/scraper --seeds=https://go.dev --max-depth=2 --max-pages=60 --concurrency=6 --wait=false
```

## Steps and results

1. Crawl started against `https://go.dev`, depth 2, budget 60 pages.
2. After ~2s (11 documents written), the worker process was killed with
   `kill -9` — a hard crash, not a graceful shutdown (SIGTERM is handled
   gracefully by `worker.InterruptCh()`; SIGKILL cannot be caught, which is
   the point of the test).
3. `temporal workflow describe` showed the workflow still alive with
   `Pending Activities: 6` — Temporal knew work was outstanding but had no
   worker to run it. This is expected: without `activity.RecordHeartbeat`,
   Temporal can't distinguish "worker is slow" from "worker is dead" until
   `StartToCloseTimeout` (30s) elapses.
4. The worker was restarted (fresh process, same `--output` path).
5. Once the timed-out activities' `StartToCloseTimeout` expired, Temporal
   rescheduled them onto the newly-connected worker automatically — no
   manual intervention, no re-running the client.
6. The workflow's in-memory frontier (queue + seen-set) was intact,
   reconstructed by Temporal replaying the workflow's event history — the
   crawl did not restart from the seed URL, it resumed exactly where it had
   left off, continuing through several Continue-As-New segments.
7. Crawl reached `Status: COMPLETED`. Final result:
   `{"Failed":3,"Fetched":60,"Skipped":0,"Succeeded":57}`.
8. Output file: **57 lines, 57 unique URLs, 0 duplicates.**

## What this proves

- A worker crash mid-fetch does not lose already-completed pages: the
  first 11 documents written before the crash were still on disk after
  restart (this required fixing `storage.NewNDJSONWriter` to open in
  **append** mode — it originally used `os.Create`, which truncates on
  every restart and would have destroyed the pre-crash output; see
  `internal/storage/writer.go`).
- A worker crash does not duplicate work: activities in flight at the time
  of the crash were retried exactly once each after the timeout window, and
  `WriteDocument`'s content-hash dedupe (`internal/activities/activities.go`)
  meant even a retried write wouldn't double-append.
- The crawl's frontier state (what's left to crawl, what's already been
  seen) survives a process crash without any external persistence code in
  this repo — it comes entirely from Temporal's workflow history replay.

## Known gap this test surfaced

Crash detection took up to 30s (bounded by `StartToCloseTimeout`) because
activities don't heartbeat. For faster failover, add `HeartbeatTimeout` to
the `ActivityOptions` in `internal/workflows/crawl_workflow.go` and call
`activity.RecordHeartbeat(ctx, nil)` periodically inside long-running
activities (mainly relevant if per-page fetch timeouts are increased well
past a few seconds).
