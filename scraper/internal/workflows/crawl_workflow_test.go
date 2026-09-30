package workflows

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/testsuite"

	"search-engine-scraper/internal/activities"
	"search-engine-scraper/internal/simhash"
)

// TestCrawlWorkflow_RevisitAfter_SkipsFreshURLs proves the revisit/
// freshness policy is actually wired end-to-end: with RevisitAfter set,
// a seed CheckFreshness reports as fresh must never be fetched, while an
// unrelated seed (and one CheckFreshness reports as stale/never-crawled by
// simply not including it) must be.
func TestCrawlWorkflow_RevisitAfter_SkipsFreshURLs(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	const (
		freshURL = "https://example.com/fresh"
		staleURL = "https://example.com/stale"
	)

	var mu sync.Mutex
	fetched := map[string]bool{}

	env.OnActivity(act.CheckFreshness, mock.Anything, mock.Anything).Return(
		activities.CheckFreshnessOutput{Fresh: map[string]bool{freshURL: true}}, nil,
	)
	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			fetched[in.URL] = true
			mu.Unlock()
			return activities.ProcessPageOutput{
				URL: in.URL, NormalizedURL: in.URL, Skipped: true, SkipReason: "test",
			}, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds:        []Seed{{URL: freshURL}, {URL: staleURL}},
		MaxDepth:     0,
		MaxPages:     10,
		Concurrency:  4,
		RevisitAfter: 24 * time.Hour,
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if fetched[freshURL] {
		t.Error("fresh URL should NOT have been fetched: CheckFreshness reported it as fresh")
	}
	if !fetched[staleURL] {
		t.Error("stale URL should have been fetched: CheckFreshness did not report it as fresh")
	}
}

// TestCrawlWorkflow_RevisitAfterZero_NeverChecksFreshness proves the policy
// is truly opt-in: with RevisitAfter left at zero (the default), no
// CheckFreshness activity call should happen at all, and every URL should
// be fetched -- the exact pre-existing behavior, unaffected by this
// feature's presence.
func TestCrawlWorkflow_RevisitAfterZero_NeverChecksFreshness(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	const url = "https://example.com/a"

	var mu sync.Mutex
	fetched := map[string]bool{}

	// Deliberately NOT mocking act.CheckFreshness: if the workflow calls it
	// anyway, the test environment will error the activity (unregistered),
	// which would surface as the seed never getting enqueued/fetched.
	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			fetched[in.URL] = true
			mu.Unlock()
			return activities.ProcessPageOutput{
				URL: in.URL, NormalizedURL: in.URL, Skipped: true, SkipReason: "test",
			}, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds:       []Seed{{URL: url}},
		MaxDepth:    0,
		MaxPages:    10,
		Concurrency: 4,
		// RevisitAfter intentionally left zero.
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}
	if !fetched[url] {
		t.Error("URL should have been fetched: RevisitAfter=0 disables the freshness check entirely")
	}
}

// TestCrawlWorkflow_NearDuplicateNotWritten proves the near-duplicate check
// is actually wired into the workflow end-to-end: seed B's text is a
// near-duplicate of seed A's (same shared body, differing only by a
// timestamp -- the exact case exact content-hash dedup can't catch), and
// must NOT be written as a Document, while unrelated seed C must be.
func TestCrawlWorkflow_NearDuplicateNotWritten(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	const sharedBody = `the quarterly earnings report released this morning showed the
company beat analyst expectations on both revenue and profit margins
the stock price rallied in early trading as investors reacted
positively to the strong guidance provided by the chief financial
officer during the call analysts noted that the growth was broad
based across all major product lines and geographic regions the
company reiterated its full year outlook and announced an increase
to its share buyback program`

	textA := sharedBody + " published 2024-01-01 10:00am"
	textB := sharedBody + " published 2024-01-01 11:30am"
	textC := "a completely unrelated recipe for chocolate chip cookies requires flour sugar butter eggs vanilla extract baking soda and a pinch of salt mixed together and baked at 350 degrees for twelve minutes until golden brown around the edges"

	const (
		urlA = "https://example.com/a"
		urlB = "https://example.com/b"
		urlC = "https://example.com/c"
	)

	var mu sync.Mutex
	written := map[string]bool{}

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			var text string
			switch in.URL {
			case urlA:
				text = textA
			case urlB:
				text = textB
			case urlC:
				text = textC
			}
			return activities.ProcessPageOutput{
				URL:           in.URL,
				NormalizedURL: in.URL,
				Text:          text,
				SimHash:       simhash.Fingerprint(text),
			}, nil
		},
	)
	env.OnActivity(act.WriteDocument, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.WriteDocumentInput) error {
			mu.Lock()
			written[in.Doc.URL] = true
			mu.Unlock()
			return nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds:       []Seed{{URL: urlA}, {URL: urlB}, {URL: urlC}},
		MaxDepth:    0,
		MaxPages:    10,
		Concurrency: 1, // deterministic processing order: A, then B, then C
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if !written[urlA] {
		t.Error("A should have been written: it's the first of its near-duplicate group")
	}
	if written[urlB] {
		t.Error("B should NOT have been written: it's a near-duplicate of A")
	}
	if !written[urlC] {
		t.Error("C should have been written: it's unrelated content")
	}
}

