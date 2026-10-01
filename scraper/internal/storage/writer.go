// Package storage handles persisting ETL output. Phase 1 writes newline-
// delimited JSON (NDJSON) to a local file -- one Document per line, which is
// trivially streamable into any downstream indexer, message queue, or
// bulk-load job. Later phases swap the Writer implementation (Kafka
// producer, S3 batch upload, DB writer) behind the same interface.
package storage

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"sync"

	"github.com/tekraj/pgs-search-engine/scraper/internal/model"
)

// Writer is anything that can persist a crawled Document. Implementations
// must be safe for concurrent use.
type Writer interface {
	Write(doc *model.Document) error
	Close() error
}

// NDJSONWriter writes one JSON object per line to a file.
type NDJSONWriter struct {
	mu  sync.Mutex
	f   *os.File
	buf *bufio.Writer
}

// NewNDJSONWriter opens path for appending, creating it if it doesn't
// exist. Appending (not truncating) matters here: a worker process that
// crashes and restarts must not destroy documents an earlier run already
// wrote for still-in-progress crawls (see internal/activities' content-hash
// dedupe, which guards against the resulting duplicate-write risk).
func NewNDJSONWriter(path string) (*NDJSONWriter, error) {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, fmt.Errorf("open output file: %w", err)
	}
	return &NDJSONWriter{f: f, buf: bufio.NewWriter(f)}, nil
}

// Write appends doc as one JSON line, flushing immediately so a crashed
// crawl doesn't lose already-fetched pages.
func (w *NDJSONWriter) Write(doc *model.Document) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	data, err := json.Marshal(doc)
	if err != nil {
		return fmt.Errorf("marshal document: %w", err)
	}
	if _, err := w.buf.Write(data); err != nil {
		return err
	}
	if err := w.buf.WriteByte('\n'); err != nil {
		return err
	}
	return w.buf.Flush()
}

// Close flushes and closes the underlying file.
func (w *NDJSONWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if err := w.buf.Flush(); err != nil {
		return err
	}
	return w.f.Close()
}

// MultiWriter fans a document out to several Writers, e.g. Postgres (for
// the API's own use) and Kafka (for the ETL team's pipeline) at the same
// time. Write stops at the first failing Writer and returns its error
// (Temporal will retry the whole WriteDocument activity, which is safe:
// every Writer implementation upserts/dedupes by content rather than
// blindly appending); Close closes every Writer regardless of earlier
// errors, returning the first one encountered.
type MultiWriter struct {
	writers []Writer
}

// NewMultiWriter returns a Writer that fans out to every writer given.
func NewMultiWriter(writers ...Writer) *MultiWriter {
	return &MultiWriter{writers: writers}
}

func (m *MultiWriter) Write(doc *model.Document) error {
	for _, w := range m.writers {
		if err := w.Write(doc); err != nil {
			return err
		}
	}
	return nil
}

func (m *MultiWriter) Close() error {
	var firstErr error
	for _, w := range m.writers {
		if err := w.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}
