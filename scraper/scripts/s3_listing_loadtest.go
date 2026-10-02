//go:build ignore

// Command s3_listing_loadtest seeds a bucket with a large number of
// Document-shaped objects under one crawl_run_id prefix, then paginates
// through them with ListObjectsV2, timing seed throughput and pagination
// latency -- Person 4 checklist item 9
// (docs/TASK-SPLIT-search-engine-scraper.md).
//
// Not run against a real bucket as part of this branch: no LocalStack
// service exists yet in docker-compose.yml (Person 1's item 3), and no AWS
// CLI/LocalStack was available in the environment this was written in. See
// docs/SCHEMA.md's "Load-test plan" section for the run instructions and
// the extrapolation from a smaller measured run to the 1M-object scale the
// checklist item asks about.
//
// Usage (once a bucket -- real or LocalStack -- is reachable):
//
//	go run scripts/s3_listing_loadtest.go \
//	    -bucket my-bucket -run-id 999999 -count 10000 \
//	    -endpoint http://localhost:4566   # omit for real AWS S3
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

func main() {
	var (
		bucket   = flag.String("bucket", "", "S3 bucket to seed and list against (required)")
		runID    = flag.Int64("run-id", 999999, "crawl_run_id prefix to seed objects under")
		count    = flag.Int("count", 10000, "number of objects to seed before timing ListObjectsV2 pagination")
		endpoint = flag.String("endpoint", "", "S3-compatible endpoint (e.g. http://localhost:4566 for LocalStack); empty = real AWS S3")
		seedConc = flag.Int("seed-concurrency", 50, "concurrent PutObject calls while seeding")
		skipSeed = flag.Bool("skip-seed", false, "skip seeding and just time pagination over whatever already exists at the prefix")
	)
	flag.Parse()

	if *bucket == "" {
		log.Fatal("-bucket is required")
	}

	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		log.Fatalf("load AWS config: %v", err)
	}

	client := s3.NewFromConfig(cfg, func(o *s3.Options) {
		if *endpoint != "" {
			o.BaseEndpoint = aws.String(*endpoint)
			o.UsePathStyle = true
		}
	})

	prefix := fmt.Sprintf("%d/", *runID)

	if !*skipSeed {
		fmt.Printf("seeding %d objects under s3://%s/%s ...\n", *count, *bucket, prefix)
		start := time.Now()
		seed(ctx, client, *bucket, prefix, *count, *seedConc)
		elapsed := time.Since(start)
		fmt.Printf("seeded %d objects in %s (%.1f objects/sec)\n\n", *count, elapsed, float64(*count)/elapsed.Seconds())
	}

	fmt.Printf("paginating s3://%s/%s with ListObjectsV2 (default MaxKeys=1000) ...\n", *bucket, prefix)
	start := time.Now()
	pages, total := paginate(ctx, client, *bucket, prefix)
	elapsed := time.Since(start)

	fmt.Printf("\nresults:\n")
	fmt.Printf("  objects listed:   %d\n", total)
	fmt.Printf("  pages:            %d\n", pages)
	fmt.Printf("  total time:       %s\n", elapsed)
	fmt.Printf("  avg per page:     %s\n", elapsed/time.Duration(max(pages, 1)))
	fmt.Printf("  extrapolated to 1,000,000 objects (linear in page count, same per-page latency): %s\n",
		elapsed/time.Duration(max(pages, 1))*time.Duration((1_000_000+999)/1000))
}

const loadtestBody = `{"url":"https://example.com/loadtest","normalized_url":"https://example.com/loadtest"}`

func seed(ctx context.Context, client *s3.Client, bucket, prefix string, count, concurrency int) {
	sem := make(chan struct{}, concurrency)
	done := make(chan error, count)

	for i := 0; i < count; i++ {
		i := i
		sem <- struct{}{}
		go func() {
			defer func() { <-sem }()
			key := fmt.Sprintf("%s%08d.json", prefix, i)
			_, err := client.PutObject(ctx, &s3.PutObjectInput{
				Bucket:      aws.String(bucket),
				Key:         aws.String(key),
				Body:        strings.NewReader(loadtestBody),
				ContentType: aws.String("application/json"),
			})
			done <- err
		}()
	}
	for i := 0; i < count; i++ {
		if err := <-done; err != nil {
			log.Printf("seed PutObject failed: %v", err)
		}
	}
}

func paginate(ctx context.Context, client *s3.Client, bucket, prefix string) (pages, total int) {
	var continuationToken *string
	for {
		out, err := client.ListObjectsV2(ctx, &s3.ListObjectsV2Input{
			Bucket:            aws.String(bucket),
			Prefix:            aws.String(prefix),
			ContinuationToken: continuationToken,
		})
		if err != nil {
			log.Fatalf("ListObjectsV2: %v", err)
		}
		pages++
		total += len(out.Contents)
		if !aws.ToBool(out.IsTruncated) {
			break
		}
		continuationToken = out.NextContinuationToken
	}
	return pages, total
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
