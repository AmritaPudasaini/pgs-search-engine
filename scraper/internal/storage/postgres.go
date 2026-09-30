package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"search-engine-scraper/internal/db"
	"search-engine-scraper/internal/model"
)

// PostgresWriter persists documents to Postgres via sqlc-generated queries.
// Unlike NDJSONWriter's in-memory content-hash dedupe (which only protects
// against duplicate writes within one worker process's lifetime), this is
// fully idempotent across restarts and across every worker in the fleet: a
// retried WriteDocument activity lands on the same row via the
// normalized_url UNIQUE constraint (see
// migrations/0009_fix_unique_constraint_and_revisit.up.sql -- originally
// (normalized_url, content_hash), fixed since a revisit whose content
// changed needs to update the existing row, not insert a new one),
// enforced by Postgres itself rather than by worker-local state. This is
// the right choice for a multi-replica Kubernetes deployment where several
// worker pods write concurrently -- there is no single process whose
// in-memory map could dedupe across all of them.
type PostgresWriter struct {
	pool    *pgxpool.Pool
	queries *db.Queries
}

// NewPostgresWriter connects to databaseURL and returns a Writer backed by
// it. The `documents` table must already exist -- run the migrations in
// migrations/ first (see Makefile's `migrate-up` target).
func NewPostgresWriter(ctx context.Context, databaseURL string) (*PostgresWriter, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("connect to postgres: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping postgres: %w", err)
	}
	return &PostgresWriter{pool: pool, queries: db.New(pool)}, nil
}

// Write upserts one document. Safe for concurrent use: pgxpool.Pool itself
// is a connection pool safe for concurrent queries, so no additional
// locking is needed here (unlike NDJSONWriter, which serializes access to
// a single file handle).
func (w *PostgresWriter) Write(doc *model.Document) error {
	var geoLat, geoLng pgtype.Float8
	if doc.Geo != nil {
		geoLat = pgtype.Float8{Float64: doc.Geo.Lat, Valid: true}
		geoLng = pgtype.Float8{Float64: doc.Geo.Lng, Valid: true}
	}
	var crawlRunID pgtype.Int8
	if doc.CrawlRunID != 0 {
		crawlRunID = pgtype.Int8{Int64: doc.CrawlRunID, Valid: true}
	}

	// headings is stored as JSONB; a nil/empty slice must still marshal to
	// "[]" (not fail, not write SQL NULL into a NOT NULL column).
	headings, err := json.Marshal(doc.Headings)
	if err != nil {
		return fmt.Errorf("marshal headings for %s: %w", doc.URL, err)
	}

	_, err = w.queries.UpsertDocument(context.Background(), db.UpsertDocumentParams{
		Url:             doc.URL,
		NormalizedUrl:   doc.NormalizedURL,
		Category:        doc.Category,
		Title:           doc.Title,
		BodyText:        doc.Text,
		Links:           nonNilStrings(doc.Links),
		Depth:           int32(doc.Depth),
		StatusCode:      int32(doc.StatusCode),
		ContentType:     doc.ContentType,
		ContentHash:     doc.ContentHash,
		FetchDurationMs: doc.FetchDurMs,
		FetchError:      doc.Error,
		FetchedAt:       pgtype.Timestamptz{Time: doc.FetchedAt, Valid: true},
		JsonLd:          nonNilStrings(doc.JSONLD),
		GeoLat:          geoLat,
		GeoLng:          geoLng,
		AnchorTexts:     nonNilStrings(doc.AnchorTexts),
		CrawlRunID:      crawlRunID,
		CanonicalUrl:    doc.CanonicalURL,
		FinalUrl:        doc.FinalURL,
		SimHash:         int64(doc.SimHash),
		MetaDescription: doc.MetaDescription,
		Headings:        headings,
		Host:            doc.Host,
		Country:         doc.Country,
	})
	if err != nil {
		return fmt.Errorf("upsert document %s: %w", doc.URL, err)
	}
	return nil
}

// nonNilStrings coalesces a nil slice to an empty one. pgx sends a nil Go
// slice as SQL NULL for a TEXT[] parameter -- fine for a nullable column,
// but every one of documents' array columns (links, json_ld, anchor_texts)
// is NOT NULL DEFAULT '{}', and that default only applies when a column is
// omitted from the INSERT entirely, not when it's explicitly given NULL.
// Without this, any page with no links (or no JSON-LD, or no anchor text --
// a nil slice is normal and common, not an edge case) fails the NOT NULL
// constraint on write. Caught by actually running a live crawl against
// Postgres, not by unit tests, which all built params with non-nil slices.
func nonNilStrings(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

// Close releases the connection pool.
func (w *PostgresWriter) Close() error {
	w.pool.Close()
	return nil
}

// StartRun, UpdateRunStats, and FinishRun implement RunRecorder on top of
// the same pool/queries PostgresWriter already holds for documents, so a
// Postgres-backed crawl gets run-tracking for free without a second
// connection pool.

func (w *PostgresWriter) StartRun(ctx context.Context, in StartRunInput) (int64, error) {
	id, err := w.queries.CreateCrawlRun(ctx, db.CreateCrawlRunParams{
		SeedCount: int32(in.SeedCount),
		MaxDepth:  int32(in.MaxDepth),
		MaxPages:  int32(in.MaxPages),
	})
	if err != nil {
		return 0, fmt.Errorf("create crawl run: %w", err)
	}
	return id, nil
}

func (w *PostgresWriter) UpdateRunStats(ctx context.Context, runID int64, stats RunStats) error {
	err := w.queries.UpdateCrawlRunStats(ctx, db.UpdateCrawlRunStatsParams{
		ID:           runID,
		Fetched:      int32(stats.Fetched),
		Succeeded:    int32(stats.Succeeded),
		Failed:       int32(stats.Failed),
		Skipped:      int32(stats.Skipped),
		DomainCapped: int32(stats.DomainCapped),
	})
	if err != nil {
		return fmt.Errorf("update crawl run %d stats: %w", runID, err)
	}
	return nil
}

// FreshURLs implements FreshnessChecker on top of the same pool/queries
// PostgresWriter already holds for documents.
func (w *PostgresWriter) FreshURLs(ctx context.Context, normalizedURLs []string, since time.Time) (map[string]bool, error) {
	if len(normalizedURLs) == 0 {
		return nil, nil
	}
	rows, err := w.queries.ListFreshDocumentURLs(ctx, db.ListFreshDocumentURLsParams{
		NormalizedUrls: normalizedURLs,
		Since:          pgtype.Timestamptz{Time: since, Valid: true},
	})
	if err != nil {
		return nil, fmt.Errorf("list fresh document urls: %w", err)
	}
	fresh := make(map[string]bool, len(rows))
	for _, u := range rows {
		fresh[u] = true
	}
	return fresh, nil
}

func (w *PostgresWriter) FinishRun(ctx context.Context, runID int64, status string, stats RunStats, errMsg string) error {
	err := w.queries.FinishCrawlRun(ctx, db.FinishCrawlRunParams{
		ID:           runID,
		Status:       status,
		Fetched:      int32(stats.Fetched),
		Succeeded:    int32(stats.Succeeded),
		Failed:       int32(stats.Failed),
		Skipped:      int32(stats.Skipped),
		DomainCapped: int32(stats.DomainCapped),
		Error:        errMsg,
	})
	if err != nil {
		return fmt.Errorf("finish crawl run %d: %w", runID, err)
	}
	return nil
}
