package activities

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

type recordingHTMLWriter struct {
	url, hash string
	body      []byte
	calls     int
	err       error
}

func (r *recordingHTMLWriter) SaveHTML(url, hash string, body []byte) error {
	r.calls++
	r.url, r.hash, r.body = url, hash, body
	return r.err
}

func htmlMux(body string) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/page", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte(body))
	})
	return mux
}

func TestProcessPage_SavesRawHTML(t *testing.T) {
	const page = `<html><head><title>t</title></head><body>hello</body></html>`
	a, srv := newTestActivities(htmlMux(page))
	defer srv.Close()
	rec := &recordingHTMLWriter{}
	a.HTML = rec

	out, err := a.ProcessPage(context.Background(), ProcessPageInput{URL: srv.URL + "/page"})
	if err != nil {
		t.Fatalf("ProcessPage: %v", err)
	}
	if rec.calls != 1 {
		t.Fatalf("SaveHTML called %d times, want 1", rec.calls)
	}
	if string(rec.body) != page {
		t.Errorf("saved body = %q, want the raw page", rec.body)
	}
	if rec.url != out.NormalizedURL || rec.hash != out.ContentHash {
		t.Errorf("saved under (%q, %q), want (%q, %q)", rec.url, rec.hash, out.NormalizedURL, out.ContentHash)
	}
}

func TestProcessPage_HTMLWriteFailureDoesNotFailPage(t *testing.T) {
	a, srv := newTestActivities(htmlMux(`<html><body>` + strings.Repeat("x", 50) + `</body></html>`))
	defer srv.Close()
	a.HTML = &recordingHTMLWriter{err: errors.New("disk full")}

	out, err := a.ProcessPage(context.Background(), ProcessPageInput{URL: srv.URL + "/page"})
	if err != nil {
		t.Fatalf("ProcessPage returned %v, want best-effort HTML save to be ignored", err)
	}
	if out.FetchError != "" {
		t.Errorf("FetchError = %q, want empty", out.FetchError)
	}
}

func TestNew_DefaultsToNoopHTMLWriter(t *testing.T) {
	a := New(nil, nil, nil, nil, nil)
	if a.HTML == nil {
		t.Fatal("HTML writer should default to a no-op, not nil")
	}
	if err := a.HTML.SaveHTML("u", "h", []byte("x")); err != nil {
		t.Errorf("default HTML writer returned %v", err)
	}
}
