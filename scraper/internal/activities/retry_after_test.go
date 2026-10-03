package activities

import (
	"testing"
	"time"
)

func TestParseRetryAfter(t *testing.T) {
	future := time.Now().Add(90 * time.Second).UTC().Format("Mon, 02 Jan 2006 15:04:05 GMT")
	past := time.Now().Add(-time.Hour).UTC().Format("Mon, 02 Jan 2006 15:04:05 GMT")
	far := time.Now().Add(24 * time.Hour).UTC().Format("Mon, 02 Jan 2006 15:04:05 GMT")

	cases := []struct {
		name   string
		header string
		min    time.Duration
		max    time.Duration
	}{
		{"absent header uses default", "", defaultRetryAfter, defaultRetryAfter},
		{"delay in seconds", "45", 45 * time.Second, 45 * time.Second},
		{"seconds with surrounding space", " 10 ", 10 * time.Second, 10 * time.Second},
		{"zero seconds uses default", "0", defaultRetryAfter, defaultRetryAfter},
		{"negative seconds uses default", "-5", defaultRetryAfter, defaultRetryAfter},
		{"seconds above cap are clamped", "86400", maxRetryAfter, maxRetryAfter},
		{"unparsable uses default", "soon", defaultRetryAfter, defaultRetryAfter},
		{"HTTP-date in the future", future, 80 * time.Second, 90 * time.Second},
		{"HTTP-date in the past uses default", past, defaultRetryAfter, defaultRetryAfter},
		{"HTTP-date beyond cap is clamped", far, maxRetryAfter, maxRetryAfter},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := parseRetryAfter(c.header)
			if got < c.min || got > c.max {
				t.Errorf("parseRetryAfter(%q) = %v, want between %v and %v", c.header, got, c.min, c.max)
			}
		})
	}
}
