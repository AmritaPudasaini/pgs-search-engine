package storage

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// s3RunRecorderAPI is the subset of the S3 client S3RunRecorder needs, so
// tests can supply a fake instead of talking to a real bucket / LocalStack.
type s3RunRecorderAPI interface {
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
}

// s3RunManifest is the JSON shape stored at S3RunManifestKey(runID) --
// {crawl_run_id}/_run.json -- the run-tracking equivalent of a
// crawl_runs row.
type s3RunManifest struct {
	RunID        int64     `json:"run_id"`
	Status       string    `json:"status"` // "running", "completed", or "failed"
	SeedCount    int       `json:"seed_count"`
	MaxDepth     int       `json:"max_depth"`
	MaxPages     int       `json:"max_pages"`
	Fetched      int       `json:"fetched"`
	Succeeded    int       `json:"succeeded"`
	Failed       int       `json:"failed"`
	Skipped      int       `json:"skipped"`
	DomainCapped int       `json:"domain_capped"`
	Error        string    `json:"error,omitempty"`
	StartedAt    time.Time `json:"started_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

// S3RunManifestKey derives the key a run's manifest object is stored at.
// Exported so the read API (internal/api) can look up a single run's
// manifest, or list the run-manifest prefix, the same way.
func S3RunManifestKey(runID int64) string {
	return fmt.Sprintf("%d/_run.json", runID)
}

// S3RunRecorder implements RunRecorder by read-modify-writing a JSON
// manifest object per run, guarded by S3's conditional-write support
// (If-Match/If-None-Match on ETag) so concurrent updates to the same run
// (e.g. two Continue-As-New segments racing, which shouldn't normally
// happen but isn't ruled out by anything upstream) don't silently lose one
// writer's update.
type S3RunRecorder struct {
	client      s3RunRecorderAPI
	bucket      string
	keyPrefix   string
	timeout     time.Duration
	maxCASRetry int
	now         func() time.Time
	newRunID    func() int64
}

// S3RunRecorderOption configures NewS3RunRecorder.
type S3RunRecorderOption func(*s3RunRecorderConfig)

type s3RunRecorderConfig struct {
	keyPrefix    string
	endpoint     string
	usePathStyle bool
	maxRetries   int
	timeout      time.Duration
}

// WithS3RunRecorderKeyPrefix mirrors WithS3KeyPrefix -- must match whatever
// prefix the S3Writer for the same bucket uses.
func WithS3RunRecorderKeyPrefix(prefix string) S3RunRecorderOption {
	return func(c *s3RunRecorderConfig) { c.keyPrefix = strings.Trim(prefix, "/") }
}

// WithS3RunRecorderEndpoint mirrors WithS3Endpoint (LocalStack/MinIO).
func WithS3RunRecorderEndpoint(endpoint string) S3RunRecorderOption {
	return func(c *s3RunRecorderConfig) {
		c.endpoint = endpoint
		c.usePathStyle = true
	}
}

// WithS3RunRecorderMaxRetries overrides the client's retry attempts for
// throttling and other retryable errors (default 5). Distinct from the
// optimistic-concurrency retry (a fixed 3 attempts on an ETag mismatch,
// not configurable -- see UpdateRunStats/FinishRun).
func WithS3RunRecorderMaxRetries(n int) S3RunRecorderOption {
	return func(c *s3RunRecorderConfig) { c.maxRetries = n }
}

// WithS3RunRecorderTimeout overrides the per-call timeout (default 15s).
func WithS3RunRecorderTimeout(d time.Duration) S3RunRecorderOption {
	return func(c *s3RunRecorderConfig) { c.timeout = d }
}

// NewS3RunRecorder builds an S3RunRecorder against bucket using cfg
// (already loaded by the caller, same convention as NewS3Writer).
func NewS3RunRecorder(cfg aws.Config, bucket string, opts ...S3RunRecorderOption) (*S3RunRecorder, error) {
	if bucket == "" {
		return nil, fmt.Errorf("s3: bucket is required")
	}
	c := &s3RunRecorderConfig{maxRetries: 5, timeout: 15 * time.Second}
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

	return &S3RunRecorder{
		client:      client,
		bucket:      bucket,
		keyPrefix:   c.keyPrefix,
		timeout:     c.timeout,
		maxCASRetry: 3,
		now:         time.Now,
		newRunID:    func() int64 { return time.Now().UnixNano() },
	}, nil
}

func (r *S3RunRecorder) prefixed(key string) string {
	if r.keyPrefix != "" {
		return r.keyPrefix + "/" + key
	}
	return key
}

// StartRun creates a new run's manifest object. Uses If-None-Match: "*" so
// a run-ID collision (newRunID isn't guaranteed globally unique, just
// unique enough in practice -- see its doc comment) is caught as a write
// conflict rather than silently overwriting an in-progress run's manifest.
func (r *S3RunRecorder) StartRun(ctx context.Context, in StartRunInput) (int64, error) {
	runID := r.newRunID()
	now := r.now()
	manifest := s3RunManifest{
		RunID:     runID,
		Status:    "running",
		SeedCount: in.SeedCount,
		MaxDepth:  in.MaxDepth,
		MaxPages:  in.MaxPages,
		StartedAt: now,
		UpdatedAt: now,
	}

	data, err := json.Marshal(manifest)
	if err != nil {
		return 0, fmt.Errorf("marshal run manifest: %w", err)
	}

	ctx, cancel := context.WithTimeout(ctx, r.timeout)
	defer cancel()

	key := r.prefixed(S3RunManifestKey(runID))
	if _, err := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(r.bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("application/json"),
		IfNoneMatch: aws.String("*"),
	}); err != nil {
		return 0, fmt.Errorf("create run manifest s3://%s/%s: %w", r.bucket, key, err)
	}
	return runID, nil
}

// UpdateRunStats read-modify-writes the run's manifest with progress
// stats, retrying on an ETag mismatch (another writer updated the manifest
// between this call's read and write) up to maxCASRetry times.
func (r *S3RunRecorder) UpdateRunStats(ctx context.Context, runID int64, stats RunStats) error {
	return r.updateManifest(ctx, runID, func(m *s3RunManifest) {
		m.Fetched = stats.Fetched
		m.Succeeded = stats.Succeeded
		m.Failed = stats.Failed
		m.Skipped = stats.Skipped
		m.DomainCapped = stats.DomainCapped
	})
}

// FinishRun read-modify-writes the run's manifest with its terminal status
// and final stats, with the same ETag-mismatch retry as UpdateRunStats.
func (r *S3RunRecorder) FinishRun(ctx context.Context, runID int64, status string, stats RunStats, errMsg string) error {
	return r.updateManifest(ctx, runID, func(m *s3RunManifest) {
		m.Status = status
		m.Fetched = stats.Fetched
		m.Succeeded = stats.Succeeded
		m.Failed = stats.Failed
		m.Skipped = stats.Skipped
		m.DomainCapped = stats.DomainCapped
		m.Error = errMsg
	})
}

func (r *S3RunRecorder) updateManifest(ctx context.Context, runID int64, mutate func(*s3RunManifest)) error {
	key := r.prefixed(S3RunManifestKey(runID))

	var lastErr error
	for attempt := 0; attempt < r.maxCASRetry; attempt++ {
		callCtx, cancel := context.WithTimeout(ctx, r.timeout)
		getOut, err := r.client.GetObject(callCtx, &s3.GetObjectInput{
			Bucket: aws.String(r.bucket),
			Key:    aws.String(key),
		})
		if err != nil {
			cancel()
			return fmt.Errorf("get run manifest s3://%s/%s: %w", r.bucket, key, err)
		}

		body, err := io.ReadAll(getOut.Body)
		getOut.Body.Close()
		if err != nil {
			cancel()
			return fmt.Errorf("read run manifest s3://%s/%s: %w", r.bucket, key, err)
		}

		var manifest s3RunManifest
		if err := json.Unmarshal(body, &manifest); err != nil {
			cancel()
			return fmt.Errorf("unmarshal run manifest s3://%s/%s: %w", r.bucket, key, err)
		}

		mutate(&manifest)
		manifest.UpdatedAt = r.now()

		data, err := json.Marshal(manifest)
		if err != nil {
			cancel()
			return fmt.Errorf("marshal run manifest: %w", err)
		}

		_, putErr := r.client.PutObject(callCtx, &s3.PutObjectInput{
			Bucket:      aws.String(r.bucket),
			Key:         aws.String(key),
			Body:        bytes.NewReader(data),
			ContentType: aws.String("application/json"),
			IfMatch:     getOut.ETag,
		})
		cancel()
		if putErr == nil {
			return nil
		}
		lastErr = putErr
		// Any PutObject failure here (not just an ETag mismatch) is worth
		// retrying via the read-modify-write loop: a fresh GetObject picks
		// up whatever the bucket's current state actually is before trying
		// again, which self-corrects a stale read either way.
	}
	return fmt.Errorf("update run manifest s3://%s/%s: exhausted %d attempts: %w", r.bucket, key, r.maxCASRetry, lastErr)
}
