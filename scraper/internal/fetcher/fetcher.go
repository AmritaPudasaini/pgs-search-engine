// Package fetcher wraps an http.Client with the politeness and safety
// behavior a crawler needs: timeouts, a real User-Agent, capped response
// bodies, and simple retry-once-on-failure semantics.
package fetcher

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sync"
	"time"

	"golang.org/x/time/rate"
)

const (
	// MaxBodyBytes caps how much of a response we read, so one huge page
	// (or a misbehaving server) can't blow up memory.
	MaxBodyBytes = 5 << 20 // 5MB
	userAgent    = "search-engine-scraper/0.1 (+https://github.com/example/search-engine-scraper)"
)

// Fetcher performs polite HTTP GETs.
type Fetcher struct {
	client *http.Client

	domainRequestsPerSecond rate.Limit
	domainBurst             int
	defaultPolitenessDelay  time.Duration
	domainsMu               sync.Mutex
	domains                 map[string]*domainState
	// bandwidth throttles total bytes/sec read across every Get() call on
	// this Fetcher (shared, so it caps one worker process's aggregate
	// download rate regardless of how many fetches run concurrently), nil
	// when unlimited.
	bandwidth *rate.Limiter
	// bandwidthChunk is bandwidth's burst size (one second's worth of
	// bytes at the configured rate) and also the most bytes charged to it
	// in a single WaitN call -- WaitN errors if asked to wait for more
	// than the bucket's burst can ever hold, so a response larger than one
	// second's budget is charged in several chunks of at most this size
	// instead of a single too-big call.
	bandwidthChunk int
}

type domainState struct {
	limiter *rate.Limiter
	mu      sync.Mutex
	next    time.Time
	delay   time.Duration
}

// Options controls request safety and per-domain politeness.
type Options struct {
	Timeout                 time.Duration
	MaxBandwidthBPS         int
	DomainRequestsPerSecond float64
	DomainBurst             int
	PolitenessDelay         time.Duration
}

// redirectChainKey is the context key Get() uses to give its CheckRedirect
// invocations somewhere to record each hop's target -- a pointer to a
// slice, since context values are immutable but the pointee isn't. This is
// concurrency-safe despite CheckRedirect being one function shared across
// every Get() call on the same *http.Client: Go's redirect-following loop
// copies the *original* request's context onto every subsequent redirect
// request (see net/http's Client.do, which sets ctx: ireq.ctx), so each
// top-level Get() call's chain of redirects always sees the one *[]string
// that Get() created for it, never another concurrent call's.
type redirectChainKey struct{}

// New builds a Fetcher with the given per-request timeout. maxBandwidthBPS
// caps this Fetcher's aggregate download rate in bytes/sec across every
// concurrent Get() call; 0 means unlimited.
func New(timeout time.Duration, maxBandwidthBPS int) *Fetcher {
	return NewWithOptions(Options{
		Timeout:         timeout,
		MaxBandwidthBPS: maxBandwidthBPS,
	})
}

// NewWithOptions builds a Fetcher with independent rate and delay state for
// each hostname. A zero request rate or delay disables that control.
func NewWithOptions(opts Options) *Fetcher {
	var limiter *rate.Limiter
	chunk := 0
	if opts.MaxBandwidthBPS > 0 {
		chunk = opts.MaxBandwidthBPS
		limiter = rate.NewLimiter(rate.Limit(opts.MaxBandwidthBPS), chunk)
	}
	burst := opts.DomainBurst
	if burst <= 0 {
		burst = 1
	}
	return &Fetcher{
		bandwidth:              limiter,
		bandwidthChunk:         chunk,
		domainRequestsPerSecond: rate.Limit(opts.DomainRequestsPerSecond),
		domainBurst:             burst,
		defaultPolitenessDelay:  opts.PolitenessDelay,
		domains:                 make(map[string]*domainState),
		client: &http.Client{
			Timeout: opts.Timeout,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				if len(via) >= 10 {
					return fmt.Errorf("stopped after 10 redirects")
				}
				if chain, ok := req.Context().Value(redirectChainKey{}).(*[]string); ok {
					*chain = append(*chain, req.URL.String())
				}
				return nil
			},
		},
	}
}

