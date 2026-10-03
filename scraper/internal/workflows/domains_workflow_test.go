package workflows

import (
	"context"
	"sync"
	"testing"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/testsuite"

	"search-engine-scraper/internal/activities"
	"search-engine-scraper/internal/normalize"
)

func TestGroupSeedsByHost_OrdersByPriorityThenAppearance(t *testing.T) {
	groups := groupSeedsByHost([]Seed{
		{URL: "https://low.np/a", Priority: 1},
		{URL: "https://high.np/", Priority: 9},
		{URL: "https://low.np/b", Priority: 1},
		{URL: "https://mid.np/", Priority: 5},
	})
	if len(groups) != 3 {
		t.Fatalf("groups = %d, want 3 distinct hosts", len(groups))
	}
	order := []string{groups[0].Host, groups[1].Host, groups[2].Host}
	if order[0] != "high.np" || order[1] != "mid.np" || order[2] != "low.np" {
		t.Errorf("order = %v, want priority order high, mid, low", order)
	}
	if len(groups[2].Seeds) != 2 {
		t.Errorf("low.np seeds = %d, want both of its seeds grouped", len(groups[2].Seeds))
	}
}

// TestCrawlDomainsWorkflow_CrawlsEveryPageOfEveryDomain proves the
// whole-domain mode follows links past the seed page: each host's seed links
// to sub-pages, and every one of them must be fetched, for every host.
func TestCrawlDomainsWorkflow_CrawlsEveryPageOfEveryDomain(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.RegisterWorkflow(CrawlWorkflow)

	hosts := []string{"a.example.np", "b.example.np", "c.example.np"}
	subPages := []string{"/about", "/news", "/news/1", "/contact"}

	var mu sync.Mutex
	fetched := map[string]bool{}

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			fetched[in.URL] = true
			mu.Unlock()
			out := activities.ProcessPageOutput{URL: in.URL, NormalizedURL: in.URL, StatusCode: 200, ContentType: "text/html", ContentHash: in.URL, Text: "page " + in.URL}
			host := normalize.Hostname(in.URL)
			if in.URL == "https://"+host+"/" {
				for _, p := range subPages {
					out.Links = append(out.Links, "https://"+host+p)
				}
				out.Links = append(out.Links, "https://elsewhere.org/off-site") // must never be followed
			}
			return out, nil
		},
	)
	env.OnActivity(act.DiscoverSitemapURLs, mock.Anything, mock.Anything).Return(activities.DiscoverSitemapURLsOutput{}, nil)
	env.OnActivity(act.WriteDocument, mock.Anything, mock.Anything).Return(nil)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(7), nil)
	env.OnActivity(act.FinishCrawlRun, mock.Anything, mock.Anything).Return(nil)

	var seeds []Seed
	for _, h := range hosts {
		seeds = append(seeds, Seed{URL: "https://" + h + "/"})
	}
	env.ExecuteWorkflow(CrawlDomainsWorkflow, CrawlDomainsInput{
		Seeds:                seeds,
		PerDomain:            CrawlWorkflowInput{MaxDepth: 5, MaxPages: 40, Concurrency: 4, MaxConcurrentPerHost: 2},
		MaxConcurrentDomains: 2,
	})
	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}
	var res CrawlDomainsResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}

	for _, h := range hosts {
		for _, p := range append([]string{"/"}, subPages...) {
			if u := "https://" + h + p; !fetched[u] {
				t.Errorf("%s was not fetched", u)
			}
		}
	}
	if fetched["https://elsewhere.org/off-site"] {
		t.Error("an off-site link was followed in whole-domain mode")
	}
	if want := len(hosts) * (1 + len(subPages)); res.Stats.Fetched != want {
		t.Errorf("fetched = %d, want %d", res.Stats.Fetched, want)
	}
	if res.Domains.Started != 3 || res.Domains.Completed != 3 || res.Domains.Failed != 0 {
		t.Errorf("domains = %+v, want 3 started, 3 completed", res.Domains)
	}
	if res.RunID != 7 {
		t.Errorf("run id = %d, want the parent's run 7", res.RunID)
	}
}
