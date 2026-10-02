package robots

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"search-engine-scraper/internal/fetcher"
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

func newGuardFor(t *testing.T, robotsBody string, status int) (*Guard, string) {
	t.Helper()
	var hits int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/robots.txt" {
			http.NotFound(w, r)
			return
		}
		hits++
		w.WriteHeader(status)
		w.Write([]byte(robotsBody))
	}))
	t.Cleanup(srv.Close)
	g := New(fetcher.New(5*time.Second, 0), "testbot")
	t.Cleanup(func() {
		if hits > 1 {
			t.Errorf("robots.txt fetched %d times, want it cached after the first", hits)
		}
	})
	return g, srv.URL
}

func TestGuardAllowed_HonorsDisallowAndAllow(t *testing.T) {
	g, base := newGuardFor(t, "User-agent: *\nDisallow: /private\nAllow: /private/public\n", http.StatusOK)
	ctx := context.Background()

	if g.Allowed(ctx, base+"/private/secret") {
		t.Error("/private/secret should be disallowed")
	}
	if !g.Allowed(ctx, base+"/private/public/page") {
		t.Error("/private/public/page should be allowed (longest match wins)")
	}
	if !g.Allowed(ctx, base+"/open") {
		t.Error("/open should be allowed")
	}
}

func TestGuardAllowed_MissingRobotsTxtAllowsEverything(t *testing.T) {
	g, base := newGuardFor(t, "", http.StatusNotFound)
	if !g.Allowed(context.Background(), base+"/anything") {
		t.Error("a 404 robots.txt should allow all URLs")
	}
}

func TestGuardAllowed_UnparsableURLIsDisallowed(t *testing.T) {
	g := New(fetcher.New(time.Second, 0), "testbot")
	if g.Allowed(context.Background(), "http://[::1") {
		t.Error("an unparsable URL should not be allowed")
	}
}

func TestGuardCrawlDelayAndSitemaps(t *testing.T) {
	g, base := newGuardFor(t, "User-agent: *\nCrawl-delay: 3\nSitemap: https://example.com/sm.xml\n", http.StatusOK)
	ctx := context.Background()

	if got := g.CrawlDelay(ctx, base+"/"); got != 3*time.Second {
		t.Errorf("CrawlDelay = %v, want 3s", got)
	}
	sm := g.Sitemaps(ctx, base+"/")
	if len(sm) != 1 || sm[0] != "https://example.com/sm.xml" {
		t.Errorf("Sitemaps = %v, want [https://example.com/sm.xml]", sm)
	}
}

func TestGuardCrawlDelayAndSitemaps_NoRobotsTxt(t *testing.T) {
	g, base := newGuardFor(t, "", http.StatusNotFound)
	ctx := context.Background()

	if got := g.CrawlDelay(ctx, base+"/"); got != 0 {
		t.Errorf("CrawlDelay = %v, want 0", got)
	}
	if sm := g.Sitemaps(ctx, base+"/"); sm != nil {
		t.Errorf("Sitemaps = %v, want nil", sm)
	}
}
