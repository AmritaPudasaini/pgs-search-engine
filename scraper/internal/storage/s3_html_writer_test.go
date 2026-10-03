package storage

import (
	"context"
	"errors"
	"io"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type fakePutter struct {
	inputs []*s3.PutObjectInput
	bodies [][]byte
	err    error
}

func (f *fakePutter) PutObject(ctx context.Context, in *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	b, _ := io.ReadAll(in.Body)
	f.inputs = append(f.inputs, in)
	f.bodies = append(f.bodies, b)
	return &s3.PutObjectOutput{}, f.err
}

func TestS3HTMLWriter_UploadsRawBodyUnderHostAndHash(t *testing.T) {
	fake := &fakePutter{}
	w := &S3HTMLWriter{client: fake, bucket: "bkt", keyPrefix: "dev", putTimeout: 5e9}

	page := []byte("<html><body>Hello \xe0\xa4\xa8</body></html>")
	if err := w.SaveHTML("https://Example.com/a?b=1", "abc123", page); err != nil {
		t.Fatalf("SaveHTML: %v", err)
	}
	if len(fake.inputs) != 1 {
		t.Fatalf("PutObject called %d times, want 1", len(fake.inputs))
	}
	in := fake.inputs[0]
	if *in.Bucket != "bkt" || *in.Key != "dev/html/example.com/abc123.html" {
		t.Errorf("put to s3://%s/%s, want s3://bkt/dev/html/example.com/abc123.html", *in.Bucket, *in.Key)
	}
	if *in.ContentType != "text/html" {
		t.Errorf("ContentType = %q, want text/html", *in.ContentType)
	}
	if string(fake.bodies[0]) != string(page) {
		t.Error("uploaded body differs from the fetched HTML")
	}
}

func TestS3HTMLWriter_RequiresContentHash(t *testing.T) {
	fake := &fakePutter{}
	w := &S3HTMLWriter{client: fake, bucket: "bkt", putTimeout: 5e9}
	if err := w.SaveHTML("https://example.com/", "", []byte("x")); err == nil {
		t.Fatal("want error for empty content hash")
	}
	if len(fake.inputs) != 0 {
		t.Error("nothing should be uploaded without a content hash")
	}
}

func TestS3HTMLWriter_PropagatesPutError(t *testing.T) {
	w := &S3HTMLWriter{client: &fakePutter{err: errors.New("throttled")}, bucket: "bkt", putTimeout: 5e9}
	if err := w.SaveHTML("https://example.com/", "h", []byte("x")); err == nil {
		t.Fatal("want error when PutObject fails")
	}
}

func TestS3HTMLObjectKey_UnparsableURLFallsBack(t *testing.T) {
	if got := S3HTMLObjectKey("::not a url", "h"); got != "html/unknown-host/h.html" {
		t.Errorf("key = %q", got)
	}
}
