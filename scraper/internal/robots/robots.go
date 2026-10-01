// Package robots implements minimal robots.txt fetching, parsing, and
// per-host caching so the crawler stays polite. It supports User-agent
// groups, Disallow/Allow rules (longest-match-wins) and Crawl-delay.
package robots

import (
	"bufio"
	"context"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/tekraj/pgs-search-engine/scraper/internal/fetcher"
)

type ruleSet struct {
	allow      []string
	disallow   []string
	crawlDelay time.Duration
	// sitemaps are Sitemap: directives -- these apply to the whole
	// robots.txt regardless of which User-agent group they appear under
	// (per the sitemaps.org/robots.txt convention), so every ruleSet
	// returned by parse for a given file carries the same list.
	sitemaps []string
}

// Guard checks and caches robots.txt rules per host.
type Guard struct {
	fetcher   *fetcher.Fetcher
	userAgent string

	mu    sync.Mutex
	cache map[string]*ruleSet // host -> rules
}

// New builds a Guard that uses f to fetch robots.txt files.
func New(f *fetcher.Fetcher, userAgent string) *Guard {
	return &Guard{
		fetcher:   f,
		userAgent: userAgent,
		cache:     make(map[string]*ruleSet),
	}
}

// Allowed reports whether rawURL may be fetched under the target host's
// robots.txt, fetching and caching the file on first use for that host.
func (g *Guard) Allowed(ctx context.Context, rawURL string) bool {
	u, err := url.Parse(rawURL)
	if err != nil {
		return false
	}

	rs := g.rulesFor(ctx, u)
	if rs == nil {
		return true // no robots.txt or fetch failed => assume allowed
	}

	path := u.Path
	if path == "" {
		path = "/"
	}

	// Longest matching rule wins; Allow beats Disallow on a tie.
	bestLen := -1
	allowed := true
	for _, d := range rs.disallow {
		if d != "" && strings.HasPrefix(path, d) && len(d) > bestLen {
			bestLen = len(d)
			allowed = false
		}
	}
	for _, a := range rs.allow {
		if a != "" && strings.HasPrefix(path, a) && len(a) >= bestLen {
			bestLen = len(a)
			allowed = true
		}
	}
	return allowed
}

// CrawlDelay returns the site-requested delay between requests, if any.
func (g *Guard) CrawlDelay(ctx context.Context, rawURL string) time.Duration {
	u, err := url.Parse(rawURL)
	if err != nil {
		return 0
	}
	rs := g.rulesFor(ctx, u)
	if rs == nil {
		return 0
	}
	return rs.crawlDelay
}

// Sitemaps returns the Sitemap: URLs declared in the target host's
// robots.txt, or nil if it declares none (or has no robots.txt at all).
// These are the standard way a crawler discovers URLs beyond following
// links, so callers should seed the frontier from them in addition to any
// explicit seeds.
func (g *Guard) Sitemaps(ctx context.Context, rawURL string) []string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return nil
	}
	rs := g.rulesFor(ctx, u)
	if rs == nil {
		return nil
	}
	return rs.sitemaps
}

func (g *Guard) rulesFor(ctx context.Context, u *url.URL) *ruleSet {
	host := u.Host

	g.mu.Lock()
	if rs, ok := g.cache[host]; ok {
		g.mu.Unlock()
		return rs
	}
	g.mu.Unlock()

	robotsURL := u.Scheme + "://" + host + "/robots.txt"
	res, err := g.fetcher.Get(ctx, robotsURL)

	var rs *ruleSet
	if err == nil && res.StatusCode == 200 {
		rs = parse(string(res.Body), g.userAgent)
	}

	g.mu.Lock()
	g.cache[host] = rs
	g.mu.Unlock()

	return rs
}

// parse extracts the rule group matching userAgent (falling back to "*").
func parse(body, userAgent string) *ruleSet {
	groups := map[string]*ruleSet{}
	var current []string // agent names for the group currently being read
	lastWasAgent := false
	var sitemaps []string // Sitemap: directives, not scoped to any group

	scanner := bufio.NewScanner(strings.NewReader(body))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.ToLower(strings.TrimSpace(parts[0]))
		val := strings.TrimSpace(parts[1])

		switch key {
		case "user-agent":
			agent := strings.ToLower(val)
			if _, ok := groups[agent]; !ok {
				groups[agent] = &ruleSet{}
			}
			if lastWasAgent {
				current = append(current, agent)
			} else {
				current = []string{agent}
			}
			lastWasAgent = true
			continue
		case "disallow":
			for _, a := range current {
				groups[a].disallow = append(groups[a].disallow, val)
			}
		case "allow":
			for _, a := range current {
				groups[a].allow = append(groups[a].allow, val)
			}
		case "crawl-delay":
			if secs, err := strconv.ParseFloat(val, 64); err == nil {
				for _, a := range current {
					groups[a].crawlDelay = time.Duration(secs * float64(time.Second))
				}
			}
		case "sitemap":
			if val != "" {
				sitemaps = append(sitemaps, val)
			}
		}
		lastWasAgent = false
	}

	agent := strings.ToLower(userAgent)
	rs, ok := groups[agent]
	if !ok {
		rs, ok = groups["*"]
	}
	if !ok {
		rs = &ruleSet{}
	}
	rs.sitemaps = sitemaps
	return rs
}
