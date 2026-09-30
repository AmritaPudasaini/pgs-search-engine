// Command scraper is the CLI client that starts a crawl: it does not fetch
// anything itself, it asks Temporal to run CrawlWorkflow and (optionally)
// waits for the result. The actual fetching happens in one or more
// `worker` processes (see cmd/worker) that may be on different machines --
// this client only needs network access to the Temporal server.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"strings"
	"time"

	"go.temporal.io/sdk/client"

	"search-engine-scraper/internal/envflag"
	"search-engine-scraper/internal/seeds"
	"search-engine-scraper/internal/workflows"
)

// Auto-concurrency bounds used when --concurrency is left at 0: the
// workflow's in-flight-fetch budget scales with how many seed URLs the
// seed file provided (more seeds/links to cover in parallel warrants more
// concurrency), clamped so a tiny seed file doesn't starve itself and a
// huge one doesn't request an unbounded number of in-flight fetches.
const (
	autoConcurrencyPerSeed = 4
	autoConcurrencyMin     = 8
	autoConcurrencyMax     = 256
)

// autoConcurrency derives a workflow Concurrency from how many seed URLs
// this crawl was given, so scaling out to more/fewer seeding links changes
// how much fetch parallelism the crawl requests without a manual flag per
// seed file size.
func autoConcurrency(numSeeds int) int {
	c := numSeeds * autoConcurrencyPerSeed
	if c < autoConcurrencyMin {
		c = autoConcurrencyMin
	}
	if c > autoConcurrencyMax {
		c = autoConcurrencyMax
	}
	return c
}

