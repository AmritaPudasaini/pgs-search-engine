package storage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"search-engine-scraper/internal/model"
)

// s3PutObjectAPI is the subset of the S3 client S3Writer needs, so tests
// can supply a fake instead of talking to a real bucket / LocalStack.
type s3PutObjectAPI interface {
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

// S3Writer writes each crawled Document as a JSON object to S3, to two
// keys:
//
//   - S3ObjectKey(doc.CrawlRunID, doc.NormalizedURL) -- content-addressed
//     and scoped to the run that wrote it, so concurrent worker replicas
//     writing the same document within one run overwrite the same key with
//     identical bytes (no central DB needed for replica-safe dedupe), and
//     the API can list/filter documents by crawl_run_id via key prefix.
//   - S3LatestObjectKey(doc.NormalizedURL) -- content-addressed by URL
//     alone, independent of which run wrote it, always overwritten with
//     the most recent fetch. This is what makes freshness checking
//     possible at all: "was this URL fetched recently" has no single
//     stable key to HeadObject if every write lives under a per-run
//     prefix, since a URL's crawl_run_id isn't known in advance of
//     fetching it. See S3FreshnessChecker.
//
// Safe for concurrent use: the underlying S3 client is.
type S3Writer struct {
	client     s3PutObjectAPI
	bucket     string
	keyPrefix  string
	putTimeout time.Duration
}

// S3WriterOption configures NewS3Writer.
type S3WriterOption func(*s3WriterConfig)

type s3WriterConfig struct {
	keyPrefix    string
	endpoint     string
	usePathStyle bool
	maxRetries   int
	putTimeout   time.Duration
}

// WithS3KeyPrefix adds a fixed prefix (e.g. an environment name) in front
// of every object key, ahead of the crawl_run_id/"latest" segment:
// "<prefix>/<crawl_run_id>/<hash>.json" instead of
// "<crawl_run_id>/<hash>.json". Useful for sharing one bucket across
// environments.
func WithS3KeyPrefix(prefix string) S3WriterOption {
	return func(c *s3WriterConfig) { c.keyPrefix = strings.Trim(prefix, "/") }
}

// WithS3Endpoint points the client at an S3-compatible endpoint (e.g.
// LocalStack or MinIO for local dev) instead of real AWS S3, and switches
// to path-style addressing, which those emulators require.
func WithS3Endpoint(endpoint string) S3WriterOption {
	return func(c *s3WriterConfig) {
		c.endpoint = endpoint
		c.usePathStyle = true
	}
}

// WithS3MaxRetries overrides the client's retry attempts for throttling and
// other retryable errors (default 5).
func WithS3MaxRetries(n int) S3WriterOption {
	return func(c *s3WriterConfig) { c.maxRetries = n }
}

// WithS3PutTimeout overrides the per-object PutObject timeout (default
// 30s).
func WithS3PutTimeout(d time.Duration) S3WriterOption {
	return func(c *s3WriterConfig) { c.putTimeout = d }
}

// NewS3Writer builds an S3Writer against bucket using cfg (already loaded
// by the caller, e.g. via config.LoadDefaultConfig, so this package
// doesn't own credential/region resolution).
func NewS3Writer(cfg aws.Config, bucket string, opts ...S3WriterOption) (*S3Writer, error) {
	if bucket == "" {
		return nil, fmt.Errorf("s3: bucket is required")
	}
	c := &s3WriterConfig{maxRetries: 5, putTimeout: 30 * time.Second}
	for _, opt := range opts {
		opt(c)
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

	return &S3Writer{
		client:     client,
		bucket:     bucket,
		keyPrefix:  c.keyPrefix,
		putTimeout: c.putTimeout,
	}, nil
}

// s3URLHash is the hash component shared by S3ObjectKey and
// S3LatestObjectKey -- kept as one function so the two key schemes can
// never drift apart on how a URL is hashed.
func s3URLHash(normalizedURL string) string {
	sum := sha256.Sum256([]byte(normalizedURL))
	return hex.EncodeToString(sum[:])
}

// S3ObjectKey derives the content-addressed, run-scoped key a Document
// with the given crawl run ID and normalized URL is written to. Exported
// so the read API (internal/api) can key its own lookups the same way
// without duplicating the hash scheme.
func S3ObjectKey(crawlRunID int64, normalizedURL string) string {
	return fmt.Sprintf("%d/%s.json", crawlRunID, s3URLHash(normalizedURL))
}

// S3LatestObjectKey derives the content-addressed, run-independent key
// that always holds a URL's most recently written Document -- see
// S3Writer's doc comment for why this exists alongside S3ObjectKey.
func S3LatestObjectKey(normalizedURL string) string {
	return "latest/" + s3URLHash(normalizedURL) + ".json"
}

func (w *S3Writer) prefixed(key string) string {
	if w.keyPrefix != "" {
		return w.keyPrefix + "/" + key
	}
	return key
}

// Write marshals doc as JSON once and PUTs it to both its run-scoped key
// (S3ObjectKey) and its latest key (S3LatestObjectKey). Throttling/
// transient errors are retried by the client's configured Retryer (see
// WithS3MaxRetries); Write only returns once every retry on a given PUT is
// exhausted. If the run-scoped PUT succeeds but the latest PUT fails, Write
// still returns an error (the freshness index would otherwise silently
// fall behind) even though the document is safely durable under its
// run-scoped key -- a retried WriteDocument activity re-PUTs both keys
// with identical bytes, which is a no-op, not a duplicate.
func (w *S3Writer) Write(doc *model.Document) error {
	if doc.NormalizedURL == "" {
		return fmt.Errorf("s3: document %s has no normalized_url to key on", doc.URL)
	}

	data, err := json.Marshal(doc)
	if err != nil {
		return fmt.Errorf("marshal document: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), w.putTimeout)
	defer cancel()

	runKey := w.prefixed(S3ObjectKey(doc.CrawlRunID, doc.NormalizedURL))
	if _, err := w.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(w.bucket),
		Key:         aws.String(runKey),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("application/json"),
	}); err != nil {
		return fmt.Errorf("put %s to s3://%s/%s: %w", doc.URL, w.bucket, runKey, err)
	}

	latestKey := w.prefixed(S3LatestObjectKey(doc.NormalizedURL))
	if _, err := w.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(w.bucket),
		Key:         aws.String(latestKey),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("application/json"),
	}); err != nil {
		return fmt.Errorf("put %s to s3://%s/%s (latest index): %w", doc.URL, w.bucket, latestKey, err)
	}

	return nil
}

// Close is a no-op: the S3 client owns no per-writer resource (connections
// are pooled by the underlying http.Client) that needs releasing.
func (w *S3Writer) Close() error { return nil }
