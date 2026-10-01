package storage

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDocumentDownloaderStoresBinaryAndMetadata(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/pdf")
		w.Write([]byte("%PDF-1.7 test"))
	}))
	defer srv.Close()
	store := &recordingStore{}
	d, err := NewDocumentDownloader(srv.Client(), store, "crawler", "raw", 1024)
	if err != nil {
		t.Fatalf("NewDocumentDownloader: %v", err)
	}
	metadata, err := d.Download(context.Background(), "https://example.gov.np/notices", srv.URL+"/notice.pdf")
	if err != nil {
		t.Fatalf("Download: %v", err)
	}
	if len(store.objects) != 2 {
		t.Fatalf("objects = %d, want binary and metadata", len(store.objects))
	}
	if !strings.Contains(metadata.StoragePath, "/documents/") || metadata.SHA256 == "" {
		t.Fatalf("metadata = %+v", metadata)
	}
}

func TestDocumentDownloaderRejectsOversizedBody(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/pdf")
		w.Write([]byte("%PDF-" + strings.Repeat("x", 64)))
	}))
	defer srv.Close()
	store := &recordingStore{}
	d, _ := NewDocumentDownloader(srv.Client(), store, "crawler", "", 16)
	if _, err := d.Download(context.Background(), "https://example.gov.np", srv.URL+"/large.pdf"); err == nil {
		t.Fatal("Download error = nil, want size-limit error")
	}
	if len(store.objects) != 0 {
		t.Fatalf("stored %d objects after rejected download", len(store.objects))
	}
}
