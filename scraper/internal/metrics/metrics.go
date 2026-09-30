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
)
