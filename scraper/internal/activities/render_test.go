package activities

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"

	"search-engine-scraper/internal/model"
	"search-engine-scraper/internal/render"
)

type fakeRenderer struct {
	html  string
	err   error
	calls int
}

func (f *fakeRenderer) Render(ctx context.Context, url string) (string, string, error) {
	f.calls++
	return f.html, url, f.err
}

type memRecords struct{ recs []*model.PageRecord }

func (m *memRecords) SaveRecord(r *model.PageRecord) (string, error) {
	m.recs = append(m.recs, r)
	return "pages/" + r.Host + "/" + r.ContentHash + ".json", nil
}

type memHTML struct{ saved map[string][]byte }

func (m *memHTML) SaveHTML(url, hash string, body []byte) error {
	if m.saved == nil {
		m.saved = map[string][]byte{}
	}
	m.saved[hash] = body
	return nil
}

const spaShell = `<html><head><title>App</title></head><body><div id="root"></div><script src="/a.js"></script></body></html>`
const spaRendered = `<html lang="en"><head><title>App</title></head><body><div id="root"><h1>Real heading</h1>
<p>` + "Rendered paragraph with plenty of words to read. " + `</p><a href="/inner">inner page</a></div></body></html>`

func spaMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/spa", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte(spaShell))
	})
	return mux
}

func TestProcessPage_AutoRendersJSAppShell(t *testing.T) {
	a, srv := newTestActivities(spaMux())
	defer srv.Close()
	r := &fakeRenderer{html: spaRendered}
	recs, html := &memRecords{}, &memHTML{}
	a.Renderer, a.RenderMode, a.Records, a.HTML = r, render.ModeAuto, recs, html

	out, err := a.ProcessPage(context.Background(), ProcessPageInput{URL: srv.URL + "/spa"})
	if err != nil {
		t.Fatal(err)
	}
	if r.calls != 1 || !out.Rendered {
		t.Fatalf("renderer calls=%d rendered=%v, want the shell to be rendered", r.calls, out.Rendered)
	}
	if !strings.Contains(out.Text, "Rendered paragraph") || len(out.Headings) != 1 {
		t.Errorf("output should come from the rendered DOM: text=%q headings=%v", out.Text, out.Headings)
	}
	found := false
	for _, l := range out.Links {
		found = found || strings.HasSuffix(l, "/inner")
	}
	if !found {
		t.Errorf("links from the rendered DOM missing: %v", out.Links)
	}
	if out.HTMLKey == "" || out.RenderedHTMLKey == "" || out.RecordKey == "" {
		t.Errorf("keys not set: html=%q rendered=%q record=%q", out.HTMLKey, out.RenderedHTMLKey, out.RecordKey)
	}
	if len(html.saved) != 2 {
		t.Errorf("saved %d html objects, want raw + rendered", len(html.saved))
	}
	if len(recs.recs) != 1 || !recs.recs[0].Rendered || recs.recs[0].RenderReason == "" || len(recs.recs[0].TagCounts) == 0 {
		t.Errorf("page record wrong: %+v", recs.recs)
	}
}

func TestProcessPage_RenderOffNeverRenders(t *testing.T) {
	a, srv := newTestActivities(spaMux())
	defer srv.Close()
	r := &fakeRenderer{html: spaRendered}
	a.Renderer = r // RenderMode stays off

	out, err := a.ProcessPage(context.Background(), ProcessPageInput{URL: srv.URL + "/spa"})
	if err != nil || r.calls != 0 || out.Rendered {
		t.Fatalf("err=%v calls=%d rendered=%v, want no rendering when off", err, r.calls, out.Rendered)
	}
}

func TestProcessPage_AutoSkipsStaticPages(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/static", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write([]byte(`<html><body><h1>Static</h1><p>` + strings.Repeat("real words here ", 40) + `</p></body></html>`))
	})
	a, srv := newTestActivities(mux)
	defer srv.Close()
	r := &fakeRenderer{html: spaRendered}
	a.Renderer, a.RenderMode = r, render.ModeAuto

	if _, err := a.ProcessPage(context.Background(), ProcessPageInput{URL: srv.URL + "/static"}); err != nil {
		t.Fatal(err)
	}
	if r.calls != 0 {
		t.Errorf("renderer called %d times for a static page", r.calls)
	}
}

func TestProcessPage_AlwaysRendersAndFallsBackOnError(t *testing.T) {
	a, srv := newTestActivities(spaMux())
	defer srv.Close()
	a.Renderer, a.RenderMode = &fakeRenderer{err: errors.New("chrome down")}, render.ModeAlways

	out, err := a.ProcessPage(context.Background(), ProcessPageInput{URL: srv.URL + "/spa"})
	if err != nil {
		t.Fatalf("a render failure must not fail the page: %v", err)
	}
	if out.Rendered || out.RenderError == "" || out.Title != "App" {
		t.Errorf("rendered=%v renderError=%q title=%q, want static fallback with the error recorded", out.Rendered, out.RenderError, out.Title)
	}
}
