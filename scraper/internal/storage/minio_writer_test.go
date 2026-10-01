package storage

import (
	"context"
	"encoding/json"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

type recordedObject struct {
	bucket      string
	key         string
	contentType string
	data        []byte
}

type recordingStore struct {
	objects []recordedObject
	err     error
}

func (s *recordingStore) PutObject(_ context.Context, bucket, key string, body io.Reader, _ int64, contentType string) error {
	if s.err != nil {
		return s.err
	}
	data, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	s.objects = append(s.objects, recordedObject{bucket: bucket, key: key, contentType: contentType, data: data})
	return nil
}

func TestMinIOWriterWritesSelfContainedPayload(t *testing.T) {
	store := &recordingStore{}
	writer, err := NewMinIOWriter(store, "crawler", "raw")
	if err != nil {
		t.Fatalf("NewMinIOWriter: %v", err)
	}
	doc := &model.Document{
		URL: "https://mofaga.gov.np/notices/1", Host: "mofaga.gov.np",
		Title: "Notice", MetaKeywords: []string{"nepal"}, Text: "notice body",
		InternalLinks: []string{"https://mofaga.gov.np/about"},
		ExternalLinks: []string{"https://nepal.gov.np"},
		StatusCode:    200, ContentType: "text/html; charset=utf-8", Depth: 2,
		FetchedAt: time.Date(2026, 9, 19, 10, 0, 0, 0, time.UTC),
	}
	payload, err := BuildDFSPayload(doc, []byte("<html>raw</html>"), "MoFAGA")
	if err != nil {
		t.Fatalf("BuildDFSPayload: %v", err)
	}
	stored, err := writer.WritePage(context.Background(), payload)
	if err != nil {
		t.Fatalf("WritePage: %v", err)
	}
	if len(store.objects) != 1 || !strings.HasPrefix(stored.Key, "raw/pages/mofaga.gov.np/2026/09/19/") {
		t.Fatalf("stored=%+v objects=%+v", stored, store.objects)
	}
	var decoded model.DFSPayload
	if err := json.Unmarshal(store.objects[0].data, &decoded); err != nil {
		t.Fatalf("decode object: %v", err)
	}
	if decoded.StorageMetadata.PageURL != doc.URL || decoded.RawPayload.Data == "" {
		t.Fatalf("payload missing contract fields: %+v", decoded)
	}
}
