package workflows

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"

	"search-engine-scraper/internal/activities"
	"search-engine-scraper/internal/normalize"
)

func TestTaskQueueForHost_OffUsesSharedQueue(t *testing.T) {
	for _, shards := range []int{-1, 0, 1} {
		if got := TaskQueueForHost("example.com", shards); got != TaskQueueName {
			t.Errorf("shards=%d: queue = %q, want %q", shards, got, TaskQueueName)
		}
	}
}

func TestTaskQueueForHost_StableAndCaseInsensitive(t *testing.T) {
	a := TaskQueueForHost("Example.COM", 8)
	b := TaskQueueForHost("example.com", 8)
	if a != b {
		t.Errorf("same host mapped to %q and %q", a, b)
	}
	for i := 0; i < 5; i++ {
		if TaskQueueForHost("example.com", 8) != a {
			t.Fatal("mapping is not stable across calls")
		}
	}
}

func TestShardForHost_InRangeAndSpread(t *testing.T) {
	const shards = 4
	counts := make([]int, shards)
	for i := 0; i < 2000; i++ {
		s := ShardForHost(fmt.Sprintf("site-%d.gov.np", i), shards)
		if s < 0 || s >= shards {
			t.Fatalf("shard %d out of range", s)
		}
		counts[s]++
	}
	for i, c := range counts {
		if c < 350 || c > 650 {
			t.Errorf("shard %d got %d of 2000 hosts, want a roughly even spread", i, c)
		}
	}
}

// TestCrawlWorkflow_ShardsRouteEachHostToItsOwnQueue proves that with
// TaskQueueShards set, every fetch for a host is scheduled on that host's
// shard queue -- never on another host's -- and that the crawl still
// completes.
func TestCrawlWorkflow_ShardsRouteEachHostToItsOwnQueue(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()

	const shards = 3
	urls := []string{
		"https://a.example.np/", "https://b.example.np/", "https://c.example.np/",
		"https://d.example.np/", "https://e.example.np/", "https://f.example.np/",
	}

	var mu sync.Mutex
	queues := map[string]string{} // host -> queue its fetch ran on

	env.OnActivity(act.ProcessPage, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in activities.ProcessPageInput) (activities.ProcessPageOutput, error) {
			mu.Lock()
			queues[normalize.Hostname(in.URL)] = activity.GetInfo(ctx).TaskQueue
			mu.Unlock()
			return activities.ProcessPageOutput{URL: in.URL, NormalizedURL: in.URL, Skipped: true, SkipReason: "test"}, nil
		},
	)
	env.OnActivity(act.DiscoverSitemapURLs, mock.Anything, mock.Anything).Return(activities.DiscoverSitemapURLsOutput{}, nil)
	env.OnActivity(act.StartCrawlRun, mock.Anything, mock.Anything).Return(int64(0), nil)

	var seeds []Seed
	for _, u := range urls {
		seeds = append(seeds, Seed{URL: u})
	}
	env.ExecuteWorkflow(CrawlWorkflow, CrawlWorkflowInput{
		Seeds: seeds, MaxDepth: 0, MaxPages: 20, Concurrency: 6, TaskQueueShards: shards,
	})
	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow error: %v", err)
	}

	if len(queues) != len(urls) {
		t.Fatalf("fetched %d hosts, want %d", len(queues), len(urls))
	}
	for host, q := range queues {
		if want := TaskQueueForHost(host, shards); q != want {
			t.Errorf("host %s fetched on %q, want its shard queue %q", host, q, want)
		}
		if !strings.Contains(q, "-shard-") {
			t.Errorf("host %s fetched on %q, want a shard queue", host, q)
		}
	}
}
