package storage

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// fakeS3HeadObjectAPI serves canned HeadObject responses keyed by the
// requested object key, so S3FreshnessChecker can be tested without
// LocalStack. A key absent from objects returns *s3types.NotFound, mirroring
// a real bucket's behavior for an object that was never written.
type fakeS3HeadObjectAPI struct {
	mu      sync.Mutex
	objects map[string]time.Time // key -> LastModified
	calls   int
}

func (f *fakeS3HeadObjectAPI) HeadObject(_ context.Context, in *s3.HeadObjectInput, _ ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	f.mu.Lock()
	f.calls++
	lastModified, ok := f.objects[aws.ToString(in.Key)]
	f.mu.Unlock()

	if !ok {
		return nil, &s3types.NotFound{}
	}
	return &s3.HeadObjectOutput{LastModified: aws.Time(lastModified)}, nil
}

func TestS3FreshnessChecker_FreshURLs_ExistingRecentObjectIsFresh(t *testing.T) {
	now := time.Now()
	fake := &fakeS3HeadObjectAPI{objects: map[string]time.Time{
		S3LatestObjectKey("https://example.com/a"): now.Add(-time.Hour),
	}}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: time.Second, maxConcurrency: 4}

	fresh, err := c.FreshURLs(context.Background(), []string{"https://example.com/a"}, now.Add(-24*time.Hour))
	if err != nil {
		t.Fatalf("FreshURLs: %v", err)
	}
	if !fresh["https://example.com/a"] {
		t.Error("expected https://example.com/a to be fresh (fetched 1h ago, since=24h ago)")
	}
}

func TestS3FreshnessChecker_FreshURLs_StaleObjectIsNotFresh(t *testing.T) {
	now := time.Now()
	fake := &fakeS3HeadObjectAPI{objects: map[string]time.Time{
		S3LatestObjectKey("https://example.com/a"): now.Add(-48 * time.Hour),
	}}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: time.Second, maxConcurrency: 4}

	fresh, err := c.FreshURLs(context.Background(), []string{"https://example.com/a"}, now.Add(-24*time.Hour))
	if err != nil {
		t.Fatalf("FreshURLs: %v", err)
	}
	if fresh["https://example.com/a"] {
		t.Error("expected https://example.com/a to NOT be fresh (fetched 48h ago, since=24h ago)")
	}
}

func TestS3FreshnessChecker_FreshURLs_NeverFetchedIsNotFresh(t *testing.T) {
	fake := &fakeS3HeadObjectAPI{objects: map[string]time.Time{}}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: time.Second, maxConcurrency: 4}

	fresh, err := c.FreshURLs(context.Background(), []string{"https://example.com/never-fetched"}, time.Now().Add(-24*time.Hour))
	if err != nil {
		t.Fatalf("FreshURLs: %v", err)
	}
	if fresh["https://example.com/never-fetched"] {
		t.Error("a URL with no latest-key object should never be reported fresh")
	}
}

func TestS3FreshnessChecker_FreshURLs_MixedBatch(t *testing.T) {
	now := time.Now()
	fake := &fakeS3HeadObjectAPI{objects: map[string]time.Time{
		S3LatestObjectKey("https://example.com/fresh"): now.Add(-time.Minute),
		S3LatestObjectKey("https://example.com/stale"): now.Add(-72 * time.Hour),
	}}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: time.Second, maxConcurrency: 4}

	fresh, err := c.FreshURLs(context.Background(), []string{
		"https://example.com/fresh",
		"https://example.com/stale",
		"https://example.com/never-fetched",
	}, now.Add(-24*time.Hour))
	if err != nil {
		t.Fatalf("FreshURLs: %v", err)
	}
	if !fresh["https://example.com/fresh"] {
		t.Error("fresh URL should be reported fresh")
	}
	if fresh["https://example.com/stale"] {
		t.Error("stale URL should NOT be reported fresh")
	}
	if fresh["https://example.com/never-fetched"] {
		t.Error("never-fetched URL should NOT be reported fresh")
	}
}

func TestS3FreshnessChecker_FreshURLs_EmptyBatchReturnsNilWithoutCallingS3(t *testing.T) {
	fake := &fakeS3HeadObjectAPI{objects: map[string]time.Time{}}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: time.Second, maxConcurrency: 4}

	fresh, err := c.FreshURLs(context.Background(), nil, time.Now())
	if err != nil {
		t.Fatalf("FreshURLs: %v", err)
	}
	if fresh != nil {
		t.Errorf("fresh = %v, want nil", fresh)
	}
	if fake.calls != 0 {
		t.Errorf("HeadObject called %d times for an empty batch, want 0", fake.calls)
	}
}

// TestS3FreshnessChecker_FreshURLs_TransientErrorTreatedAsNotFresh proves a
// HeadObject error that isn't "not found" (e.g. throttling) doesn't fail
// the whole batch or the other candidates in it -- the affected URL is
// just treated as not fresh (safe default: fetch it).
func TestS3FreshnessChecker_FreshURLs_TransientErrorTreatedAsNotFresh(t *testing.T) {
	fake := &erroringHeadObjectAPI{err: errors.New("throttled")}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: time.Second, maxConcurrency: 4}

	fresh, err := c.FreshURLs(context.Background(), []string{"https://example.com/a"}, time.Now().Add(-24*time.Hour))
	if err != nil {
		t.Fatalf("FreshURLs: %v, want nil (per-candidate errors shouldn't fail the batch)", err)
	}
	if fresh["https://example.com/a"] {
		t.Error("a URL whose HeadObject errored should not be reported fresh")
	}
}

type erroringHeadObjectAPI struct{ err error }

func (f *erroringHeadObjectAPI) HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	return nil, f.err
}

func TestS3FreshnessChecker_FreshURLs_RespectsMaxConcurrency(t *testing.T) {
	const maxConcurrency = 3
	fake := &concurrencyTrackingHeadObjectAPI{}
	c := &S3FreshnessChecker{client: fake, bucket: "docs-bucket", headTimeout: 2 * time.Second, maxConcurrency: maxConcurrency}

	urls := make([]string, 20)
	for i := range urls {
		urls[i] = "https://example.com/" + string(rune('a'+i))
	}

	if _, err := c.FreshURLs(context.Background(), urls, time.Now()); err != nil {
		t.Fatalf("FreshURLs: %v", err)
	}

	if fake.maxObserved > maxConcurrency {
		t.Errorf("observed %d concurrent HeadObject calls, want at most %d", fake.maxObserved, maxConcurrency)
	}
	if fake.maxObserved == 0 {
		t.Fatal("no HeadObject calls were observed -- test setup is broken")
	}
}

type concurrencyTrackingHeadObjectAPI struct {
	mu          sync.Mutex
	inFlight    int
	maxObserved int
}

func (f *concurrencyTrackingHeadObjectAPI) HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	f.mu.Lock()
	f.inFlight++
	if f.inFlight > f.maxObserved {
		f.maxObserved = f.inFlight
	}
	f.mu.Unlock()

	time.Sleep(20 * time.Millisecond)

	f.mu.Lock()
	f.inFlight--
	f.mu.Unlock()

	return nil, &s3types.NotFound{}
}
