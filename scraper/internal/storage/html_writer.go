package storage

import (
	"fmt"
	"os"
	"path/filepath"
)

// HTMLWriter saves a page's raw HTML body, separately from the parsed
// model.Document metadata that Writer persists -- for teams that want the
// original document (re-parsing with a different pipeline later, archival,
// diffing a page across crawls) rather than only the extracted text.
type HTMLWriter interface {
	// SaveHTML persists body for the page identified by contentHash. It
	// must be safe to call repeatedly with the same contentHash (e.g. after
	// a Temporal activity retry) without duplicating work.
	SaveHTML(normalizedURL, contentHash string, body []byte) error
}

// NoopHTMLWriter discards every page, used when raw HTML downloads aren't
// enabled.
type NoopHTMLWriter struct{}

func (NoopHTMLWriter) SaveHTML(string, string, []byte) error { return nil }

// DirHTMLWriter saves each page's raw HTML body to a file under a
// directory, named by content hash. Naming by content hash rather than URL
// both dedupes identical content reached via different URLs (redirects,
// tracking-param variants) and sidesteps having to sanitize a URL into a
// safe filename.
type DirHTMLWriter struct {
	dir string
}

// NewDirHTMLWriter creates dir (and any missing parents) if it doesn't
// already exist.
func NewDirHTMLWriter(dir string) (*DirHTMLWriter, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create html output dir: %w", err)
	}
	return &DirHTMLWriter{dir: dir}, nil
}

// SaveHTML writes body to <dir>/<contentHash>.html, skipping the write if
// that file already exists -- both an optimization (identical content
// crawled again needn't be rewritten) and the idempotency an activity retry
// needs.
func (w *DirHTMLWriter) SaveHTML(normalizedURL, contentHash string, body []byte) error {
	path := filepath.Join(w.dir, contentHash+".html")
	if _, err := os.Stat(path); err == nil {
		return nil
	}
	return os.WriteFile(path, body, 0o644)
}
