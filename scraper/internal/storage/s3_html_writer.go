package storage

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"search-engine-scraper/internal/model"
)

// S3HTMLWriter uploads each fetched page's complete, unmodified HTML body to
// S3 as its own object. Nothing about the page is kept in a database: the
// object is the record, and the parsed metadata (see S3Writer) refers to it
// by content hash.
//
// Objects are keyed "<prefix>/html/<host>/<content_hash>.html". Keying by
// content hash makes SaveHTML idempotent (an activity retry rewrites the
// same key with identical bytes) and keeps every distinct version of a page.
type S3HTMLWriter struct {
	client     s3PutObjectAPI
	bucket     string
	keyPrefix  string
	putTimeout time.Duration
}

// NewS3HTMLWriter builds an S3HTMLWriter against bucket using cfg, with the
// same options as NewS3Writer (key prefix, endpoint, retries, timeout).
func NewS3HTMLWriter(cfg aws.Config, bucket string, opts ...S3WriterOption) (*S3HTMLWriter, error) {
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
	return &S3HTMLWriter{client: client, bucket: bucket, keyPrefix: c.keyPrefix, putTimeout: c.putTimeout}, nil
}

// S3HTMLObjectKey derives the key SaveHTML writes a page to, without the
// optional environment prefix.
func S3HTMLObjectKey(normalizedURL, contentHash string) string {
	host := "unknown-host"
	if u, err := url.Parse(normalizedURL); err == nil && u.Hostname() != "" {
		host = strings.ToLower(u.Hostname())
	}
	return "html/" + host + "/" + contentHash + ".html"
}

// SaveHTML implements HTMLWriter.
func (w *S3HTMLWriter) SaveHTML(normalizedURL, contentHash string, body []byte) error {
	if contentHash == "" {
		return fmt.Errorf("s3: html for %s has no content hash to key on", normalizedURL)
	}
	key := S3HTMLObjectKey(normalizedURL, contentHash)
	if w.keyPrefix != "" {
		key = w.keyPrefix + "/" + key
	}

	ctx, cancel := context.WithTimeout(context.Background(), w.putTimeout)
	defer cancel()

	if _, err := w.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(w.bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(body),
		ContentType: aws.String("text/html"),
		Metadata:    map[string]string{"source-url": url.PathEscape(normalizedURL)},
	}); err != nil {
		return fmt.Errorf("put html for %s to s3://%s/%s: %w", normalizedURL, w.bucket, key, err)
	}
	return nil
}

// RecordWriter saves a page's complete structured capture (model.PageRecord)
// and returns the key it was stored under.
type RecordWriter interface {
	SaveRecord(rec *model.PageRecord) (key string, err error)
}

// NoopRecordWriter discards records.
type NoopRecordWriter struct{}

func (NoopRecordWriter) SaveRecord(*model.PageRecord) (string, error) { return "", nil }

// S3RecordObjectKey derives the key a page's record is written to, without
// the optional environment prefix: "pages/<host>/<content_hash>.json".
func S3RecordObjectKey(host, contentHash string) string {
	if host == "" {
		host = "unknown-host"
	}
	return "pages/" + strings.ToLower(host) + "/" + contentHash + ".json"
}

// S3RecordWriter uploads PageRecords as JSON objects.
type S3RecordWriter struct {
	client     s3PutObjectAPI
	bucket     string
	keyPrefix  string
	putTimeout time.Duration
}

// NewS3RecordWriter builds an S3RecordWriter with the same options as
// NewS3Writer.
func NewS3RecordWriter(cfg aws.Config, bucket string, opts ...S3WriterOption) (*S3RecordWriter, error) {
	h, err := NewS3HTMLWriter(cfg, bucket, opts...)
	if err != nil {
		return nil, err
	}
	return &S3RecordWriter{client: h.client, bucket: h.bucket, keyPrefix: h.keyPrefix, putTimeout: h.putTimeout}, nil
}

// SaveRecord implements RecordWriter.
func (w *S3RecordWriter) SaveRecord(rec *model.PageRecord) (string, error) {
	if rec.ContentHash == "" {
		return "", fmt.Errorf("s3: record for %s has no content hash to key on", rec.URL)
	}
	data, err := json.Marshal(rec)
	if err != nil {
		return "", fmt.Errorf("marshal page record: %w", err)
	}
	key := S3RecordObjectKey(rec.Host, rec.ContentHash)
	full := key
	if w.keyPrefix != "" {
		full = w.keyPrefix + "/" + key
	}
	ctx, cancel := context.WithTimeout(context.Background(), w.putTimeout)
	defer cancel()
	if _, err := w.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(w.bucket),
		Key:         aws.String(full),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("application/json"),
	}); err != nil {
		return "", fmt.Errorf("put record for %s to s3://%s/%s: %w", rec.URL, w.bucket, full, err)
	}
	return key, nil
}
