package storage

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// fakeS3RunRecorderAPI is an in-memory S3 object store (keyed by object
// key, value + a monotonic ETag) that PutObject/GetObject work against, so
// S3RunRecorder's read-modify-write + conditional-write logic can be
// tested without LocalStack.
type fakeS3RunRecorderAPI struct {
	mu       sync.Mutex
	objects  map[string][]byte
	etags    map[string]string
	etagSeq  int
	putCalls int
}

func newFakeS3RunRecorderAPI() *fakeS3RunRecorderAPI {
	return &fakeS3RunRecorderAPI{objects: map[string][]byte{}, etags: map[string]string{}}
}

func (f *fakeS3RunRecorderAPI) PutObject(_ context.Context, in *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.putCalls++

	key := aws.ToString(in.Key)
	currentETag, exists := f.etags[key]

	if in.IfNoneMatch != nil && aws.ToString(in.IfNoneMatch) == "*" && exists {
		return nil, errors.New("PreconditionFailed: object already exists")
	}
	if in.IfMatch != nil {
		if !exists {
			return nil, errors.New("PreconditionFailed: object does not exist")
		}
		if aws.ToString(in.IfMatch) != currentETag {
			return nil, errors.New("PreconditionFailed: ETag mismatch")
		}
	}

	body, err := io.ReadAll(in.Body)
	if err != nil {
		return nil, err
	}
	f.etagSeq++
	newETag := strconv.Itoa(f.etagSeq)
	f.objects[key] = body
	f.etags[key] = newETag
	return &s3.PutObjectOutput{ETag: aws.String(newETag)}, nil
}

func (f *fakeS3RunRecorderAPI) GetObject(_ context.Context, in *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()

	key := aws.ToString(in.Key)
	body, ok := f.objects[key]
	if !ok {
		return nil, errors.New("NoSuchKey")
	}
	return &s3.GetObjectOutput{
		Body: io.NopCloser(bytes.NewReader(body)),
		ETag: aws.String(f.etags[key]),
	}, nil
}

func newTestRunRecorder(client s3RunRecorderAPI, runIDs ...int64) *S3RunRecorder {
	i := 0
	return &S3RunRecorder{
		client:      client,
		bucket:      "docs-bucket",
		timeout:     time.Second,
		maxCASRetry: 3,
		now:         time.Now,
		newRunID: func() int64 {
			id := runIDs[i]
			i++
			return id
		},
	}
}

func TestS3RunRecorder_StartRun_WritesManifestAtRunIDKey(t *testing.T) {
	fake := newFakeS3RunRecorderAPI()
	r := newTestRunRecorder(fake, 12345)

	runID, err := r.StartRun(context.Background(), StartRunInput{SeedCount: 3, MaxDepth: 2, MaxPages: 100})
	if err != nil {
		t.Fatalf("StartRun: %v", err)
	}
	if runID != 12345 {
		t.Fatalf("runID = %d, want 12345", runID)
	}

	body, ok := fake.objects[S3RunManifestKey(12345)]
	if !ok {
		t.Fatalf("no object at key %q", S3RunManifestKey(12345))
	}
	var m S3RunManifest
	if err := json.Unmarshal(body, &m); err != nil {
		t.Fatalf("unmarshal manifest: %v", err)
	}
	if m.Status != "running" || m.SeedCount != 3 || m.MaxDepth != 2 || m.MaxPages != 100 {
		t.Errorf("manifest = %+v, want running/3/2/100", m)
	}
}

func TestS3RunRecorder_StartRun_CollisionIsAnError(t *testing.T) {
	fake := newFakeS3RunRecorderAPI()
	r := newTestRunRecorder(fake, 1, 1) // same runID both times, forces a collision

	if _, err := r.StartRun(context.Background(), StartRunInput{}); err != nil {
		t.Fatalf("StartRun (first): %v", err)
	}
	if _, err := r.StartRun(context.Background(), StartRunInput{}); err == nil {
		t.Fatal("StartRun (colliding runID): got nil error, want IfNoneMatch precondition failure")
	}
}

func TestS3RunRecorder_UpdateRunStats_UpdatesFieldsPreservingOthers(t *testing.T) {
	fake := newFakeS3RunRecorderAPI()
	r := newTestRunRecorder(fake, 7)

	runID, err := r.StartRun(context.Background(), StartRunInput{SeedCount: 5, MaxDepth: 1, MaxPages: 50})
	if err != nil {
		t.Fatalf("StartRun: %v", err)
	}

	if err := r.UpdateRunStats(context.Background(), runID, RunStats{Fetched: 10, Succeeded: 8, Failed: 2}); err != nil {
		t.Fatalf("UpdateRunStats: %v", err)
	}

	var m S3RunManifest
	if err := json.Unmarshal(fake.objects[S3RunManifestKey(runID)], &m); err != nil {
		t.Fatalf("unmarshal manifest: %v", err)
	}
	if m.Status != "running" {
		t.Errorf("Status = %q, want %q (UpdateRunStats shouldn't change status)", m.Status, "running")
	}
	if m.SeedCount != 5 || m.MaxDepth != 1 || m.MaxPages != 50 {
		t.Errorf("StartRun fields not preserved: %+v", m)
	}
	if m.Fetched != 10 || m.Succeeded != 8 || m.Failed != 2 {
		t.Errorf("stats not applied: %+v", m)
	}
}

func TestS3RunRecorder_FinishRun_SetsTerminalStatusAndError(t *testing.T) {
	fake := newFakeS3RunRecorderAPI()
	r := newTestRunRecorder(fake, 9)

	runID, err := r.StartRun(context.Background(), StartRunInput{})
	if err != nil {
		t.Fatalf("StartRun: %v", err)
	}

	if err := r.FinishRun(context.Background(), runID, "failed", RunStats{Fetched: 5, Failed: 5}, "all pages failed"); err != nil {
		t.Fatalf("FinishRun: %v", err)
	}

	var m S3RunManifest
	if err := json.Unmarshal(fake.objects[S3RunManifestKey(runID)], &m); err != nil {
		t.Fatalf("unmarshal manifest: %v", err)
	}
	if m.Status != "failed" {
		t.Errorf("Status = %q, want %q", m.Status, "failed")
	}
	if m.Error != "all pages failed" {
		t.Errorf("Error = %q, want %q", m.Error, "all pages failed")
	}
}

func TestS3RunRecorder_UpdateRunStats_UnknownRunIDIsAnError(t *testing.T) {
	fake := newFakeS3RunRecorderAPI()
	r := newTestRunRecorder(fake)

	if err := r.UpdateRunStats(context.Background(), 999, RunStats{}); err == nil {
		t.Fatal("UpdateRunStats on a nonexistent run: got nil error, want one")
	}
}
