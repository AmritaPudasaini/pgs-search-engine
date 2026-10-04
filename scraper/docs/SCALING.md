# Scaling the crawl

## Default: identical replicas

`make scale SCALE=N` runs N identical workers on one task queue
(`scraper-task-queue`). Temporal gives each fetch to whichever worker is
free. Simple and fast to scale, but a host's fetches spread over all
replicas, so per-host politeness (rate limit, `Crawl-delay`, robots cache,
DNS cache) is enforced per process: with N workers a host can see up to N
times the per-worker rate.

## Host sharding: one worker owns each domain

Set `--task-queue-shards=N` (env `TASK_QUEUE_SHARDS`) on the scraper client
and on the workers. Each host is hashed (FNV-1a) to one of N shard queues,
`scraper-task-queue-shard-<i>`; fetch activities (`ProcessPage`,
`DiscoverSitemapURLs`) for that host only run on workers polling that shard.
Workflow tasks, storage writes and run bookkeeping stay on the shared queue.

Worker flags:

| Flag | Meaning |
| --- | --- |
| `--task-queue-shards` | total shards (1 = off) |
| `--shard-index` | shard this worker polls; `-1` = all shards |
| `--shard-from-hostname` | take the shard from the hostname's trailing ordinal (`worker-sharded-3` -> 3) |

Local (from the repository root): `docker compose --profile scraper-sharded up -d`
starts three shard workers (`scraper-worker-shard-{0,1,2}`),
then crawl with `--task-queue-shards=3`. Kubernetes: the `scraper-sharded` component in the repository's `k8/`
(StatefulSet, one pod per shard).

Notes:
- A shard is a hash bucket, not a single domain. Use as many shards as you
  want containers; N=number of domains would mean one container per domain,
  which is rarely worth it.
- Every shard queue needs a live worker, or fetches for its hosts wait. If a
  shard worker dies, Temporal holds its tasks until a replacement starts.
- Resizing N re-hashes hosts to different shards.
