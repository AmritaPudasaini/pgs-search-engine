package api

import (
	"context"
	"errors"
	"net/http"
	"testing"

	"search-engine-scraper/internal/db"
)

// fakeQuerier embeds db.Querier (nil) so it trivially satisfies the
// interface -- only CountDocuments, the one method handleHealthz calls, is
// overridden. Any other method actually being invoked would nil-deref,
// which is fine: these tests only exercise /healthz.
type fakeQuerier struct {
	db.Querier
	countErr error
}

func (f *fakeQuerier) CountDocuments(context.Context) (int64, error) {
	if f.countErr != nil {
		return 0, f.countErr
	}
	return 42, nil
}

func TestServer_HandleHealthz_OKWhenDatabaseReachable(t *testing.T) {
	s := NewServer(&fakeQuerier{})
	rec := doGet(t, s.Routes(), "/healthz")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200, body = %s", rec.Code, rec.Body.String())
	}
}

// TestServer_HandleHealthz_UnhealthyWhenDatabaseUnreachable proves
// /healthz stopped being an unconditional 200 -- see the handler's doc
// comment (Person 5 checklist item 9). CountDocuments failing is used as
// the reachability check, since Server's constructor only holds a
// db.Querier (no literal Ping available without changing NewServer's
// signature and breaking cmd/api/main.go's call site).
func TestServer_HandleHealthz_UnhealthyWhenDatabaseUnreachable(t *testing.T) {
	s := NewServer(&fakeQuerier{countErr: errors.New("connection refused")})
	rec := doGet(t, s.Routes(), "/healthz")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503, body = %s", rec.Code, rec.Body.String())
	}
}
