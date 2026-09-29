# search-engine-scraper

A scalable, fault-tolerant web crawler built in Go, orchestrated by
[Temporal](https://temporal.io) for durable execution. Scope is
intentionally narrow: crawl the web and produce clean, structured ETL
records (NDJSON). Indexing, search, backend, and UI are out of scope for
this repo.

**New here? See [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) for
the fastest path to a running crawl** (`make run`, then `make crawl`).
The rest of this README covers how it's built and why.

## Why Temporal

A crawler runs for a long time, talks to unreliable third-party servers,
and its worker process can die mid-run (deploy, OOM, crash). Handling that
correctly by hand — retries with backoff, "did this page already get
written?", resuming a queue after a restart without losing or duplicating
work — is exactly what Temporal is for:

- **Automatic retries with backoff** on transient failures (network errors,
  5xx responses), configured once as a policy, not hand-rolled per call site.
- **Crash recovery for free.** If the worker process is killed, Temporal
  replays the workflow's history to reconstruct its in-memory frontier state
  and re-dispatches only the activities that hadn't finished — nothing
  already completed gets lost or silently re-run. This was verified by
  killing (`kill -9`) a worker mid-crawl and confirming it resumed to a
  complete, duplicate-free result (see `docs/RESILIENCE.md`).
- **Bounded history via Continue-As-New**, so a workflow can crawl
  arbitrarily many pages without its event history growing unbounded.
- **Real concurrency + horizontal scale**, via goroutines within a worker
  process and by running multiple worker processes against the same task
  queue (see "Scaling" below).

## Project layout

Standard Go layout — packages by responsibility, no framework, no modular
monolith:

```
cmd/scraper/          Temporal client: starts a crawl workflow, optionally waits on it
cmd/worker/            Temporal worker: registers & executes the workflow + activities
internal/model/         Document: the ETL record shape written to NDJSON
internal/fetcher/        Polite HTTP client (timeouts, UA, body size cap)
internal/robots/          robots.txt fetch/parse/cache, crawl-delay
internal/parser/           HTML -> title/text/links extraction (real tokenizer, not regex)
internal/normalize/         URL canonicalization + relative-link resolution
internal/storage/            Output writer: NDJSON file or Postgres, same Writer interface
internal/db/                   sqlc-generated Postgres queries (from internal/db/queries.sql)
internal/seeds/                  Seed-list file parser ([category] sections -> Seed{URL,Category,Priority})
internal/envflag/                  CLI flags that also read from env vars (for Docker/Kubernetes config)
internal/activities/                Temporal Activities: ProcessPage (fetch+parse), WriteDocument
internal/workflows/                  Temporal Workflow: CrawlWorkflow (frontier, fan-out, retries)
migrations/                            SQL migrations (golang-migrate format) for the documents table
configs/seeds.example.txt                Example multi-category seed list
data/output/                               Default NDJSON output location (gitignored)
Dockerfile.worker, Dockerfile.scraper        Multi-stage builds -> distroless images
docker-compose.yml                             Postgres + Temporal + worker, one command to run it all
k8s/                                             Kubernetes manifests (Deployment, HPA, StatefulSet, Jobs)
```

`internal/workflows` is the only package that knows about the crawl as a
whole; it calls into `internal/activities`, which in turn wraps
`fetcher`/`robots`/`parser`/`storage`. Everything else is a plain,
independently-testable package.

## How it works

```
cmd/scraper (client)
    |  ExecuteWorkflow(CrawlWorkflow, seeds, limits)
    v
Temporal Server  <-- durably persists every step, retries, and timer
    |
    v
cmd/worker (one or many processes, any machine)
    |
    +-- CrawlWorkflow: owns the frontier (queue + seen-set) as workflow
    |     state; fans out up to --concurrency ProcessPage activities at
    |     once; Continue-As-New every 50 pages to bound history size.
    |
    +-- ProcessPage activity: robots.txt check + crawl-delay + fetch +
    |     parse. Transient errors (network, 5xx) return a Go error so
    |     Temporal retries with backoff; permanent outcomes (404, non-HTML,
    |     robots-disallowed) return a normal result so the workflow moves on
    |     instead of retrying forever.
    |
    +-- WriteDocument activity: appends one NDJSON line, deduped by
          content-hash so an activity retry can't double-write.
```

## Quick start (Docker, one command)

```bash
make run
```

That's `docker compose up --build`: it builds the worker and scraper
images, starts Postgres, runs the `documents` table migration, starts
Temporal (server + Web UI at http://localhost:8233), and starts one worker
replica. Once it's up, start a crawl from another terminal:

```bash
make crawl SEEDS=https://example.com
# or: make crawl SEEDS_FILE=configs/seeds.example.txt
```

Scale to more worker replicas — each one is an independent Temporal worker
on the same task queue, no coordination code needed:

```bash
make scale SCALE=5
```

`make down` stops everything and wipes the Postgres volume. See
`make help` for every target (migrations, sqlc, local dev DB, Kubernetes).

## Quick start (running locally, no Docker)

Requires a Temporal server. For local dev, install the Temporal CLI (bundles
a dev server) and start it in one terminal:

```bash
brew install temporal
temporal server start-dev
```

In another terminal, build and run a worker (this is what actually fetches
pages — run one or more of these). By default it writes NDJSON to a local
file; pass `--storage=postgres --database-url=...` to use Postgres instead
(see "Database" below):

```bash
go build -o bin/worker ./cmd/worker
./bin/worker --output=data/output/documents.ndjson
```

In a third terminal, start a crawl. Either give seeds directly:

```bash
go build -o bin/scraper ./cmd/scraper
./bin/scraper --seeds=https://example.com --max-depth=2 --max-pages=100 --concurrency=8
```

...or, to crawl many unrelated sites/categories in one run — the way a real
search engine crawler is seeded, rather than crawling one site at a time —
point it at a seed-list file instead:

```bash
./bin/scraper --seeds-file=configs/seeds.example.txt --same-host-only=false \
  --max-depth=3 --max-pages=2000 --max-pages-per-domain=200 --concurrency=16
```

`--max-pages-per-domain` keeps any one fast-responding site from eating the
whole `--max-pages` budget before slower sites get a turn — see "Known
tradeoffs" below.

A seed-list file groups seeds into categories (see `configs/seeds.example.txt`):

```
[news]
https://example-news-site.com

[tech]
https://example-tech-site.com
https://another-tech-site.com
```

Every crawled `Document` gets tagged with the `category` of the seed it
came from (inherited down the link graph), so you can filter/split results
by topic afterward even though it was all one crawl.

**Priority** controls crawl order, not just grouping. A `[category]`
header may carry a default priority (`[tech 10]`), and a seed line may
override it just for that URL (`https://example.com 20`) — higher values
are fetched before lower ones:

```
[tech 10]
https://example-tech-site.com
https://another-tech-site.com 20

[news]
https://example-news-site.com
```

Priority is inherited down the link graph the same way category is: every
link discovered from a seed keeps that seed's priority, so a high-priority
seed's whole branch is favored over a low-priority one's, not just its
front page. Within whatever's currently startable (not domain-capped, not
waiting on a `--max-concurrent-per-host` slot), the workflow always starts
the highest-priority queued item next; equal priorities fall back to FIFO
order.

**`--same-host-only`** is the "one site" vs. "the whole web" switch:
- `true` (default) — each seed's discovered links stay confined to that
  seed's own host. Good for focused site crawls.
- `false` — the crawler follows outbound links wherever they lead, crossing
  onto any domain it discovers, exactly like a real search-engine crawler.
  The only things bounding it are `--max-depth` and `--max-pages` (and
  robots.txt on every host it touches) — there's no seed list to maintain
  once you set it loose, it discovers new sites on its own.

The client blocks by default and prints final stats. Pass `--wait=false` to
fire-and-forget and inspect progress via:

```bash
temporal workflow describe --workflow-id <the printed workflow-id>
temporal workflow show --workflow-id <the printed workflow-id>
```

or the Web UI Temporal's dev server prints a URL for on startup.

Output is newline-delimited JSON, one `model.Document` per line:

```json
{
  "url": "https://example.com",
  "normalized_url": "https://example.com/",
  "title": "Example Domain",
  "text": "Example Domain This domain is for use in documentation examples...",
  "links": ["https://iana.org/domains/example"],
  "depth": 0,
  "status_code": 200,
  "content_type": "text/html",
  "content_hash": "ff67a9...",
  "category": "tech",
  "fetched_at": "2026-09-01T08:52:39Z",
  "fetch_duration_ms": 16
}
```

### `cmd/scraper` flags (start a crawl)

Unlike `cmd/worker` (below), **not every flag here supports an
environment-variable override** -- only `--temporal-address`,
`--namespace`, `--seeds-file`, and `--country-filter` are registered via
`internal/envflag` (same upper-case/dashes-to-underscores derivation as
`cmd/worker`'s); every other flag below is a plain `flag.*` with no env
var equivalent. This is an inconsistency in `cmd/scraper/main.go` itself,
not just undocumented -- found while reviewing `internal/envflag`'s
derivation against this table (`docs/TASK-SPLIT-search-engine-scraper.md`
Person 5 checklist item 8).

| Flag | Default | Meaning |
|---|---|---|
| `--seeds` | | Comma-separated starting URLs (use this OR `--seeds-file`) |
| `--seeds-file` | | Path to a `[category]`-grouped seed-list file (use this OR `--seeds`) |
| `--category` | uncategorized | Category label applied to `--seeds` URLs (ignored with `--seeds-file`) |
| `--priority` | 0 | Crawl priority applied to `--seeds` URLs (higher = crawled first, ignored with `--seeds-file` — set per-URL/per-category priority in the file itself, see below) |
| `--max-depth` | 2 | Max link-hops from a seed |
| `--max-pages` | 100 | Total page budget for the crawl, shared across every seed/category |
| `--concurrency` | 0 (auto) | Max pages one workflow run has in flight at once. `0` auto-scales with seed count: `numSeeds*4`, clamped to `[8,256]` — a bigger seed file requests more parallelism without a manual flag per file size. Pass a positive value to override. |
| `--same-host-only` | true | `true` = stay on each seed's own host; `false` = open crawl, follow links anywhere |
| `--max-pages-per-domain` | 0 | Cap pages fetched from any single host (0 = unlimited); prevents one fast domain crowding out the rest of `--max-pages` |
| `--max-concurrent-per-host` | 0 | Cap concurrent in-flight fetches to any single host (0 = unlimited; `--concurrency` alone governs total in-flight fetches) |
| `--revisit-after` | 0 | Skip (re-)fetching a URL already crawled more recently than this duration (0 = disabled, always fetch; requires `--storage=postgres` on the worker to have any effect) |
| `--country-filter` | NP | ISO 3166-1 alpha-2 country code: only pages detected as this country are written as documents (others are still fetched and followed for links, just not stored); empty = no filter |
| `--workflow-id` | derived | Temporal workflow ID (override to control dedup/re-runs) |
| `--wait` | true | Block until the crawl finishes and print stats |
| `--temporal-address` | localhost:7233 | Temporal frontend address |
| `--namespace` | default | Temporal namespace |

### `cmd/worker` flags (do the actual fetching)

Every flag here can also be set via an environment variable of the same
name (upper-cased, dashes to underscores — e.g. `--database-url` is
`DATABASE_URL`), which is how `docker-compose.yml` and the Kubernetes
manifests configure it without a wrapper script.

| Flag | Env var | Default | Meaning |
|---|---|---|---|
| `--storage` | `STORAGE` | ndjson | `ndjson` (local file), `postgres`, or `kafka` |
| `--output` | `OUTPUT` | data/output/documents.ndjson | NDJSON output path (used when `--storage=ndjson`) |
| `--database-url` | `DATABASE_URL` | | Postgres connection string (required when `--storage=postgres`) |
| `--kafka-brokers` | `KAFKA_BROKERS` | | Comma-separated Kafka broker addresses (required when `--storage=kafka`) |
| `--kafka-topic` | `KAFKA_TOPIC` | crawled-documents | Kafka topic crawled documents are published to (used when `--storage=kafka`) — the hand-off point to the ETL pipeline |
| `--max-concurrent-activities` | `MAX_CONCURRENT_ACTIVITIES` | `NumCPU * 100` | Concurrent activity goroutines in this process |
| `--max-bandwidth-bytes-per-sec` | `MAX_BANDWIDTH_BYTES_PER_SEC` | 0 (unlimited) | Caps this worker process's aggregate download rate in bytes/sec, across every concurrent fetch it's running |
| `--timeout` | `TIMEOUT` | 10s | Per-request HTTP timeout |
| `--user-agent` | `USER_AGENT` | search-engine-scraper | UA string + robots.txt group to obey |
| `--metrics-address` | `METRICS_ADDRESS` | :9090 | Address to serve Prometheus metrics on (`GET /metrics`); empty disables it |
| `--temporal-address` | `TEMPORAL_ADDRESS` | localhost:7233 | Temporal frontend address |
| `--namespace` | `NAMESPACE` | default | Temporal namespace |

## Scaling

Two independent knobs:

1. **Within one worker process**: `--max-concurrent-activities` bounds how
   many `ProcessPage`/`WriteDocument` activities run as concurrent
   goroutines (the Temporal SDK's activity worker pool). It defaults to
   `runtime.NumCPU() * 100` — deliberately aggressive, since fetching is
   I/O-bound (blocked on network round-trips), not CPU-bound, so far more
   fetches can be in flight than there are cores. In a container this
   reads the *container's* CPU count via
   [`go.uber.org/automaxprocs`](https://github.com/uber-go/automaxprocs)
   (imported in `cmd/worker/main.go`), not the host machine's, so raising a
   Kubernetes pod's `resources.limits.cpu` alone raises per-pod concurrency.
2. **Across machines**: run `cmd/worker` multiple times — same
   `--temporal-address`, same task queue — on as many machines/containers/pods
   as you want. Temporal load-balances activity and workflow tasks across
   all of them automatically; no coordination code needed here. This is
   `docker compose up --scale worker=N` (`make scale SCALE=N`) or a
   Kubernetes Deployment's `replicas` / its HorizontalPodAutoscaler
   (`k8s/03-worker.yaml`).

Crawl-wide concurrency is therefore `--concurrency` (per-workflow in-flight
cap, set by the client) bounded by the total activity-execution capacity of
however many worker processes are currently connected. Left at its default
(`0`), `--concurrency` auto-scales with the seed file's size (`numSeeds*4`,
clamped to `[8,256]`), so a bigger seed list automatically asks for more
in-flight fetches without a manual flag per file.

**Bandwidth** is a separate, worker-side cap: `--max-bandwidth-bytes-per-sec`
throttles one worker process's aggregate download rate regardless of how
many fetches it has in flight — set it on capacity-constrained links/hosting
plans so raising `--concurrency` or activity concurrency can't blow past
the network's actual bandwidth budget. It's per-process, so scaling out to
more worker replicas raises the crawl's aggregate bandwidth ceiling
proportionally, same as `--max-concurrent-activities`.

With `--storage=postgres`
that scaling is safe by construction: every replica upserts into the same
table keyed by `normalized_url`, so N workers writing
concurrently can't produce duplicate rows (see "Database" below) — the
NDJSON writer, by contrast, is one file per worker process and isn't
meant to be run with multiple replicas pointed at the same path.

## Database

For a single local run, the NDJSON file (`--storage=ndjson`, the default)
is simplest. For anything with more than one worker replica — Docker
Compose's `--scale`, or a Kubernetes Deployment — use Postgres
(`--storage=postgres --database-url=...`) instead: every replica writes to
the same table, and `WriteDocument` is a real upsert keyed on
`normalized_url` (see `migrations/0009_fix_unique_constraint_and_revisit.up.sql`,
which replaced the original `(normalized_url, content_hash)` constraint —
see that migration's comment for why),
so it's genuinely idempotent under Temporal's at-least-once activity
retries across the whole fleet — not just within one process's lifetime,
which is the most the NDJSON writer's in-memory dedupe could ever offer
(see `internal/storage/postgres.go`'s doc comment).

**Migrations** are plain SQL files in `migrations/`, applied with
[golang-migrate](https://github.com/golang-migrate/migrate):

```bash
make migrate-up            # apply, against APP_DB_URL (defaults to the local dev DB below)
make migrate-down          # roll back one
make migrate-new NAME=x    # scaffold a new migration pair
```

`docker-compose.yml`'s `migrate` service runs `make migrate-up`'s equivalent
automatically before the worker starts. For local (non-Docker) development
against Postgres:

```bash
make devdb-up      # starts a throwaway Postgres container on :5433 and applies migrations
./bin/worker --storage=postgres --database-url="postgres://scraper:scraper@localhost:5433/scraper?sslmode=disable"
make devdb-down     # tear it down
```

**Queries** are hand-written SQL in `internal/db/queries.sql`; running
`make sqlc` (wraps [sqlc](https://sqlc.dev)) regenerates the type-safe Go
client in `internal/db/` from that file plus the schema in `migrations/`.
Re-run it after editing either. Nothing in `internal/db/*.go` is
hand-edited — it's all `// Code generated by sqlc. DO NOT EDIT.`

## ETL hand-off (Kafka)

`--storage=kafka --kafka-brokers=host:9092 --kafka-topic=crawled-documents`
publishes every crawled `model.Document` as a JSON message to that Kafka
topic, keyed by `normalized_url` (see `internal/storage/kafka_writer.go`) --
this is the stream the ETL team consumes instead of polling Postgres or an
NDJSON file. Kafka can also run *alongside* Postgres/NDJSON: pass
`--kafka-brokers` with any other `--storage` value and the worker fans out
to both (`storage.MultiWriter`), so the crawler's own API keeps reading
Postgres while ETL reads the same documents off Kafka in real time.
`docker-compose.yml`'s `kafka` service is a single-node Redpanda broker
(Kafka-API-compatible) for local development.

## Geo-tagging and the Nepal-only filter

Every document carries a best-guess origin `Country` (ISO 3166-1 alpha-2),
resolved by `internal/parser.DetectCountry` from, in priority order: a
JSON-LD `PostalAddress.addressCountry`, `og:locale`'s territory subtag,
the `geo.region` meta tag, `<html lang>`, and finally the page's host
ccTLD (`example.com.np` -> `NP`). This is a heuristic, not a geolocation
service -- a page with none of those signals gets `Country: ""`.

The crawler currently scopes itself to Nepal: `cmd/scraper`'s
`--country-filter` flag defaults to `NP`. A page whose detected country
doesn't match (including an undetected `""`) is still fetched and has its
links followed as normal -- so a global index page can lead the crawl to
in-country pages linked from it -- it's just not written as a Document
(counted under `CountryFiltered` in the crawl's final stats). Pass
`--country-filter=` (empty) for the original unrestricted, whole-web
behavior, or any other ISO code to scope to a different country.

## Docker

`docker-compose.yml` runs the whole stack: Postgres (holding both
Temporal's own persistence and this app's `documents` table, in separate
databases), the `migrate` one-shot job, Temporal server + Web UI, and the
`worker` service. `scraper` is defined but not auto-started (it's a
one-shot client, not a long-running service — see its `profiles: ["tools"]`)
; run it on demand with `make crawl` or `docker compose run --rm scraper ...`.

```bash
make run              # docker compose up --build, foreground
make up                # same, detached
make scale SCALE=5      # docker compose up --scale worker=5
make logs                # follow worker logs
make down                 # stop + wipe volumes
```

`Dockerfile.worker` and `Dockerfile.scraper` are both multi-stage: a
`golang:1.25-alpine` build stage produces a static binary
(`CGO_ENABLED=0`), copied into a `gcr.io/distroless/static-debian12`
runtime stage — no shell, no package manager, just the binary and CA
certificates (needed for the worker's outbound HTTPS crawling). Smaller
image, smaller attack surface than shipping the Go toolchain or a full
distro to production. The builder image tag must stay at or above
`go.mod`'s `go` directive — bump both together if you upgrade Go.

This was verified with an actual `make run` against this repo: all
services came up, a crawl through `docker compose run scraper` landed rows
in Postgres, and scaling to 3 worker replicas (`make scale SCALE=3`) then
running a 60-page crawl showed activities picked up by multiple replicas
with zero duplicate rows in the `documents` table. Two things worth
knowing if you hit them:
- `temporalio/auto-setup`'s `DB` env var must be `postgres12`, not
  `postgresql` (a name that exists in some Temporal docs/versions but not
  this image's driver list).
- The `worker` service has `restart: on-failure`: Compose's
  `depends_on: temporal: condition: service_started` only waits for
  Temporal's *container* to start, not for its gRPC server to finish
  schema setup and start accepting connections, so the worker can lose
  that race on a cold start. The restart policy self-heals it within a
  few seconds rather than needing a wait-for-it script.

## Kubernetes

`k8s/` has plain manifests (no Helm/Kustomize, to keep it readable for a
course project) for everything this repo owns:

| File | What |
|---|---|
| `00-namespace.yaml` | `search-engine-scraper` namespace |
| `01-postgres.yaml` | Postgres `StatefulSet` + headless `Service` + `Secret` with connection info |
| `02-migrate-job.yaml` | One-shot `Job` applying `migrations/*.sql` before the worker starts |
| `03-worker.yaml` | Worker `Deployment` (3 replicas) + `HorizontalPodAutoscaler` (2–10 replicas on 70% CPU) |
| `04-migrations-configmap.yaml` | Generated from `migrations/*.sql` — regenerate with `make k8s-migrations-configmap` after editing a migration |
| `scraper-job.yaml.tmpl` | Template for one-off crawl `Job`s, rendered by `make k8s-crawl` |

**Temporal server itself is not hand-rolled here.** Run it via the
[official Helm chart](https://github.com/temporalio/helm-charts)
(`helm install temporal temporalio/temporal -n temporal`) — that's the
maintained, correct way to run Temporal in Kubernetes; reinventing its
manifests would be a lot of brittle YAML for no benefit over the chart.
`k8s/03-worker.yaml`'s `TEMPORAL_ADDRESS` assumes that chart's default
service name/namespace — adjust it (or point at Temporal Cloud) if yours
differs.

```bash
# build & push images to your own registry first, then update the `image:`
# fields in k8s/03-worker.yaml and scraper-job.yaml.tmpl to match
make k8s-apply                              # deploy everything this repo owns
make k8s-crawl SEEDS=https://example.com     # one-off crawl Job
make k8s-delete                               # tear down
```

Scaling in the cluster is the `worker` Deployment's `replicas` (static) or
its `HorizontalPodAutoscaler` (automatic, based on CPU) — both act on the
same knob described in "Scaling" above: more pods, each with its own
`NumCPU * 100` in-process concurrency bounded by its container's CPU limit.

## Known tradeoffs (by design, for this project's scope)

- **NDJSON output dedupe (`--storage=ndjson`) is best-effort across a
  crash**, deduped by content-hash within one worker process's in-memory
  lifetime; a crash between "activity succeeded" and "Temporal recorded
  that" can in rare cases produce one duplicate line after a restart. Use
  `--storage=postgres` instead if this matters — its dedupe is a real
  database constraint, safe across restarts and across every replica in a
  scaled-out deployment (see "Database" above).
- **Crash detection latency is bounded by `StartToCloseTimeout` (30s)**
  because activities don't call `activity.RecordHeartbeat`. A worker that
  dies mid-fetch means that one page waits up to 30s before Temporal
  reschedules it elsewhere — acceptable for crawl throughput at this scale;
  heartbeating would tighten that window.
- **`--max-pages` is one shared, FIFO-ordered budget across every seed and
  category in a run.** Without `--max-pages-per-domain`, whichever seed's
  pages happen to respond fastest can consume a disproportionate share of
  the budget before slower sites get much of a look-in (this is exactly
  what happened running the example seeds file before this flag existed:
  MDN dominated over go.dev and Wikipedia purely because it answered
  first). Set `--max-pages-per-domain` on multi-seed/open crawls to cap
  any single host's share; URLs discovered beyond a host's cap are dropped
  permanently and counted in `Stats.DomainCapped`, not requeued elsewhere.
- **robots.txt politeness is per-host but not rate-limited beyond
  `Crawl-delay`.** An open (`--same-host-only=false`) crawl can end up
  issuing several concurrent requests to different pages on the *same*
  newly-discovered host at once if `--concurrency` is high and the crawl
  happens to enqueue several of that host's links back-to-back; there's no
  global per-host concurrency cap beyond what `Crawl-delay` enforces.

## Testing

```bash
go test ./...
go vet ./...
gofmt -l .
```

Unit tests cover `internal/normalize` (URL canonicalization/resolution) and
`internal/robots` (robots.txt group parsing, longest-match rules). The
Temporal workflow/activity logic was verified by hand against a live
Temporal dev server, including a `kill -9` mid-crawl to confirm recovery —
see `docs/RESILIENCE.md` for the exact steps and results.
