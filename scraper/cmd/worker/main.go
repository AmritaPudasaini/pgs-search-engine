// Command worker runs a Temporal worker that executes CrawlWorkflow and its
// activities. This is where actual concurrency and scale-out happen:
//   - within one process, up to --max-concurrent-activities activities run
//     as concurrent goroutines (the Temporal SDK's activity worker pool) --
//     it defaults to a large, CPU-count-scaled number since fetching is
//     I/O-bound, not CPU-bound (see maxConcurrentDefault below);
//   - horizontally, run this binary multiple times (same task queue,
//     same/different machines/pods) and Temporal load-balances activity and
//     workflow tasks across all of them automatically -- this is the knob
//     Docker/Kubernetes scale with (docker compose --scale, a Deployment's
//     replica count or HPA).
//
// Every flag can also be set via an environment variable of the same name
// (upper-cased, dashes to underscores, e.g. --database-url ==
// DATABASE_URL), which is how the Docker/Kubernetes deployment configures
// this binary without a wrapper script.
package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"runtime"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	_ "go.uber.org/automaxprocs" // sets GOMAXPROCS from the container's cgroup CPU quota, not the host's core count

	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"

	"search-engine-scraper/internal/activities"
	"search-engine-scraper/internal/envflag"
	"search-engine-scraper/internal/fetcher"
	"search-engine-scraper/internal/robots"
	"search-engine-scraper/internal/storage"
	"search-engine-scraper/internal/workflows"
)

func main() {
	var (
		hostPort       = envflag.String("temporal-address", "localhost:7233", "Temporal frontend address")
		namespace      = envflag.String("namespace", "default", "Temporal namespace")
		storageKind    = envflag.String("storage", "ndjson", "where to write crawled documents: ndjson, postgres, or kafka")
		output         = envflag.String("output", "data/output/documents.ndjson", "NDJSON output path (used when --storage=ndjson)")
		databaseURL    = envflag.String("database-url", "", "Postgres connection string (used when --storage=postgres), e.g. postgres://user:pass@host:5432/scraper")
		kafkaBrokers   = envflag.String("kafka-brokers", "", "comma-separated Kafka broker addresses, e.g. kafka-1:9092,kafka-2:9092 (used when --storage=kafka)")
		kafkaTopic     = envflag.String("kafka-topic", "crawled-documents", "Kafka topic to publish crawled documents to (used when --storage=kafka) -- the hand-off point to the ETL pipeline")
		requestTimeout = envflag.Duration("timeout", 10*time.Second, "per-request HTTP timeout")
		maxConcurrent  = envflag.Int("max-concurrent-activities", maxConcurrentDefault(), "max activities this worker process executes concurrently (fetching is I/O-bound, so this can safely exceed core count)")
		userAgent      = envflag.String("user-agent", "search-engine-scraper", "User-Agent / robots.txt group name to identify as")
		metricsAddress = envflag.String("metrics-address", ":9090", "address to serve Prometheus metrics on (GET /metrics); empty disables it")
		maxBandwidth   = envflag.Int("max-bandwidth-bytes-per-sec", 0, "cap this worker process's aggregate download rate in bytes/sec across all concurrent fetches (0 = unlimited)")
	)
	flag.Parse()

	if *metricsAddress != "" {
		mux := http.NewServeMux()
		mux.Handle("/metrics", promhttp.Handler())
		go func() {
			// Best-effort: a metrics-port conflict shouldn't take down the
			// crawler itself, just observability into it.
			if err := http.ListenAndServe(*metricsAddress, mux); err != nil {
				log.Printf("metrics server stopped: %v", err)
			}
		}()
		log.Printf("metrics: http://%s/metrics", *metricsAddress)
	}

	primary, err := buildWriter(*storageKind, *output, *databaseURL, *kafkaBrokers, *kafkaTopic)
	if err != nil {
		log.Fatalf("open storage writer: %v", err)
	}
	// runRecorder/freshnessChecker must be derived from primary before it's
	// potentially wrapped in a MultiWriter below -- MultiWriter doesn't
	// itself implement storage.RunRecorder/FreshnessChecker, only whichever
	// single backend (Postgres) actually does.
	runs := runRecorder(primary)
	freshness := freshnessChecker(primary)

	writer := primary
	if *storageKind != "kafka" && *kafkaBrokers != "" {
		// Fan out to Kafka in addition to the primary backend, so the ETL
		// team gets a live document stream even when the primary store
		// (Postgres/NDJSON) is what the crawler's own API/tooling reads.
		kw, err := storage.NewKafkaWriter(storage.ParseBrokers(*kafkaBrokers), *kafkaTopic)
		if err != nil {
			log.Fatalf("open kafka writer: %v", err)
		}
		writer = storage.NewMultiWriter(primary, kw)
	}
	defer writer.Close()

	c, err := client.Dial(client.Options{HostPort: *hostPort, Namespace: *namespace})
	if err != nil {
		log.Fatalf("connect to temporal at %s: %v", *hostPort, err)
	}
	defer c.Close()

	f := fetcher.New(*requestTimeout, *maxBandwidth)
	guard := robots.New(f, *userAgent)
	act := activities.New(f, guard, writer, runs, freshness)

	w := worker.New(c, workflows.TaskQueueName, worker.Options{
		MaxConcurrentActivityExecutionSize: *maxConcurrent,
	})
	w.RegisterWorkflow(workflows.CrawlWorkflow)
	w.RegisterActivity(act.ProcessPage)
	w.RegisterActivity(act.WriteDocument)
	w.RegisterActivity(act.DiscoverSitemapURLs)
	w.RegisterActivity(act.CheckFreshness)
	w.RegisterActivity(act.StartCrawlRun)
	w.RegisterActivity(act.UpdateCrawlRunStats)
	w.RegisterActivity(act.FinishCrawlRun)

	log.Printf("worker started: task_queue=%s temporal=%s storage=%s gomaxprocs=%d max_concurrent_activities=%d max_bandwidth_bytes_per_sec=%d",
		workflows.TaskQueueName, *hostPort, *storageKind, runtime.GOMAXPROCS(0), *maxConcurrent, *maxBandwidth)

	if err := w.Run(worker.InterruptCh()); err != nil {
		log.Fatalf("worker stopped: %v", err)
	}
}

