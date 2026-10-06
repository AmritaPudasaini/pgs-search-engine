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

// PostgresWriter writes crawled documents and crawl runs to the shared Bronze
// tables (crawled_documents, crawl_runs) as the pgs_scraper role, with the
// statements of database/docs/scraper-db-contract.md. The schema belongs to
// database/'s models and Alembic migrations; sqlc generates internal/db from
// database/sql/scraper_schema.sql, which is exported from those models.
//
// Idempotent across restarts and across every worker in the fleet: a retried
// WriteDocument activity lands on the same row through the
// (normalized_url, content_hash) unique key, enforced by Postgres itself rather
// than by worker-local state.
type PostgresWriter struct {
	pool    *pgxpool.Pool
	queries *db.Queries
}

// NewPostgresWriter connects to databaseURL (the pgs_scraper role) and returns a
// Writer backed by it. The tables must already exist: the database/ migrations
// (db-migrate) create them.
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

// Write upserts one document. Safe for concurrent use: pgxpool.Pool is.
func (w *PostgresWriter) Write(doc *model.Document) error {
	params, err := crawledDocumentParams(doc)
	if err != nil {
		return err
	}
	if _, err := w.queries.UpsertCrawledDocument(context.Background(), params); err != nil {
		return fmt.Errorf("upsert crawled document %s: %w", doc.URL, err)
	}
	return nil
}

// crawledDocumentParams applies the contract's conversions (§1): an empty string
// or a zero crawl run ID is NULL, not a value; SimHash is stored bit-for-bit as
// int64; Geo and ContactInfo are flattened into their columns.
func crawledDocumentParams(doc *model.Document) (db.UpsertCrawledDocumentParams, error) {
	headings, err := jsonOrNull(doc.Headings, len(doc.Headings) > 0)
	if err != nil {
		return db.UpsertCrawledDocumentParams{}, fmt.Errorf("marshal headings for %s: %w", doc.URL, err)
	}
	openGraph, err := jsonOrNull(doc.OpenGraph, len(doc.OpenGraph) > 0)
	if err != nil {
		return db.UpsertCrawledDocumentParams{}, fmt.Errorf("marshal open graph for %s: %w", doc.URL, err)
	}
	p := db.UpsertCrawledDocumentParams{
		Host:            text(doc.Host),
		Url:             doc.URL,
		NormalizedUrl:   doc.NormalizedURL,
		FinalUrl:        text(doc.FinalURL),
		CanonicalUrl:    text(doc.CanonicalURL),
		Category:        text(doc.Category),
		Title:           text(doc.Title),
		MetaDescription: text(doc.MetaDescription),
		MetaKeywords:    doc.MetaKeywords,
		OpenGraph:       openGraph,
		Text:            text(doc.Text),
		Headings:        headings,
		JsonLd:          doc.JSONLD,
		Emails:          doc.ContactInfo.Emails,
		Phones:          doc.ContactInfo.Phones,
		Address:         text(doc.ContactInfo.Address),
		SocialLinks:     doc.SocialLinks,
		Links:           doc.Links,
		AnchorTexts:     doc.AnchorTexts,
		InternalLinks:   doc.InternalLinks,
		ExternalLinks:   doc.ExternalLinks,
		ImageLinks:      doc.ImageLinks,
		VideoLinks:      doc.VideoLinks,
		Country:         text(doc.Country),
		SimHash:         pgtype.Int8{Int64: int64(doc.SimHash), Valid: doc.SimHash != 0},
		Depth:           int32(doc.Depth),
		StatusCode:      pgtype.Int4{Int32: int32(doc.StatusCode), Valid: doc.StatusCode != 0},
		ContentType:     text(doc.ContentType),
		ContentHash:     doc.ContentHash,
		FetchedAt:       pgtype.Timestamptz{Time: doc.FetchedAt, Valid: true},
		FetchDurationMs: pgtype.Int8{Int64: doc.FetchDurMs, Valid: true},
		Error:           text(doc.Error),
	}
	if doc.CrawlRunID != 0 {
		p.CrawlRunID = pgtype.Int8{Int64: doc.CrawlRunID, Valid: true}
	}
	if doc.Geo != nil {
		p.GeoLat = pgtype.Float8{Float64: doc.Geo.Lat, Valid: true}
		p.GeoLng = pgtype.Float8{Float64: doc.Geo.Lng, Valid: true}
	}
	return p, nil
}

// text is SQL NULL for "" (an omitted value), else the string.
func text(s string) pgtype.Text {
	return pgtype.Text{String: s, Valid: s != ""}
}

// jsonOrNull marshals v for a JSONB column, or returns nil (SQL NULL) when
// present is false.
func jsonOrNull(v any, present bool) ([]byte, error) {
	if !present {
		return nil, nil
	}
	return json.Marshal(v)
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
		SeedCount: pgtype.Int4{Int32: int32(in.SeedCount), Valid: true},
		MaxDepth:  pgtype.Int4{Int32: int32(in.MaxDepth), Valid: true},
		MaxPages:  pgtype.Int4{Int32: int32(in.MaxPages), Valid: true},
	})
	if err != nil {
		return 0, fmt.Errorf("create crawl run: %w", err)
	}
	return id, nil
}

func (w *PostgresWriter) UpdateRunStats(ctx context.Context, runID int64, stats RunStats) error {
	err := w.queries.UpdateCrawlRunStats(ctx, db.UpdateCrawlRunStatsParams{
		ID:                runID,
		FetchedCount:      int32(stats.Fetched),
		SucceededCount:    int32(stats.Succeeded),
		FailedCount:       int32(stats.Failed),
		SkippedCount:      int32(stats.Skipped),
		DomainCappedCount: int32(stats.DomainCapped),
	})
	if err != nil {
		return fmt.Errorf("update crawl run %d stats: %w", runID, err)
	}
	return nil
}

// FreshURLs implements FreshnessChecker on top of the same pool/queries
// PostgresWriter already holds for documents (any version of the URL counts).
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
		ID:                runID,
		Status:            status,
		FetchedCount:      int32(stats.Fetched),
		SucceededCount:    int32(stats.Succeeded),
		FailedCount:       int32(stats.Failed),
		SkippedCount:      int32(stats.Skipped),
		DomainCappedCount: int32(stats.DomainCapped),
		Error:             text(errMsg),
	})
	if err != nil {
		return fmt.Errorf("finish crawl run %d: %w", runID, err)
	}
	return nil
}
