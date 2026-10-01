package fetcher

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync"
	"testing"
	"time"
)

func TestGet_FollowsRedirectsAndRecordsFinalURLAndChain(t *testing.T) {
	mux := http.NewServeMux()
	var baseURL string
	mux.HandleFunc("/start", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, baseURL+"/middle", http.StatusMovedPermanently)
	})
	mux.HandleFunc("/middle", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, baseURL+"/end", http.StatusFound)
	})
	mux.HandleFunc("/end", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("done"))
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()
	baseURL = srv.URL

	f := New(5*time.Second, 0)
	res, err := f.Get(context.Background(), srv.URL+"/start")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}

	if res.FinalURL != srv.URL+"/end" {
		t.Errorf("FinalURL = %q, want %q", res.FinalURL, srv.URL+"/end")
	}
	wantChain := []string{srv.URL + "/middle", srv.URL + "/end"}
	if len(res.RedirectChain) != len(wantChain) {
		t.Fatalf("RedirectChain = %v, want %v", res.RedirectChain, wantChain)
	}
	for i := range wantChain {
		if res.RedirectChain[i] != wantChain[i] {
			t.Errorf("RedirectChain[%d] = %q, want %q", i, res.RedirectChain[i], wantChain[i])
		}
	}
}

func TestGet_NoRedirect_FinalURLMatchesRequestedAndChainEmpty(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok"))
	}))
	defer srv.Close()

	f := New(5*time.Second, 0)
	res, err := f.Get(context.Background(), srv.URL+"/page")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if res.FinalURL != srv.URL+"/page" {
		t.Errorf("FinalURL = %q, want %q", res.FinalURL, srv.URL+"/page")
	}
	if len(res.RedirectChain) != 0 {
		t.Errorf("RedirectChain = %v, want empty", res.RedirectChain)
	}
}

// TestGet_ConcurrentRedirectsDontCrossContaminate proves the per-Get()
// redirect-chain accumulator is genuinely request-scoped: many concurrent
// Get() calls to different redirect chains on the same *Fetcher (same
// underlying *http.Client, same shared CheckRedirect closure) must each
// see only their own hops, never another goroutine's.
func TestGet_ConcurrentRedirectsDontCrossContaminate(t *testing.T) {
	mux := http.NewServeMux()
	var baseURL string
	const n = 20
	// Build n independent 2-hop redirect chains: /startI -> /midI -> /endI.
	for i := 0; i < n; i++ {
		i := i
		mux.HandleFunc(pathFor(i, "start"), func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, baseURL+pathFor(i, "mid"), http.StatusMovedPermanently)
		})
		mux.HandleFunc(pathFor(i, "mid"), func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, baseURL+pathFor(i, "end"), http.StatusFound)
		})
		mux.HandleFunc(pathFor(i, "end"), func(w http.ResponseWriter, r *http.Request) {
			w.Write([]byte("done"))
		})
	}
	srv := httptest.NewServer(mux)
	defer srv.Close()
	baseURL = srv.URL

	f := New(5*time.Second, 0)
	var wg sync.WaitGroup
	errs := make([]error, n)
	chains := make([][]string, n)
	for i := 0; i < n; i++ {
		i := i
		wg.Add(1)
		go func() {
			defer wg.Done()
			res, err := f.Get(context.Background(), srv.URL+pathFor(i, "start"))
			if err != nil {
				errs[i] = err
				return
			}
			chains[i] = res.RedirectChain
		}()
	}
	wg.Wait()

	for i := 0; i < n; i++ {
		if errs[i] != nil {
			t.Fatalf("chain %d: Get: %v", i, errs[i])
		}
		want := []string{srv.URL + pathFor(i, "mid"), srv.URL + pathFor(i, "end")}
		got := chains[i]
		if len(got) != len(want) || got[0] != want[0] || got[1] != want[1] {
			t.Errorf("chain %d = %v, want %v (cross-contamination if this doesn't match)", i, got, want)
		}
	}
}

func pathFor(i int, stage string) string {
	return "/" + stage + "-" + strconv.Itoa(i)
}

// TestGet_BandwidthLimit_ThrottlesAggregateRate proves a Fetcher built with
// a bandwidth cap makes fetching a body noticeably larger than one second's
// budget take a perceptible amount of wall-clock time -- otherwise a bug
// that ignores the limiter entirely would still pass.
func TestGet_BandwidthLimit_ThrottlesAggregateRate(t *testing.T) {
	const bandwidthBPS = 500          // bytes/sec: also the limiter's burst (see New)
	const bodySize = bandwidthBPS * 2 // 2 chunks: 1 free from burst, 1 must wait ~1s
	body := make([]byte, bodySize)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(body)
	}))
	defer srv.Close()

	f := New(5*time.Second, bandwidthBPS)

	start := time.Now()
	if _, err := f.Get(context.Background(), srv.URL); err != nil {
		t.Fatalf("Get: %v", err)
	}
	elapsed := time.Since(start)

	if elapsed < 700*time.Millisecond {
		t.Errorf("fetching a %d-byte body at %d bytes/sec took %v, want throttling to take noticeably longer (~1s)", bodySize, bandwidthBPS, elapsed)
	}
}

func TestGet_PolitenessDelaySpacesSameDomainRequests(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok"))
	}))
	defer srv.Close()

	const delay = 50 * time.Millisecond
	f := NewWithOptions(Options{Timeout: time.Second, PolitenessDelay: delay})
	if _, err := f.Get(context.Background(), srv.URL+"/first"); err != nil {
		t.Fatalf("first Get: %v", err)
	}
	start := time.Now()
	if _, err := f.Get(context.Background(), srv.URL+"/second"); err != nil {
		t.Fatalf("second Get: %v", err)
	}
	if elapsed := time.Since(start); elapsed < 35*time.Millisecond {
		t.Fatalf("second request waited %v, want a per-domain delay near %v", elapsed, delay)
	}
}

func TestSetDomainDelayOverridesDefault(t *testing.T) {
	f := NewWithOptions(Options{Timeout: time.Second})
	if err := f.SetDomainDelay("https://example.gov.np/start", 20*time.Millisecond); err != nil {
		t.Fatalf("SetDomainDelay: %v", err)
	}
	if err := f.waitForDomain(context.Background(), "https://example.gov.np/one"); err != nil {
		t.Fatalf("first wait: %v", err)
	}
	start := time.Now()
	if err := f.waitForDomain(context.Background(), "https://example.gov.np/two"); err != nil {
		t.Fatalf("second wait: %v", err)
	}
	if elapsed := time.Since(start); elapsed < 12*time.Millisecond {
		t.Fatalf("second wait = %v, want configured crawl delay", elapsed)
	}
}
