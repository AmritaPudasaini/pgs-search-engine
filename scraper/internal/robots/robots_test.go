package robots

import (
	"testing"
	"time"
)

func TestParseLongestMatchWins(t *testing.T) {
	body := `
User-agent: *
Disallow: /private
Allow: /private/public
Crawl-delay: 2
`
	rs := parse(body, "mybot")
	if len(rs.disallow) != 1 || rs.disallow[0] != "/private" {
		t.Fatalf("unexpected disallow rules: %v", rs.disallow)
	}
	if rs.crawlDelay.Seconds() != 2 {
		t.Fatalf("expected crawl-delay 2s, got %v", rs.crawlDelay)
	}
}

func TestParseSpecificAgentOverridesWildcard(t *testing.T) {
	body := `
User-agent: *
Disallow: /

User-agent: mybot
Disallow: /admin
`
	rs := parse(body, "mybot")
	if len(rs.disallow) != 1 || rs.disallow[0] != "/admin" {
		t.Fatalf("expected mybot-specific rules, got %v", rs.disallow)
	}
}

func TestParseGroupedUserAgents(t *testing.T) {
	body := `
User-agent: a
User-agent: b
Disallow: /x
`
	rs := parse(body, "b")
	if len(rs.disallow) != 1 || rs.disallow[0] != "/x" {
		t.Fatalf("expected grouped agents to share rules, got %v", rs.disallow)
	}
}

func TestParseSitemapsApplyRegardlessOfUserAgentGroup(t *testing.T) {
	body := `
Sitemap: https://example.com/sitemap.xml

User-agent: *
Disallow: /private

Sitemap: https://example.com/sitemap-news.xml

User-agent: mybot
Disallow: /admin
`
	want := []string{"https://example.com/sitemap.xml", "https://example.com/sitemap-news.xml"}

	for _, agent := range []string{"mybot", "someotherbot"} {
		rs := parse(body, agent)
		if len(rs.sitemaps) != len(want) {
			t.Fatalf("agent %q: sitemaps = %v, want %v", agent, rs.sitemaps, want)
		}
		for i := range want {
			if rs.sitemaps[i] != want[i] {
				t.Errorf("agent %q: sitemaps[%d] = %q, want %q", agent, i, rs.sitemaps[i], want[i])
			}
		}
	}
}

func TestParseNoSitemapsYieldsNilSlice(t *testing.T) {
	body := `
User-agent: *
Disallow: /private
`
	rs := parse(body, "mybot")
	if len(rs.sitemaps) != 0 {
		t.Errorf("sitemaps = %v, want none", rs.sitemaps)
	}
}

func TestParseCrawlDelayFractionalSeconds(t *testing.T) {
	body := `
User-agent: *
Crawl-delay: 0.5
`
	rs := parse(body, "mybot")
	if rs.crawlDelay != 500*time.Millisecond {
		t.Fatalf("crawlDelay = %v, want 500ms", rs.crawlDelay)
	}
}

// TestParseCrawlDelayInvalidValueIsIgnored proves a Crawl-delay line that
// doesn't parse as a number is dropped rather than left at some corrupted
// value or fatally rejecting the whole robots.txt -- consistent with the
// package's fetch-failure/parse-failure behavior elsewhere (see
// Guard.rulesFor and DiscoverSitemapURLs), where a malformed
// robots.txt degrades to "no extra rules" rather than blocking the crawl.
func TestParseCrawlDelayInvalidValueIsIgnored(t *testing.T) {
	body := `
User-agent: *
Crawl-delay: not-a-number
Disallow: /private
`
	rs := parse(body, "mybot")
	if rs.crawlDelay != 0 {
		t.Fatalf("crawlDelay = %v, want 0 (invalid value should be ignored)", rs.crawlDelay)
	}
	if len(rs.disallow) != 1 || rs.disallow[0] != "/private" {
		t.Fatalf("an invalid Crawl-delay line shouldn't affect other directives in the same group: disallow = %v", rs.disallow)
	}
}

func TestParseCrawlDelayAbsentDefaultsToZero(t *testing.T) {
	body := `
User-agent: *
Disallow: /private
`
	rs := parse(body, "mybot")
	if rs.crawlDelay != 0 {
		t.Fatalf("crawlDelay = %v, want 0 (no Crawl-delay directive present)", rs.crawlDelay)
	}
}
