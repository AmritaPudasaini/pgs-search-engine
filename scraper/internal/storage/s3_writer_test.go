package storage

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"search-engine-scraper/internal/model"
)

// fakeS3PutObjectAPI records every PutObject call without touching a real
// bucket, so S3Writer's key derivation and body encoding can be tested
// without LocalStack. Write does two PUTs per document (run-scoped +
// latest), so this records all of them rather than just the last.
type fakeS3PutObjectAPI struct {
	inputs []*s3.PutObjectInput
	// errOnKey, if non-empty, makes PutObject fail only for that exact key
	// -- lets a test target one of the two PUTs Write issues.
	errOnKey string
	err      error
}

func (f *fakeS3PutObjectAPI) PutObject(_ context.Context, in *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	if f.err != nil && (f.errOnKey == "" || aws.ToString(in.Key) == f.errOnKey) {
		return nil, f.err
	}
	f.inputs = append(f.inputs, in)
	return &s3.PutObjectOutput{}, nil
}

func (f *fakeS3PutObjectAPI) keys() []string {
	keys := make([]string, len(f.inputs))
	for i, in := range f.inputs {
		keys[i] = aws.ToString(in.Key)
	}
	return keys
}

func TestS3Writer_WriteKeysRunScopedAndLatest(t *testing.T) {
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

	if len(fake.inputs) != 2 {
		t.Fatalf("PutObject called %d times, want 2 (run-scoped + latest)", len(fake.inputs))
	}

	wantRunKey := S3ObjectKey(42, "https://example.com/a")
	wantLatestKey := S3LatestObjectKey("https://example.com/a")
	gotKeys := fake.keys()
	if gotKeys[0] != wantRunKey {
		t.Errorf("first PUT key = %q, want run-scoped key %q", gotKeys[0], wantRunKey)
	}
	if gotKeys[1] != wantLatestKey {
		t.Errorf("second PUT key = %q, want latest key %q", gotKeys[1], wantLatestKey)
	}

	for _, in := range fake.inputs {
		if got := aws.ToString(in.Bucket); got != "docs-bucket" {
			t.Errorf("Bucket = %q, want %q", got, "docs-bucket")
		}
		if got := aws.ToString(in.ContentType); got != "application/json" {
			t.Errorf("ContentType = %q, want application/json", got)
		}
	}

	body, err := io.ReadAll(fake.inputs[0].Body)
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

func TestS3Writer_WriteSameDocumentTwiceUsesSameKeys(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	doc := &model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 1}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write (first): %v", err)
	}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write (second): %v", err)
	}

	keys := fake.keys()
	if len(keys) != 4 {
		t.Fatalf("PutObject called %d times across two writes, want 4", len(keys))
	}
	if keys[0] != keys[2] {
		t.Errorf("run-scoped keys differ across identical writes: %q vs %q, want replica-safe overwrite of the same key", keys[0], keys[2])
	}
	if keys[1] != keys[3] {
		t.Errorf("latest keys differ across identical writes: %q vs %q, want replica-safe overwrite of the same key", keys[1], keys[3])
	}
}

// TestS3Writer_LatestKeyIsRunIndependent proves the same URL written under
// two different crawl runs converges on the SAME latest key (unlike the
// run-scoped key, which differs per run) -- this is what makes it usable
// as a freshness index across runs.
func TestS3Writer_LatestKeyIsRunIndependent(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	if err := w.Write(&model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 1}); err != nil {
		t.Fatalf("Write (run 1): %v", err)
	}
	if err := w.Write(&model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 2}); err != nil {
		t.Fatalf("Write (run 2): %v", err)
	}

	keys := fake.keys()
	runKey1, latestKey1 := keys[0], keys[1]
	runKey2, latestKey2 := keys[2], keys[3]

	if runKey1 == runKey2 {
		t.Errorf("run-scoped keys should differ across runs: both %q", runKey1)
	}
	if latestKey1 != latestKey2 {
		t.Errorf("latest keys should be identical across runs for the same URL: %q vs %q", latestKey1, latestKey2)
	}
}

