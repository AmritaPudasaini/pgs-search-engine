package storage

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"search-engine-scraper/internal/model"
)

// fakeS3PutObjectAPI records PutObject calls without touching a real
// bucket, so S3Writer's key derivation and body encoding can be tested
// without LocalStack.
type fakeS3PutObjectAPI struct {
	lastInput *s3.PutObjectInput
	err       error
	calls     int
}

func (f *fakeS3PutObjectAPI) PutObject(_ context.Context, in *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	f.calls++
	if f.err != nil {
		return nil, f.err
	}
	f.lastInput = in
	return &s3.PutObjectOutput{}, nil
}

func TestS3Writer_WriteKeysByCrawlRunAndNormalizedURLHash(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	doc := &model.Document{
		URL:           "https://example.com/a?utm_source=x",
		NormalizedURL: "https://example.com/a",
		CrawlRunID:    42,
		Title:         "A",
	}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write: %v", err)
	}

	wantKey := S3ObjectKey(42, "https://example.com/a")
	if got := aws.ToString(fake.lastInput.Key); got != wantKey {
		t.Errorf("Key = %q, want %q", got, wantKey)
	}
	if got := aws.ToString(fake.lastInput.Bucket); got != "docs-bucket" {
		t.Errorf("Bucket = %q, want %q", got, "docs-bucket")
	}
	if got := aws.ToString(fake.lastInput.ContentType); got != "application/json" {
		t.Errorf("ContentType = %q, want application/json", got)
	}

	body, err := io.ReadAll(fake.lastInput.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	var got model.Document
	if err := json.Unmarshal(body, &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if got.NormalizedURL != doc.NormalizedURL || got.Title != doc.Title {
		t.Errorf("body = %+v, want NormalizedURL/Title matching %+v", got, doc)
	}
}

func TestS3Writer_WriteSameDocumentTwiceUsesSameKey(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	doc := &model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 1}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write (first): %v", err)
	}
	firstKey := aws.ToString(fake.lastInput.Key)

	if err := w.Write(doc); err != nil {
		t.Fatalf("Write (second): %v", err)
	}
	secondKey := aws.ToString(fake.lastInput.Key)

	if firstKey != secondKey {
		t.Errorf("keys differ across identical writes: %q vs %q, want replica-safe overwrite of the same key", firstKey, secondKey)
	}
	if fake.calls != 2 {
		t.Errorf("calls = %d, want 2", fake.calls)
	}
}

func TestS3Writer_WriteWithKeyPrefixPrependsPrefix(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", keyPrefix: "staging", putTimeout: time.Second}

	doc := &model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 7}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write: %v", err)
	}

	want := "staging/" + S3ObjectKey(7, "https://example.com/a")
	if got := aws.ToString(fake.lastInput.Key); got != want {
		t.Errorf("Key = %q, want %q", got, want)
	}
}

func TestS3Writer_WriteRejectsEmptyNormalizedURL(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	if err := w.Write(&model.Document{URL: "https://example.com/a"}); err == nil {
		t.Fatal("Write with empty NormalizedURL: got nil error, want one")
	}
	if fake.calls != 0 {
		t.Errorf("calls = %d, want 0 (should reject before calling S3)", fake.calls)
	}
}

func TestS3Writer_WritePropagatesClientError(t *testing.T) {
	fake := &fakeS3PutObjectAPI{err: errors.New("throttled")}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	err := w.Write(&model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a"})
	if err == nil {
		t.Fatal("Write: got nil error, want propagated client error")
	}
}

func TestS3Writer_CloseIsANoop(t *testing.T) {
	w := &S3Writer{}
	if err := w.Close(); err != nil {
		t.Errorf("Close: %v, want nil", err)
	}
}

func TestS3ObjectKey_DifferentURLsDifferentKeys(t *testing.T) {
	a := S3ObjectKey(1, "https://example.com/a")
	b := S3ObjectKey(1, "https://example.com/b")
	if a == b {
		t.Errorf("S3ObjectKey collided for different URLs: %q", a)
	}
}

func TestS3ObjectKey_SameURLDifferentRunsDifferentKeys(t *testing.T) {
	a := S3ObjectKey(1, "https://example.com/a")
	b := S3ObjectKey(2, "https://example.com/a")
	if a == b {
		t.Errorf("S3ObjectKey collided across different crawl runs: %q", a)
	}
}
