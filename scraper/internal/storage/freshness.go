package storage

import (
	"context"
	"time"
)

// FreshnessChecker implements the revisit/freshness policy: given a batch
// of candidate URLs about to be added to the crawl frontier, it reports
// which ones already have a document on file recent enough not to bother
// re-fetching. This is what lets a repeated crawl (e.g. a nightly run
// against the same seeds) skip pages that haven't had a chance to change
// yet, rather than blindly re-fetching everything every time or never
// re-fetching anything at all.
type FreshnessChecker interface {
	// FreshURLs returns the subset of normalizedURLs that already have a
	// document fetched more recently than since. A URL absent from the
	// result is either stale (last fetched before since) or was never
	// crawled at all -- both cases mean "go ahead and fetch it".
	FreshURLs(ctx context.Context, normalizedURLs []string, since time.Time) (map[string]bool, error)
}

// NoopFreshnessChecker is used when no persistent storage backend is
// configured (--storage=ndjson has no queryable history to check against).
// It reports nothing as fresh, so every URL is always eligible to fetch --
// the same behavior as before a revisit policy existed.
type NoopFreshnessChecker struct{}

func (NoopFreshnessChecker) FreshURLs(context.Context, []string, time.Time) (map[string]bool, error) {
	return nil, nil
}