func TestS3Writer_WriteWithKeyPrefixPrependsPrefixToBothKeys(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", keyPrefix: "staging", putTimeout: time.Second}

	doc := &model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 7}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write: %v", err)
	}

	keys := fake.keys()
	wantRunKey := "staging/" + S3ObjectKey(7, "https://example.com/a")
	wantLatestKey := "staging/" + S3LatestObjectKey("https://example.com/a")
	if keys[0] != wantRunKey {
		t.Errorf("run-scoped key = %q, want %q", keys[0], wantRunKey)
	}
	if keys[1] != wantLatestKey {
		t.Errorf("latest key = %q, want %q", keys[1], wantLatestKey)
	}
}

func TestS3Writer_WriteRejectsEmptyNormalizedURL(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	if err := w.Write(&model.Document{URL: "https://example.com/a"}); err == nil {
		t.Fatal("Write with empty NormalizedURL: got nil error, want one")
	}
	if len(fake.inputs) != 0 {
		t.Errorf("PutObject called %d times, want 0 (should reject before calling S3)", len(fake.inputs))
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

// TestS3Writer_WriteFailsIfLatestPutFails proves a failure on just the
// second (latest-index) PUT still surfaces as a Write error -- the
// document is durably written under its run-scoped key at that point, but
// silently leaving the freshness index stale would be a worse failure mode
// than a retried WriteDocument activity.
func TestS3Writer_WriteFailsIfLatestPutFails(t *testing.T) {
	doc := &model.Document{URL: "https://example.com/a", NormalizedURL: "https://example.com/a", CrawlRunID: 3}
	fake := &fakeS3PutObjectAPI{err: errors.New("throttled"), errOnKey: S3LatestObjectKey(doc.NormalizedURL)}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	if err := w.Write(doc); err == nil {
		t.Fatal("Write: got nil error, want the latest-index PUT's error surfaced")
	}
	if len(fake.inputs) != 1 {
		t.Errorf("PutObject recorded %d successful calls, want 1 (the run-scoped PUT that did succeed)", len(fake.inputs))
	}
}

// TestS3Writer_WriteHandlesNilSliceFields proves a Document with every
// slice field left nil (Links, AnchorTexts, JSONLD, Headings, SimHashes --
// the common case: a page with no links, no JSON-LD, no anchor text)
// marshals and writes cleanly. Unlike Postgres's nonNilStrings coalescing
// (needed because pgx sends a nil Go slice as SQL NULL against a NOT NULL
// TEXT[] column), S3 has no schema to violate here -- this documents that
// no equivalent coalescing is needed for the S3 path, not that one was
// added.
func TestS3Writer_WriteHandlesNilSliceFields(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	doc := &model.Document{
		URL: "https://example.com/a", NormalizedURL: "https://example.com/a",
		Links: nil, AnchorTexts: nil, JSONLD: nil, Headings: nil,
	}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write with nil slice fields: %v", err)
	}

	body, err := io.ReadAll(fake.inputs[0].Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	if !json.Valid(body) {
		t.Fatalf("body is not valid JSON: %s", body)
	}
}

// TestS3Writer_WriteHandlesEmptyJSONLD is the non-nil counterpart: an
// empty (but non-nil) JSONLD slice, and one containing an empty JSON
// object string -- both valid, both should round-trip.
func TestS3Writer_WriteHandlesEmptyJSONLD(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	doc := &model.Document{
		URL: "https://example.com/a", NormalizedURL: "https://example.com/a",
		JSONLD: []string{"{}"},
	}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write with empty JSON-LD: %v", err)
	}

	body, err := io.ReadAll(fake.inputs[0].Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	var got model.Document
	if err := json.Unmarshal(body, &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if len(got.JSONLD) != 1 || got.JSONLD[0] != "{}" {
		t.Errorf("JSONLD = %v, want [\"{}\"]", got.JSONLD)
	}
}

// TestS3Writer_WriteHandlesOversizedDocument proves a Document whose Text
// is much larger than a typical page (several MB) still marshals and PUTs
// without truncation -- S3's PutObject has no practical size limit for a
// crawled page's worth of text (single-PUT objects up to 5GB), unlike a
// hypothetical fixed-size buffer bug.
func TestS3Writer_WriteHandlesOversizedDocument(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	bigText := strings.Repeat("a", 5*1024*1024) // 5MB
	doc := &model.Document{
		URL: "https://example.com/a", NormalizedURL: "https://example.com/a",
		Text: bigText,
	}
	if err := w.Write(doc); err != nil {
		t.Fatalf("Write with oversized document: %v", err)
	}

	body, err := io.ReadAll(fake.inputs[0].Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	var got model.Document
	if err := json.Unmarshal(body, &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if len(got.Text) != len(bigText) {
		t.Errorf("Text length = %d, want %d (no truncation)", len(got.Text), len(bigText))
	}
}

func TestS3Writer_CloseIsANoop(t *testing.T) {
	w := &S3Writer{}
	if err := w.Close(); err != nil {
		t.Errorf("Close: %v, want nil", err)
	}
}

// TestS3Writer_SameContentDifferentURLsDoNotCollapse proves two Documents
// with identical Text (and therefore identical SimHash/ContentHash -- the
// near-duplicate/exact-duplicate signals internal/simhash and the
// content-hash dedupe use) but different NormalizedURL each get their own
// S3 key and are both written: the key is derived from the URL, not from
// the content, so a near-duplicate or exact-duplicate *content* collision
// (a real, expected case -- e.g. a syndicated article on two different
// sites) never collapses two genuinely different pages onto one S3 object.
// That collapsing-by-content-hash behavior is specific to Postgres's
// (normalized_url, content_hash) unique constraint, which S3Writer
// deliberately doesn't replicate.
func TestS3Writer_SameContentDifferentURLsDoNotCollapse(t *testing.T) {
	fake := &fakeS3PutObjectAPI{}
	w := &S3Writer{client: fake, bucket: "docs-bucket", putTimeout: time.Second}

	const sharedText = "identical syndicated article body, word for word"
	const sharedContentHash = "abc123"
	const sharedSimHash = uint64(0xdeadbeef)

	docA := &model.Document{
		URL: "https://site-a.example/article", NormalizedURL: "https://site-a.example/article",
		Text: sharedText, ContentHash: sharedContentHash, SimHash: sharedSimHash,
	}
	docB := &model.Document{
		URL: "https://site-b.example/article", NormalizedURL: "https://site-b.example/article",
		Text: sharedText, ContentHash: sharedContentHash, SimHash: sharedSimHash,
	}

	if err := w.Write(docA); err != nil {
		t.Fatalf("Write docA: %v", err)
	}
	if err := w.Write(docB); err != nil {
		t.Fatalf("Write docB: %v", err)
	}

	keys := fake.keys()
	if len(keys) != 4 {
		t.Fatalf("PutObject called %d times, want 4 (2 keys x 2 documents)", len(keys))
	}
	runKeyA, latestKeyA, runKeyB, latestKeyB := keys[0], keys[1], keys[2], keys[3]

	if runKeyA == runKeyB {
		t.Errorf("run-scoped keys collided despite different URLs: both %q", runKeyA)
	}
	if latestKeyA == latestKeyB {
		t.Errorf("latest keys collided despite different URLs: both %q", latestKeyA)
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

func TestS3LatestObjectKey_DifferentURLsDifferentKeys(t *testing.T) {
	a := S3LatestObjectKey("https://example.com/a")
	b := S3LatestObjectKey("https://example.com/b")
	if a == b {
		t.Errorf("S3LatestObjectKey collided for different URLs: %q", a)
	}
}
