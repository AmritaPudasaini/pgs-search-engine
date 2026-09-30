// Package api exposes the crawled documents over HTTP so they can be
// browsed without a direct Postgres connection: JSON endpoints under
// /api/v1, plus a Swagger UI (see openapi.yaml) at /docs for interactively
// exploring and calling them.
package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"search-engine-scraper/internal/db"
)

const (
	defaultLimit = 20
	maxLimit     = 200
)

// Server serves the read-only documents API on top of the same
// sqlc-generated queries the worker uses to write.
type Server struct {
	queries db.Querier
}

func NewServer(queries db.Querier) *Server {
	return &Server{queries: queries}
}

// Routes returns the HTTP handler for the whole API: JSON endpoints plus
// the Swagger UI and the OpenAPI spec it loads.
func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", handleHealthz)

	mux.HandleFunc("GET /api/v1/documents", s.handleListDocuments)
	mux.HandleFunc("GET /api/v1/documents/count", s.handleCountDocuments)
	mux.HandleFunc("GET /api/v1/documents/categories", s.handleCountByCategory)

	mux.HandleFunc("GET /api/v1/crawl-runs", s.handleListCrawlRuns)
	mux.HandleFunc("GET /api/v1/crawl-runs/{id}", s.handleGetCrawlRun)

	mux.HandleFunc("GET /openapi.yaml", handleOpenAPISpec)
	mux.HandleFunc("GET /docs", handleSwaggerUI)
	mux.HandleFunc("GET /docs/", handleSwaggerUI)
	mux.HandleFunc("GET /", handleRoot)

	return mux
}

func handleHealthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func handleRoot(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	http.Redirect(w, r, "/docs", http.StatusFound)
}

// handleListDocuments serves
// GET /api/v1/documents?category=&limit=&offset=&crawl_run_id=&country=.
// category is required: the underlying query is scoped to one category at
// a time (see internal/db/queries.sql.go ListDocumentsByCategory) -- GET
// /api/v1/documents/categories lists the valid values and how many
// documents each has. crawl_run_id is optional: pass it to narrow the
// category down to just the documents one specific (already
// validated via GET /api/v1/crawl-runs/{id}) run produced. country is
// optional: an ISO 3166-1 alpha-2 code (e.g. "NP") to narrow to just that
// origin country -- how an ETL consumer scoped to only Nepal would query
// this endpoint.
func (s *Server) handleListDocuments(w http.ResponseWriter, r *http.Request) {
	category := r.URL.Query().Get("category")
	if category == "" {
		writeError(w, http.StatusBadRequest, "category query parameter is required (see GET /api/v1/documents/categories for valid values)")
		return
	}

	limit, err := parseBoundedInt(r.URL.Query().Get("limit"), defaultLimit, 1, maxLimit)
	if err != nil {
		writeError(w, http.StatusBadRequest, "limit must be an integer between 1 and "+strconv.Itoa(maxLimit))
		return
	}
	offset, err := parseBoundedInt(r.URL.Query().Get("offset"), 0, 0, 1<<31-1)
	if err != nil {
		writeError(w, http.StatusBadRequest, "offset must be a non-negative integer")
		return
	}

	var crawlRunID pgtype.Int8
	if raw := r.URL.Query().Get("crawl_run_id"); raw != "" {
		id, err := strconv.ParseInt(raw, 10, 64)
		if err != nil {
			writeError(w, http.StatusBadRequest, "crawl_run_id must be an integer")
			return
		}
		crawlRunID = pgtype.Int8{Int64: id, Valid: true}
	}

	var country pgtype.Text
	if raw := r.URL.Query().Get("country"); raw != "" {
		country = pgtype.Text{String: strings.ToUpper(raw), Valid: true}
	}

	docs, err := s.queries.ListDocumentsByCategory(r.Context(), db.ListDocumentsByCategoryParams{
		Category:   category,
		Limit:      int32(limit),
		Offset:     int32(offset),
		CrawlRunID: crawlRunID,
		Country:    country,
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list documents")
		return
	}
	if docs == nil {
		docs = []db.Document{}
	}

	resp := map[string]any{
		"category": category,
		"limit":    limit,
		"offset":   offset,
		"count":    len(docs),
		"items":    docs,
	}
	if crawlRunID.Valid {
		resp["crawl_run_id"] = crawlRunID.Int64
	}
	if country.Valid {
		resp["country"] = country.String
	}
	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) handleCountDocuments(w http.ResponseWriter, r *http.Request) {
	count, err := s.queries.CountDocuments(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to count documents")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int64{"total": count})
}

func (s *Server) handleCountByCategory(w http.ResponseWriter, r *http.Request) {
	rows, err := s.queries.CountDocumentsByCategory(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to count documents by category")
		return
	}
	if rows == nil {
		rows = []db.CountDocumentsByCategoryRow{}
	}
	writeJSON(w, http.StatusOK, rows)
}

// handleListCrawlRuns serves GET /api/v1/crawl-runs?limit=&offset=. This is
// the validation summary another team should check before consuming a
// batch of documents: was the run completed or did it fail, and how many
// pages succeeded/failed/were skipped.
func (s *Server) handleListCrawlRuns(w http.ResponseWriter, r *http.Request) {
	limit, err := parseBoundedInt(r.URL.Query().Get("limit"), defaultLimit, 1, maxLimit)
	if err != nil {
		writeError(w, http.StatusBadRequest, "limit must be an integer between 1 and "+strconv.Itoa(maxLimit))
		return
	}
	offset, err := parseBoundedInt(r.URL.Query().Get("offset"), 0, 0, 1<<31-1)
	if err != nil {
		writeError(w, http.StatusBadRequest, "offset must be a non-negative integer")
		return
	}

	runs, err := s.queries.ListCrawlRuns(r.Context(), db.ListCrawlRunsParams{
		Limit:  int32(limit),
		Offset: int32(offset),
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list crawl runs")
		return
	}
	if runs == nil {
		runs = []db.CrawlRun{}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"limit":  limit,
		"offset": offset,
		"count":  len(runs),
		"items":  runs,
	})
}

// handleGetCrawlRun serves GET /api/v1/crawl-runs/{id}: the full validation
// summary for one run.
func (s *Server) handleGetCrawlRun(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "id must be an integer")
		return
	}

	run, err := s.queries.GetCrawlRun(r.Context(), id)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "crawl run not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to get crawl run")
		return
	}
	writeJSON(w, http.StatusOK, run)
}

func parseBoundedInt(raw string, def, min, max int) (int, error) {
	if raw == "" {
		return def, nil
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return 0, err
	}
	if v < min || v > max {
		return 0, errors.New("out of range")
	}
	return v, nil
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