func main() {
	var (
		hostPort      = envflag.String("temporal-address", "localhost:7233", "Temporal frontend address")
		namespace     = envflag.String("namespace", "default", "Temporal namespace")
		seedsFlag     = flag.String("seeds", "", "comma-separated list of seed URLs (use this OR --seeds-file)")
		seedsFile     = envflag.String("seeds-file", "", "path to a seed-list file with [category] sections (use this OR --seeds)")
		category      = flag.String("category", seeds.DefaultCategory, "category label applied to all URLs given via --seeds")
		priority      = flag.Int("priority", seeds.DefaultPriority, "crawl priority applied to all URLs given via --seeds (higher = crawled first); use --seeds-file for per-URL/per-category priority")
		maxDepth      = flag.Int("max-depth", 2, "maximum link depth to follow from a seed")
		maxPages      = flag.Int("max-pages", 100, "maximum total pages to fetch this crawl, across all seeds/categories")
		maxPerDomain  = flag.Int("max-pages-per-domain", 0, "cap pages fetched from any single host (0 = unlimited, shared budget is first-come-first-served)")
		concurrency   = flag.Int("concurrency", 0, "max pages a single workflow run has in flight at once (0 = auto-scale with seed count: numSeeds*4, clamped to [8,256])")
		maxPerHost    = flag.Int("max-concurrent-per-host", 0, "cap concurrent in-flight fetches to any single host (0 = unlimited, --concurrency alone governs total in-flight fetches)")
		revisitAfter  = flag.Duration("revisit-after", 0, "skip (re-)fetching a URL already crawled more recently than this (0 = disabled, always fetch; requires --storage=postgres on the worker to have any effect)")
		sameHost      = flag.Bool("same-host-only", true, "keep each seed's discovered links on that seed's own host; false = open crawl, follow links anywhere")
		countryFilter = envflag.String("country-filter", "NP", "ISO 3166-1 alpha-2 country code: only pages detected as this country are written as documents (others are still fetched and followed for links, just not stored); empty = no filter, store every page regardless of detected country")
		workflowID    = flag.String("workflow-id", "", "Temporal workflow ID (default: derived from seeds + timestamp)")
		wait          = flag.Bool("wait", true, "block until the crawl finishes and print final stats (ignored when --cron is set)")
		cron          = flag.String("cron", "", `Temporal cron schedule (standard 5-field crontab syntax, e.g. "*/15 * * * *" for every 15 minutes) to run this crawl automatically and repeatedly instead of once; Temporal itself durably fires each occurrence, so no external scheduler is needed and the crawl keeps recurring even if this client process exits`)
	)
	flag.Parse()

	if (*seedsFlag == "") == (*seedsFile == "") {
		log.Fatal("pass exactly one of --seeds or --seeds-file")
	}

	var crawlSeeds []workflows.Seed
	if *seedsFile != "" {
		parsed, err := seeds.ParseFile(*seedsFile)
		if err != nil {
			log.Fatalf("parse seeds file: %v", err)
		}
		for _, s := range parsed {
			crawlSeeds = append(crawlSeeds, workflows.Seed{URL: s.URL, Category: s.Category, Priority: s.Priority})
		}
	} else {
		for _, u := range strings.Split(*seedsFlag, ",") {
			u = strings.TrimSpace(u)
			if u == "" {
				continue
			}
			crawlSeeds = append(crawlSeeds, workflows.Seed{URL: u, Category: *category, Priority: *priority})
		}
		if len(crawlSeeds) == 0 {
			log.Fatal("--seeds contained no URLs")
		}
	}

	effConcurrency := *concurrency
	if effConcurrency <= 0 {
		effConcurrency = autoConcurrency(len(crawlSeeds))
		log.Printf("auto-scaling concurrency to %d for %d seed URL(s)", effConcurrency, len(crawlSeeds))
	}

	id := *workflowID
	if id == "" {
		id = fmt.Sprintf("crawl-%s-%d", strings.ReplaceAll(crawlSeeds[0].URL, "/", "_"), time.Now().Unix())
	}

	c, err := client.Dial(client.Options{HostPort: *hostPort, Namespace: *namespace})
	if err != nil {
		log.Fatalf("connect to temporal at %s: %v", *hostPort, err)
	}
	defer c.Close()

	input := workflows.CrawlWorkflowInput{
		Seeds:                crawlSeeds,
		MaxDepth:             *maxDepth,
		MaxPages:             *maxPages,
		Concurrency:          effConcurrency,
		SameHostOnly:         *sameHost,
		MaxPagesPerDomain:    *maxPerDomain,
		MaxConcurrentPerHost: *maxPerHost,
		RevisitAfter:         *revisitAfter,
		CountryFilter:        strings.ToUpper(strings.TrimSpace(*countryFilter)),
	}

	startOpts := client.StartWorkflowOptions{
		ID:        id,
		TaskQueue: workflows.TaskQueueName,
	}
	if *cron != "" {
		startOpts.CronSchedule = *cron
	}

	run, err := c.ExecuteWorkflow(context.Background(), startOpts, workflows.CrawlWorkflow, input)
	if err != nil {
		log.Fatalf("start workflow: %v", err)
	}

	log.Printf("crawl started: workflow_id=%s run_id=%s seed_count=%d", run.GetID(), run.GetRunID(), len(crawlSeeds))
	log.Printf("inspect with: temporal workflow describe --workflow-id %s", run.GetID())

	if *cron != "" {
		// A cron workflow recurs indefinitely -- Get() would block until the
		// schedule itself is terminated, which defeats "runs automatically
		// in the background." Worker capacity (replicas/HPA) scales
		// independently of how this client exits.
		log.Printf("cron schedule active: %q -- Temporal will start a new CrawlWorkflow run on this schedule; this client can exit, the schedule persists on the Temporal server", *cron)
		return
	}

	if !*wait {
		return
	}

	var result workflows.CrawlResult
	if err := run.Get(context.Background(), &result); err != nil {
		log.Fatalf("crawl failed: %v", err)
	}

	log.Printf("crawl finished: fetched=%d succeeded=%d failed=%d skipped=%d domain_capped=%d country_filtered=%d",
		result.Stats.Fetched, result.Stats.Succeeded, result.Stats.Failed, result.Stats.Skipped, result.Stats.DomainCapped, result.Stats.CountryFiltered)
	if result.RunID != 0 {
		log.Printf("validation summary: GET /api/v1/crawl-runs/%d", result.RunID)
	}
}