// maxConcurrentDefault scales with visible CPU count so a container given
// more CPU automatically fans out more concurrent fetches without a manual
// flag per deployment size. 100x is aggressive on purpose: ProcessPage
// activities spend almost all their time blocked on network I/O, so far
// more of them can be in flight than there are cores -- the real ceiling is
// the target sites' response times and robots.txt Crawl-delay, not CPU.
func maxConcurrentDefault() int {
	return runtime.NumCPU() * 100
}

// runRecorder returns writer itself when it's Postgres-backed (it already
// implements storage.RunRecorder on the same pool), or a no-op when running
// with --storage=ndjson, which has no database to track crawl runs in.
func runRecorder(writer storage.Writer) storage.RunRecorder {
	if pg, ok := writer.(storage.RunRecorder); ok {
		return pg
	}
	return storage.NoopRunRecorder{}
}

// freshnessChecker returns writer itself when it's Postgres-backed (it
// already implements storage.FreshnessChecker on the same pool), or a
// no-op when running with --storage=ndjson, which has no queryable history
// to check freshness against.
func freshnessChecker(writer storage.Writer) storage.FreshnessChecker {
	if pg, ok := writer.(storage.FreshnessChecker); ok {
		return pg
	}
	return storage.NoopFreshnessChecker{}
}

func buildWriter(kind, output, databaseURL, kafkaBrokers, kafkaTopic string) (storage.Writer, error) {
	switch kind {
	case "ndjson":
		return storage.NewNDJSONWriter(output)
	case "postgres":
		if databaseURL == "" {
			log.Fatal("--database-url (or DATABASE_URL) is required when --storage=postgres")
		}
		return storage.NewPostgresWriter(context.Background(), databaseURL)
	case "kafka":
		if kafkaBrokers == "" {
			log.Fatal("--kafka-brokers (or KAFKA_BROKERS) is required when --storage=kafka")
		}
		return storage.NewKafkaWriter(storage.ParseBrokers(kafkaBrokers), kafkaTopic)
	default:
		log.Fatalf("unknown --storage %q: must be ndjson, postgres, or kafka", kind)
		return nil, nil
	}
}
