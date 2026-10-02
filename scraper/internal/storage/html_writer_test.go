package storage

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDirHTMLWriter_SavesBodyUnderContentHash(t *testing.T) {
	dir := t.TempDir()
	w, err := NewDirHTMLWriter(filepath.Join(dir, "html"))
	if err != nil {
		t.Fatalf("NewDirHTMLWriter: %v", err)
	}

	if err := w.SaveHTML("https://example.com/", "abc123", []byte("<html>hi</html>")); err != nil {
		t.Fatalf("SaveHTML: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(dir, "html", "abc123.html"))
	if err != nil {
		t.Fatalf("read saved file: %v", err)
	}
	if string(got) != "<html>hi</html>" {
		t.Errorf("saved content = %q, want %q", got, "<html>hi</html>")
	}
}

// TestDirHTMLWriter_SkipsExistingFile proves a second SaveHTML for the same
// content hash doesn't overwrite the file -- the idempotency a Temporal
// activity retry (or the same content crawled again) needs.
func TestDirHTMLWriter_SkipsExistingFile(t *testing.T) {
	dir := t.TempDir()
	w, err := NewDirHTMLWriter(dir)
	if err != nil {
		t.Fatalf("NewDirHTMLWriter: %v", err)
	}

	if err := w.SaveHTML("https://example.com/", "abc123", []byte("first")); err != nil {
		t.Fatalf("SaveHTML: %v", err)
	}
	if err := w.SaveHTML("https://example.com/", "abc123", []byte("second")); err != nil {
		t.Fatalf("SaveHTML (second): %v", err)
	}

	got, err := os.ReadFile(filepath.Join(dir, "abc123.html"))
	if err != nil {
		t.Fatalf("read saved file: %v", err)
	}
	if string(got) != "first" {
		t.Errorf("saved content = %q, want %q (should not be overwritten)", got, "first")
	}
}

func TestNoopHTMLWriter_NeverErrors(t *testing.T) {
	if err := (NoopHTMLWriter{}).SaveHTML("u", "h", []byte("x")); err != nil {
		t.Errorf("SaveHTML: %v, want nil", err)
	}
}
