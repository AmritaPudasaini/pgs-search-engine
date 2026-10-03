// Package metrics defines the Prometheus metrics this crawler exposes for
// live operational visibility during a run: pages/sec, error rate, and
// 429-rate-per-host are all derivable from these via Prometheus's rate()
// function -- no separate "pages per second" gauge is needed, that's what
// rate(crawler_pages_fetched_total[1m]) already gives you.
//
// These are activity-level (fetch) metrics, distinct from the crawl_runs
// validation summary (internal/storage.RunRecorder): that's a post-hoc/
// polled per-run health record queried after or during a run via the API;
// this is real-time, scrape-based, and survives across runs/workers for a
// dashboard or alert rule, which a database row polled per-run can't give
// you (e.g. "429 rate spiked in the last 5 minutes").
//
// cmd/worker/main.go serves these on promhttp.Handler() in a background
// goroutine, logging (not exiting) on a bind failure -- verified live
// (2026-09-29, Person 5 checklist item 6): two worker processes started
// against the same --metrics-address, real temporal server, real ports.
// The second logged "metrics server stopped: listen tcp :19199: bind:
// address already in use" and continued straight into connecting to
// Temporal and running normally; the first process's /metrics endpoint
// kept serving scrapes throughout, unaffected. No code change needed --
// the existing goroutine + log.Printf (not log.Fatalf) already does this
// correctly.
package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Outcome label values for PagesFetched. "success" is the only outcome
// that means a Document was actually parsed and returned to the workflow
// for possible writing -- the rest are the different ways a fetch didn't
// reach that point.
const (
	OutcomeSuccess        = "success"
	OutcomeClientError    = "client_error"     // non-2xx, non-429 status
	OutcomeServerError    = "server_error"     // 5xx
	OutcomeRateLimited    = "rate_limited"     // 429
	OutcomeNetworkError   = "network_error"    // transport-level failure (DNS, timeout, connection refused, ...)
	OutcomeParseError     = "parse_error"      // fetched fine, HTML parsing failed
	OutcomeSkippedRobots  = "skipped_robots"   // robots.txt disallowed -- never fetched
	OutcomeSkippedNonHTML = "skipped_non_html" // fetched, but Content-Type wasn't HTML
)

var (
	// PagesFetched counts every ProcessPage attempt, by outcome. Rate of
	// this (all outcomes) is pages/sec; rate of the error-ish outcomes
	// over rate of all outcomes is error rate.
	PagesFetched = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "crawler_pages_fetched_total",
		Help: "Total ProcessPage attempts, labeled by outcome.",
	}, []string{"outcome"})

	// FetchDuration observes how long the underlying HTTP fetch took, for
	// requests that actually reached a server (excludes OutcomeSkippedRobots
	// and OutcomeNetworkError, which never got a response to time).
	FetchDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "crawler_fetch_duration_seconds",
		Help:    "HTTP fetch duration in seconds, for requests that received a response.",
		Buckets: prometheus.DefBuckets,
	})

	// RateLimited counts 429 responses specifically, broken down by host --
	// the "429 rate per host" the crawler needs to notice a specific site
	// throttling it, which the all-outcomes-together PagesFetched counter
	// can't distinguish on its own.
	RateLimited = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "crawler_rate_limited_total",
		Help: "Total 429 responses received, labeled by host.",
	}, []string{"host"})

	// S3PutTotal counts PutObject calls S3-backed storage makes, by
	// operation ("document", "latest", "manifest" -- see
	// internal/storage/s3_writer.go and s3_run_recorder.go for what each
	// key scheme means) and outcome ("success" or "error", the latter
	// already having exhausted the AWS SDK's own retry/backoff -- see
	// WithS3MaxRetries). Not yet incremented anywhere: adding the
	// definition is Person 5 checklist item 5; wiring the actual Inc()
	// calls into internal/storage's S3Writer/S3RunRecorder (Person 4's
	// files) is follow-up work, left for whoever integrates
	// --storage=s3 into cmd/worker, so as not to touch Person 4's files
	// again beyond the S3RunManifest export item 1 already needed.
	S3PutTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "crawler_s3_put_total",
		Help: "Total S3 PutObject calls, labeled by operation and outcome.",
	}, []string{"operation", "outcome"})

	// S3ThrottledTotal counts PutObject/GetObject/HeadObject/ListObjectsV2
	// calls that failed specifically due to S3 throttling (as opposed to
	// any other error), labeled by operation -- distinct from S3PutTotal's
	// generic "error" outcome so a throttling spike (which usually means
	// "raise WithS3MaxRetries or reduce concurrency", an operational
	// response) isn't buried inside every other kind of S3 failure (which
	// usually means "something is actually broken", a different response).
	// Same not-yet-wired status as S3PutTotal above.
	S3ThrottledTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "crawler_s3_throttled_total",
		Help: "Total S3 API calls that failed due to throttling, labeled by operation.",
	}, []string{"operation"})
)