// SetDomainDelay applies a robots.txt Crawl-delay to one hostname. Existing
// limiter state is retained so changing the delay cannot reset rate limits.
func (f *Fetcher) SetDomainDelay(rawURL string, delay time.Duration) error {
	u, err := url.Parse(rawURL)
	if err != nil || u.Hostname() == "" {
		return fmt.Errorf("invalid domain URL %q", rawURL)
	}
	state := f.domainState(u.Hostname())
	state.mu.Lock()
	state.delay = delay
	state.mu.Unlock()
	return nil
}

func (f *Fetcher) domainState(host string) *domainState {
	f.domainsMu.Lock()
	defer f.domainsMu.Unlock()
	if state, ok := f.domains[host]; ok {
		return state
	}
	state := &domainState{delay: f.defaultPolitenessDelay}
	if f.domainRequestsPerSecond > 0 {
		state.limiter = rate.NewLimiter(f.domainRequestsPerSecond, f.domainBurst)
	}
	f.domains[host] = state
	return state
}

func (f *Fetcher) waitForDomain(ctx context.Context, rawURL string) error {
	u, err := url.Parse(rawURL)
	if err != nil || u.Hostname() == "" {
		return fmt.Errorf("invalid fetch URL %q", rawURL)
	}
	state := f.domainState(u.Hostname())
	if state.limiter != nil {
		if err := state.limiter.Wait(ctx); err != nil {
			return fmt.Errorf("domain rate limiter: %w", err)
		}
	}

	state.mu.Lock()
	now := time.Now()
	startAt := state.next
	if startAt.Before(now) {
		startAt = now
	}
	state.next = startAt.Add(state.delay)
	state.mu.Unlock()

	if wait := time.Until(startAt); wait > 0 {
		timer := time.NewTimer(wait)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
		}
	}
	return nil
}

// Result is the outcome of fetching a single URL.
type Result struct {
	StatusCode  int
	ContentType string
	Header      http.Header // full response headers, e.g. so callers can read Retry-After on a 429
	Body        []byte
	Duration    time.Duration

	// FinalURL is the URL the response actually came from, after following
	// any redirects -- equal to the requested URL if there were none. A
	// caller that only records the URL it asked for silently loses this
	// whenever a page 301s elsewhere, which is common (tracking-param
	// canonicalization, http->https upgrades, trailing-slash normalization).
	FinalURL string
	// RedirectChain lists each hop's target URL in the order visited (the
	// requested URL is NOT included, only where it redirected to), so the
	// full path -- not just start and end -- is visible. Empty if the
	// request wasn't redirected at all.
	RedirectChain []string
}

// Get fetches url, respecting ctx cancellation, and returns at most
// MaxBodyBytes of the body.
func (f *Fetcher) Get(ctx context.Context, url string) (*Result, error) {
	start := time.Now()
	if err := f.waitForDomain(ctx, url); err != nil {
		return nil, err
	}

	var chain []string
	ctx = context.WithValue(ctx, redirectChainKey{}, &chain)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Accept", "text/html,application/xhtml+xml")

	resp, err := f.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("do request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, MaxBodyBytes))
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}

	if f.bandwidth != nil {
		// Charge this response's bytes against the shared bucket, in chunks
		// no larger than the bucket's burst, blocking until the rate
		// allows -- throttles this worker's aggregate download rate rather
		// than any single fetch's speed.
		for remaining := len(body); remaining > 0; {
			n := f.bandwidthChunk
			if n > remaining {
				n = remaining
			}
			if err := f.bandwidth.WaitN(ctx, n); err != nil {
				return nil, fmt.Errorf("bandwidth limiter: %w", err)
			}
			remaining -= n
		}
	}

	finalURL := url
	if resp.Request != nil && resp.Request.URL != nil {
		finalURL = resp.Request.URL.String()
	}

	return &Result{
		StatusCode:    resp.StatusCode,
		ContentType:   resp.Header.Get("Content-Type"),
		Header:        resp.Header,
		Body:          body,
		Duration:      time.Since(start),
		FinalURL:      finalURL,
		RedirectChain: chain,
	}, nil
}
