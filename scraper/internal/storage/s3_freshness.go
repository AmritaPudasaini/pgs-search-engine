package storage

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// s3HeadObjectAPI is the subset of the S3 client S3FreshnessChecker needs,
// so tests can supply a fake instead of talking to a real bucket /
// LocalStack.
type s3HeadObjectAPI interface {
	HeadObject(ctx context.Context, params *s3.HeadObjectInput, optFns ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
}

// S3FreshnessChecker implements FreshnessChecker against S3's "latest"
// index (see S3LatestObjectKey in s3_writer.go): a candidate URL is fresh
// if its latest-key object exists and was last modified more recently than
// `since`.
//
// Unlike Postgres's ListFreshDocumentURLs (one query covering every
// candidate in a batch), S3 has no batch-existence-check API, so this
// issues one HeadObject call per candidate, bounded to
// WithS3FreshnessConcurrency in flight at once. That's real added
// per-crawl latency and S3 API-call volume compared to the single-query
// Postgres path -- see docs/SCHEMA.md for the tradeoff written down.
type S3FreshnessChecker struct {
	client         s3HeadObjectAPI
	bucket         string
	keyPrefix      string
	headTimeout    time.Duration
	maxConcurrency int
}

// S3FreshnessOption configures NewS3FreshnessChecker.
type S3FreshnessOption func(*s3FreshnessConfig)

type s3FreshnessConfig struct {
	keyPrefix      string
	endpoint       string
	usePathStyle   bool
	maxRetries     int
	headTimeout    time.Duration
	maxConcurrency int
}

// WithS3FreshnessKeyPrefix mirrors WithS3KeyPrefix -- must match whatever
// prefix the S3Writer for the same bucket uses, or every HeadObject will
// miss.
func WithS3FreshnessKeyPrefix(prefix string) S3FreshnessOption {
	return func(c *s3FreshnessConfig) { c.keyPrefix = strings.Trim(prefix, "/") }
}

// WithS3FreshnessEndpoint mirrors WithS3Endpoint (LocalStack/MinIO).
func WithS3FreshnessEndpoint(endpoint string) S3FreshnessOption {
	return func(c *s3FreshnessConfig) {
		c.endpoint = endpoint
		c.usePathStyle = true
	}
}

// WithS3FreshnessMaxRetries overrides the client's retry attempts (default
// 5).
func WithS3FreshnessMaxRetries(n int) S3FreshnessOption {
	return func(c *s3FreshnessConfig) { c.maxRetries = n }
}

// WithS3FreshnessHeadTimeout overrides the per-candidate HeadObject timeout
// (default 10s).
func WithS3FreshnessHeadTimeout(d time.Duration) S3FreshnessOption {
	return func(c *s3FreshnessConfig) { c.headTimeout = d }
}

// WithS3FreshnessConcurrency caps how many HeadObject calls run at once for
// a single FreshURLs batch (default 20). Too high risks throttling on a
// large batch; too low makes a large candidate batch slow.
func WithS3FreshnessConcurrency(n int) S3FreshnessOption {
	return func(c *s3FreshnessConfig) { c.maxConcurrency = n }
}

// NewS3FreshnessChecker builds an S3FreshnessChecker against bucket using
// cfg (already loaded by the caller, same convention as NewS3Writer).
func NewS3FreshnessChecker(cfg aws.Config, bucket string, opts ...S3FreshnessOption) (*S3FreshnessChecker, error) {
	if bucket == "" {
		return nil, fmt.Errorf("s3: bucket is required")
	}
	c := &s3FreshnessConfig{maxRetries: 5, headTimeout: 10 * time.Second, maxConcurrency: 20}
	for _, opt := range opts {
		opt(c)
	}
	if c.maxConcurrency < 1 {
		c.maxConcurrency = 1
	}

	client := s3.NewFromConfig(cfg, func(o *s3.Options) {
		o.Retryer = retry.NewStandard(func(ro *retry.StandardOptions) {
			ro.MaxAttempts = c.maxRetries
		})
		if c.endpoint != "" {
			o.BaseEndpoint = aws.String(c.endpoint)
		}
		o.UsePathStyle = c.usePathStyle
	})

	return &S3FreshnessChecker{
		client:         client,
		bucket:         bucket,
		keyPrefix:      c.keyPrefix,
		headTimeout:    c.headTimeout,
		maxConcurrency: c.maxConcurrency,
	}, nil
}

func (c *S3FreshnessChecker) prefixed(key string) string {
	if c.keyPrefix != "" {
		return c.keyPrefix + "/" + key
	}
	return key
}

// FreshURLs implements FreshnessChecker. See the type's doc comment for why
// this is one HeadObject per candidate rather than a batch query. A
// candidate whose HeadObject fails for any reason other than "the object
// doesn't exist yet" (throttling, timeout, ...) is treated as not fresh
// (the safe default -- fetch it) rather than failing the whole batch: one
// candidate's transient error shouldn't discard every other candidate's
// successful lookup in the same call, and the workflow-level caller
// (crawl_workflow.go's checkFreshness) already falls back to "fetch
// everything" only on a whole-call error, not a per-URL one.
func (c *S3FreshnessChecker) FreshURLs(ctx context.Context, normalizedURLs []string, since time.Time) (map[string]bool, error) {
	if len(normalizedURLs) == 0 {
		return nil, nil
	}

	var (
		mu    sync.Mutex
		fresh = make(map[string]bool)
		wg    sync.WaitGroup
		sem   = make(chan struct{}, c.maxConcurrency)
	)

	for _, u := range normalizedURLs {
		wg.Add(1)
		sem <- struct{}{}
		go func(u string) {
			defer wg.Done()
			defer func() { <-sem }()

			hctx, cancel := context.WithTimeout(ctx, c.headTimeout)
			defer cancel()

			out, err := c.client.HeadObject(hctx, &s3.HeadObjectInput{
				Bucket: aws.String(c.bucket),
				Key:    aws.String(c.prefixed(S3LatestObjectKey(u))),
			})
			if err != nil {
				return // not found, or a transient error -- either way, not fresh
			}
			if out.LastModified != nil && !out.LastModified.Before(since) {
				mu.Lock()
				fresh[u] = true
				mu.Unlock()
			}
		}(u)
	}
	wg.Wait()

	return fresh, nil
}