// TestCrawlWorkflow_RedirectFinalURL_MarkedSeenPreventsDuplicateFetch proves
// crawl_workflow.go's addSeen(res.FinalURL) call actually prevents a
// re-fetch: seed A redirects to finalA, and A's own page happens to link
// directly to finalA (a realistic case: a redirected page's canonical
// content links back to its own final location, e.g. via a self-referential
// nav link). finalA must never be fetched a second time.
func TestCrawlWorkflow_RedirectFinalURL_MarkedSeenPreventsDuplicateFetch(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	const (
		urlA      = "https://example.com/a"
		urlFinalA = "https://example.com/final-a"
	)

	var mu sync.Mutex
	fetchCount := map[string]int{}

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			fetchCount[in.URL]++
			mu.Unlock()

			out := activities.ProcessPageOutput{URL: in.URL, NormalizedURL: in.URL}
			if in.URL == urlA {
				out.NormalizedURL = urlFinalA
				out.FinalURL = urlFinalA
				out.Links = []string{urlFinalA}
			}
			return out, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)
	env.OnActivity(act.WriteDocument, mock.Anything, mock.Anything).Return(nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds:       []Seed{{URL: urlA}},
		MaxDepth:    1,
		MaxPages:    10,
		Concurrency: 4,
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if fetchCount[urlA] != 1 {
		t.Errorf("fetchCount[A] = %d, want 1", fetchCount[urlA])
	}
	if fetchCount[urlFinalA] != 0 {
		t.Errorf("fetchCount[finalA] = %d, want 0 (already captured under A's redirect identity)", fetchCount[urlFinalA])
	}
}

// TestCrawlWorkflow_NoIndexAndNoFollow_AreIndependent proves the two
// directives are handled independently, not as one combined "skip this
// page" flag:
//   - seed A is NoIndex but not NoFollow: it must NOT be written as a
//     Document, but its one link (to B) must still be followed.
//   - seed C is NoFollow but not NoIndex: it must be written as a Document,
//     but its one link (to D) must NOT be followed -- D should never be
//     fetched at all.
func TestCrawlWorkflow_NoIndexAndNoFollow_AreIndependent(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	const (
		urlA = "https://example.com/a"
		urlB = "https://example.com/b"
		urlC = "https://example.com/c"
		urlD = "https://example.com/d"
	)

	var mu sync.Mutex
	fetched := map[string]bool{}
	written := map[string]bool{}

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			fetched[in.URL] = true
			mu.Unlock()

			out := activities.ProcessPageOutput{URL: in.URL, NormalizedURL: in.URL}
			switch in.URL {
			case urlA:
				out.NoIndex = true
				out.Links = []string{urlB}
			case urlC:
				out.NoFollow = true
				out.Links = []string{urlD}
			}
			return out, nil
		},
	)
	env.OnActivity(act.WriteDocument, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.WriteDocumentInput) error {
			mu.Lock()
			written[in.Doc.URL] = true
			mu.Unlock()
			return nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds:       []Seed{{URL: urlA}, {URL: urlC}},
		MaxDepth:    1,
		MaxPages:    10,
		Concurrency: 4,
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if !fetched[urlB] {
		t.Error("B should have been fetched: A is NoIndex but not NoFollow, so its links must still be followed")
	}
	if fetched[urlD] {
		t.Error("D should NOT have been fetched: C is NoFollow, so its links must not be followed")
	}
	if written[urlA] {
		t.Error("A should NOT have been written: it declared NoIndex")
	}
	if !written[urlC] {
		t.Error("C should have been written: NoFollow alone doesn't imply NoIndex")
	}
}

// TestCrawlWorkflow_SeedsFrontierFromSitemap proves DiscoverSitemapURLs
// results actually get enqueued and fetched, not just requested: one seed,
// whose mocked sitemap discovery returns two more URLs, should result in
// exactly three ProcessPage calls -- the seed itself plus both
// sitemap-discovered URLs -- even though only one URL was ever given as a
// Seed.
func TestCrawlWorkflow_SeedsFrontierFromSitemap(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	var mu sync.Mutex
	fetched := map[string]bool{}

	env.OnActivity(act.DiscoverSitemapURLs, mock.Anything, mock.Anything).Return(
		activities.DiscoverSitemapURLsOutput{
			URLs: []string{
				"https://example.com/from-sitemap-1",
				"https://example.com/from-sitemap-2",
			},
		}, nil,
	)
	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			fetched[in.URL] = true
			mu.Unlock()
			return activities.ProcessPageOutput{
				URL:           in.URL,
				NormalizedURL: in.URL,
				Skipped:       true,
				SkipReason:    "test",
			}, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds:       []Seed{{URL: "https://example.com/"}},
		MaxDepth:    0,
		MaxPages:    10,
		Concurrency: 4,
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	want := []string{
		"https://example.com/",
		"https://example.com/from-sitemap-1",
		"https://example.com/from-sitemap-2",
	}
	for _, u := range want {
		if !fetched[u] {
			t.Errorf("expected %q to be fetched, fetched = %v", u, fetched)
		}
	}
	if len(fetched) != len(want) {
		t.Errorf("fetched %d URLs %v, want exactly %v", len(fetched), fetched, want)
	}
}

