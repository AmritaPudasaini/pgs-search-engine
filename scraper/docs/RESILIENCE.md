# Resilience: verified crash-recovery behavior

This documents an actual test run (not a hypothetical) proving the worker
can crash mid-crawl without losing or duplicating work, thanks to Temporal.

Re-verified 2026-09-29 against the current Temporal-based crawler (Person 2
checklist item 7 of `docs/TASK-SPLIT-search-engine-scraper.md`) using
`temporal server start-dev`, a locally built worker/scraper, and a real
crawl of `https://go.dev`. The crash-recovery mechanism below is unchanged
from the original run; the command line needed one correction (see
"Drift found on re-verification").

## Setup

```bash
temporal server start-dev &
./bin/worker --output=data/output/documents.ndjson &
./bin/scraper --seeds=https://go.dev --max-depth=2 --max-pages=60 --concurrency=6 --wait=false --country-filter=""
```

`--country-filter=""` is required now and wasn't when this doc was
originally written -- see "Drift found on re-verification" below.

## Steps and results

1. Crawl started against `https://go.dev`, depth 2, budget 60 pages.
2. After ~2s (26 documents written on re-verification; 11 in the original
   run -- this varies with network conditions, not a meaningful
   discrepancy), the worker process was killed with `kill -9` — a hard
   crash, not a graceful shutdown (SIGTERM is handled gracefully by
   `worker.InterruptCh()`; SIGKILL cannot be caught, which is the point of
   the test).
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
7. Crawl reached `Status: COMPLETED`. Final result (original run):
   `{"Failed":3,"Fetched":60,"Skipped":0,"Succeeded":57}`; re-verification
   run: `{"Failed":3,"Fetched":60,"Skipped":5,"Succeeded":52}` — same
   Fetched budget, same Failed count, small Succeeded/Skipped variance from
   go.dev's live content having changed since the original run.
8. Output file, re-verification run: **52 lines, 52 unique URLs, 0
   duplicates** (the pre-crash 26 documents were confirmed present
   immediately after the `kill -9`, before the worker was ever restarted).

## Drift found on re-verification

`./cmd/scraper`'s `--country-filter` flag now defaults to `"NP"` (per its
`-help` text). Running this doc's original command line verbatim (no
`--country-filter` flag) against `https://go.dev` -- a site with no Nepal
geo signals -- filters out every single fetched page as
`CountryFiltered`, producing **zero** output documents:
`{"CountryFiltered":59,"DomainCapped":0,"Failed":1,"Fetched":60,"Skipped":0,"Succeeded":0}`.
This doesn't affect the crash-recovery mechanism itself (Temporal's replay
and activity rescheduling are unaffected by CountryFilter, which only
gates whether a successfully parsed page gets written), but it means the
exact command line originally documented here no longer reproduces this
doc's claimed 57-document output on an unrelated-country site. Updated the
command above to pass `--country-filter=""` explicitly.

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
