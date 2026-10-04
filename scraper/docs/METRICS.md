# Metrics: example Prometheus/Grafana queries

`internal/metrics` (see that package's doc comment for the full design
reasoning) defines what `cmd/worker` serves on `--metrics-address`
(default `:9090`, `GET /metrics`). This doc is the query reference the
metric definitions themselves point at -- Person 5 checklist item 7.

Every query below assumes Prometheus is scraping each worker replica
(the root `docker-compose.yml`'s `scraper-worker` service, or each pod in the Kubernetes
Deployment) on that port -- see the repository's `k8/` manifests (`scraper-worker-metrics` Service),
or point a local Prometheus at `http://localhost:9090/metrics` directly
for a single `make run` worker.

## Pages/sec

```promql
sum(rate(crawler_pages_fetched_total[1m]))
```

All outcomes combined -- the overall fetch throughput. Break down by
outcome to see the mix:

```promql
sum by (outcome) (rate(crawler_pages_fetched_total[1m]))
```

## Error rate

"Error-ish" outcomes (`client_error`, `server_error`, `rate_limited`,
`network_error`, `parse_error`) as a fraction of all attempts -- `success`
and the two `skipped_*` outcomes (robots-disallowed, non-HTML) are
expected, not errors, so they're excluded from the numerator but still
count in the denominator:

```promql
sum(rate(crawler_pages_fetched_total{outcome=~"client_error|server_error|rate_limited|network_error|parse_error"}[5m]))
/
sum(rate(crawler_pages_fetched_total[5m]))
```

## Fetch latency

`crawler_fetch_duration_seconds` is a histogram (`prometheus.DefBuckets`),
so use `histogram_quantile`, not a raw average, to see the shape rather
than let a handful of slow outliers dominate a mean:

```promql
histogram_quantile(0.95, sum(rate(crawler_fetch_duration_seconds_bucket[5m])) by (le))
```

## 429 rate by host

The specific signal for "which site is throttling us right now" --
`crawler_pages_fetched_total{outcome="rate_limited"}` alone can't break
this down by host, which is exactly why `RateLimited` exists as its own
host-labeled counter:

```promql
topk(10, sum by (host) (rate(crawler_rate_limited_total[5m])))
```

A Grafana alert rule on this (e.g. `> 0.5` for a single host sustained
over 5m) is a reasonable trigger to lower that host's crawl priority or
add/raise `--max-concurrent-per-host` friction for it specifically.

## S3 throttle rate

**Not yet emitting data**: `crawler_s3_put_total` and
`crawler_s3_throttled_total` (Person 5 item 5) are defined but not wired
into any `Inc()` call site yet -- see that item's commit message for why.
These queries are the intended shape once they are:

```promql
# S3 throttle rate by operation
sum by (operation) (rate(crawler_s3_throttled_total[5m]))

# S3 write error rate (excludes throttling, which has its own counter/query above)
sum(rate(crawler_s3_put_total{outcome="error"}[5m]))
/
sum(rate(crawler_s3_put_total[5m]))
```

A sustained non-zero S3 throttle rate is the operational signal to raise
`WithS3MaxRetries`/back off write concurrency (see
`internal/storage/s3_writer.go`), the S3-storage equivalent of the 429-by-
host alert above.

## A note on what these can't tell you

These are real-time, scrape-based, and reset when a worker process
restarts (a `CounterVec`'s underlying values live in-process, not
persisted) -- they answer "what's happening right now / over the last
few minutes across the fleet." They cannot answer "how did crawl run
#1234 go" after the fact once that worker's process has cycled: that's
what `GET /api/v1/crawl-runs/{id}` (the `crawl_runs`/`S3RunManifest`
validation summary) is for instead. See `internal/metrics`'s package doc
comment for the same distinction from the storage side.
