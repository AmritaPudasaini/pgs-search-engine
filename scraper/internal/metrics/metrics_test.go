package metrics

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

// reset clears all label combinations between tests so assertions don't
// see counts left over from a previous test in this package (these are
// package-level global metrics, shared for the lifetime of the process).
func reset() {
	PagesFetched.Reset()
	RateLimited.Reset()
	S3PutTotal.Reset()
	S3ThrottledTotal.Reset()
}

func TestPagesFetched_IncrementsPerOutcome(t *testing.T) {
	reset()

	PagesFetched.WithLabelValues(OutcomeSuccess).Inc()
	PagesFetched.WithLabelValues(OutcomeSuccess).Inc()
	PagesFetched.WithLabelValues(OutcomeServerError).Inc()

	if got := testutil.ToFloat64(PagesFetched.WithLabelValues(OutcomeSuccess)); got != 2 {
		t.Errorf("success count = %v, want 2", got)
	}
	if got := testutil.ToFloat64(PagesFetched.WithLabelValues(OutcomeServerError)); got != 1 {
		t.Errorf("server_error count = %v, want 1", got)
	}
	if got := testutil.ToFloat64(PagesFetched.WithLabelValues(OutcomeRateLimited)); got != 0 {
		t.Errorf("rate_limited count = %v, want 0 (never incremented)", got)
	}
}

func TestRateLimited_TracksPerHost(t *testing.T) {
	reset()

	RateLimited.WithLabelValues("a.example.com").Inc()
	RateLimited.WithLabelValues("a.example.com").Inc()
	RateLimited.WithLabelValues("b.example.com").Inc()

	if got := testutil.ToFloat64(RateLimited.WithLabelValues("a.example.com")); got != 2 {
		t.Errorf("a.example.com count = %v, want 2", got)
	}
	if got := testutil.ToFloat64(RateLimited.WithLabelValues("b.example.com")); got != 1 {
		t.Errorf("b.example.com count = %v, want 1", got)
	}
}

func TestS3PutTotal_TracksOperationAndOutcome(t *testing.T) {
	reset()

	S3PutTotal.WithLabelValues("document", "success").Inc()
	S3PutTotal.WithLabelValues("document", "success").Inc()
	S3PutTotal.WithLabelValues("document", "error").Inc()
	S3PutTotal.WithLabelValues("manifest", "success").Inc()

	if got := testutil.ToFloat64(S3PutTotal.WithLabelValues("document", "success")); got != 2 {
		t.Errorf("document/success count = %v, want 2", got)
	}
	if got := testutil.ToFloat64(S3PutTotal.WithLabelValues("document", "error")); got != 1 {
		t.Errorf("document/error count = %v, want 1", got)
	}
	if got := testutil.ToFloat64(S3PutTotal.WithLabelValues("manifest", "success")); got != 1 {
		t.Errorf("manifest/success count = %v, want 1", got)
	}
	if got := testutil.ToFloat64(S3PutTotal.WithLabelValues("latest", "success")); got != 0 {
		t.Errorf("latest/success count = %v, want 0 (never incremented)", got)
	}
}

func TestS3ThrottledTotal_TracksPerOperation(t *testing.T) {
	reset()

	S3ThrottledTotal.WithLabelValues("put").Inc()
	S3ThrottledTotal.WithLabelValues("put").Inc()
	S3ThrottledTotal.WithLabelValues("list").Inc()

	if got := testutil.ToFloat64(S3ThrottledTotal.WithLabelValues("put")); got != 2 {
		t.Errorf("put count = %v, want 2", got)
	}
	if got := testutil.ToFloat64(S3ThrottledTotal.WithLabelValues("list")); got != 1 {
		t.Errorf("list count = %v, want 1", got)
	}
}

// TestPromhttpHandler_ServesRegisteredMetrics proves the exact wiring
// cmd/worker/main.go uses (promhttp.Handler() over the default registry
// promauto registers these metrics against) actually serves them in
// Prometheus text format -- catching, e.g., a metric that was defined but
// never registered, or a name typo that would silently produce an empty
// scrape.
func TestPromhttpHandler_ServesRegisteredMetrics(t *testing.T) {
	reset()
	PagesFetched.WithLabelValues(OutcomeSuccess).Inc()
	RateLimited.WithLabelValues("example.com").Inc()
	S3PutTotal.WithLabelValues("document", "success").Inc()
	S3ThrottledTotal.WithLabelValues("put").Inc()

	srv := httptest.NewServer(promhttp.Handler())
	defer srv.Close()

	resp, err := http.Get(srv.URL)
	if err != nil {
		t.Fatalf("GET /metrics: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}

	for _, want := range []string{
		`crawler_pages_fetched_total{outcome="success"} 1`,
		`crawler_rate_limited_total{host="example.com"} 1`,
		`crawler_s3_put_total{operation="document",outcome="success"} 1`,
		`crawler_s3_throttled_total{operation="put"} 1`,
	} {
		if !strings.Contains(string(body), want) {
			t.Errorf("scrape output missing %q\nfull output:\n%s", want, body)
		}
	}
}
