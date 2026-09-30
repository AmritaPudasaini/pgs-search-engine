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

// S3Writer writes each crawled Document as a JSON object to S3. Keys are
// content-addressed -- S3ObjectKey(doc.CrawlRunID, doc.NormalizedURL) -- so
// concurrent worker replicas writing the same document overwrite the same
// key with identical bytes: no central DB is needed for replica-safe
// dedupe (see docs/TASK-SPLIT-search-engine-scraper.md). Safe for
// concurrent use: the underlying S3 client is.
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
// of every object key, ahead of the crawl_run_id segment: "<prefix>/<crawl
// run id>/<hash>.json" instead of "<crawl_run_id>/<hash>.json". Useful for
// sharing one bucket across environments.
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

// S3ObjectKey derives the content-addressed key a Document with the given
// crawl run ID and normalized URL is written to. Exported so the read API
// (internal/api) can key its own lookups the same way without duplicating
// the hash scheme.
func S3ObjectKey(crawlRunID int64, normalizedURL string) string {
	sum := sha256.Sum256([]byte(normalizedURL))
	return fmt.Sprintf("%d/%s.json", crawlRunID, hex.EncodeToString(sum[:]))
}

func (w *S3Writer) objectKey(doc *model.Document) string {
	key := S3ObjectKey(doc.CrawlRunID, doc.NormalizedURL)
	if w.keyPrefix != "" {
		return w.keyPrefix + "/" + key
	}
	return key
}

// Write marshals doc as JSON and PUTs it to its content-addressed key (see
// S3ObjectKey). Throttling/transient errors are retried by the client's
// configured Retryer (see WithS3MaxRetries); Write only returns once every
// retry is exhausted.
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

	key := w.objectKey(doc)
	if _, err := w.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(w.bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("application/json"),
	}); err != nil {
		return fmt.Errorf("put %s to s3://%s/%s: %w", doc.URL, w.bucket, key, err)
	}
	return nil
}

// Close is a no-op: the S3 client owns no per-writer resource (connections
// are pooled by the underlying http.Client) that needs releasing.
func (w *S3Writer) Close() error { return nil }