// TestCrawlWorkflow_MaxConcurrentPerHost proves the scheduler in
// crawl_workflow.go actually enforces MaxConcurrentPerHost: with 5 seeds on
// the same host, a global Concurrency of 5 (which would let all 5 fetch at
// once with no per-host cap), and MaxConcurrentPerHost=1, at most one
// ProcessPage call for that host should ever be in flight simultaneously.
// The mocked activity sleeps briefly and records concurrent-call overlap
// via a real counter, so a scheduling bug (e.g. accidentally checking
// domainCounts instead of activeHostCounts) would show up as maxObserved>1.
func TestCrawlWorkflow_MaxConcurrentPerHost(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	var mu sync.Mutex
	inFlight := 0
	maxObserved := 0

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			inFlight++
			if inFlight > maxObserved {
				maxObserved = inFlight
			}
			mu.Unlock()

			time.Sleep(50 * time.Millisecond)

			mu.Lock()
			inFlight--
			mu.Unlock()

			return activities.ProcessPageOutput{
				URL:           in.URL,
				NormalizedURL: in.URL,
				Skipped:       true,
				SkipReason:    "test",
			}, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds: []Seed{
			{URL: "https://example.com/a"},
			{URL: "https://example.com/b"},
			{URL: "https://example.com/c"},
			{URL: "https://example.com/d"},
			{URL: "https://example.com/e"},
		},
		MaxDepth:             0,
		MaxPages:             5,
		Concurrency:          5,
		MaxConcurrentPerHost: 1,
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if maxObserved == 0 {
		t.Fatal("no ProcessPage calls were observed -- test setup is broken")
	}
	if maxObserved > 1 {
		t.Errorf("observed %d concurrent fetches to the same host, want at most 1 (MaxConcurrentPerHost=1)", maxObserved)
	}
}

// TestCrawlWorkflow_PriorityOrdersFrontier proves higher-Priority seeds are
// fetched before lower-Priority ones even though they were listed later --
// with Concurrency=1, only one fetch runs at a time, so the ProcessPage
// call order is exactly the frontier's pick order.
func TestCrawlWorkflow_PriorityOrdersFrontier(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	var mu sync.Mutex
	var order []string

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			order = append(order, in.URL)
			mu.Unlock()
			return activities.ProcessPageOutput{
				URL: in.URL, NormalizedURL: in.URL, Skipped: true, SkipReason: "test",
			}, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds: []Seed{
			{URL: "https://a.example", Priority: 1},
			{URL: "https://b.example", Priority: 5},
			{URL: "https://c.example", Priority: 3},
		},
		MaxDepth:    0,
		MaxPages:    3,
		Concurrency: 1,
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	want := []string{"https://b.example", "https://c.example", "https://a.example"}
	if len(order) != len(want) {
		t.Fatalf("ProcessPage order = %v, want %v", order, want)
	}
	for i := range want {
		if order[i] != want[i] {
			t.Errorf("ProcessPage order = %v, want %v", order, want)
			break
		}
	}
}

// TestCrawlWorkflow_NoMaxConcurrentPerHost_AllowsFullConcurrency is the
// control case: with MaxConcurrentPerHost left at 0 (unlimited), the same 5
// same-host seeds under Concurrency=5 should run with real overlap -- this
// guards against a fix that accidentally always throttles to 1 regardless
// of the setting.
func TestCrawlWorkflow_NoMaxConcurrentPerHost_AllowsFullConcurrency(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	var mu sync.Mutex
	inFlight := 0
	maxObserved := 0

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			inFlight++
			if inFlight > maxObserved {
				maxObserved = inFlight
			}
			mu.Unlock()

			time.Sleep(50 * time.Millisecond)

			mu.Lock()
			inFlight--
			mu.Unlock()

			return activities.ProcessPageOutput{
				URL:           in.URL,
				NormalizedURL: in.URL,
				Skipped:       true,
				SkipReason:    "test",
			}, nil
		},
	)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds: []Seed{
			{URL: "https://example.com/a"},
			{URL: "https://example.com/b"},
			{URL: "https://example.com/c"},
			{URL: "https://example.com/d"},
			{URL: "https://example.com/e"},
		},
		MaxDepth:    0,
		MaxPages:    5,
		Concurrency: 5,
		// MaxConcurrentPerHost intentionally left 0 (unlimited).
	})

	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if maxObserved <= 1 {
		t.Errorf("observed at most %d concurrent fetch(es), want overlap (>1) with no per-host cap and Concurrency=5", maxObserved)
	}
}
