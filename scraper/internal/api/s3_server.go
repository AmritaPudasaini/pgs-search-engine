// S3Server is an S3-backed alternative to Server (server.go), reading
// crawled documents and run manifests directly from the bucket
// internal/storage's S3Writer/S3RunRecorder write to, instead of Postgres.
//
// Added alongside Server, not in place of it: cmd/api/main.go's
// api.NewServer(db.New(pool)) call site is Person 1's file, and this
// branch doesn't touch it for the same reason
// internal/storage/postgres.go wasn't deleted (see
// docs/TASK-SPLIT-search-engine-scraper.md's Person 4 coordination note)
// -- go build ./... must stay green on this branch without assuming
// Person 1 has already wired --api-storage=s3 or similar. Wiring
// S3Server into cmd/api is Person 1's item 8 ("Confirm cmd/api/main.go
// boots the API server independently ... reading only from S3").
package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"

	"search-engine-scraper/internal/model"
	"search-engine-scraper/internal/storage"
)

// s3ReadAPI is the subset of the S3 client S3Server needs, so tests can
// supply a fake instead of talking to a real bucket / LocalStack.
type s3ReadAPI interface {
	ListObjectsV2(ctx context.Context, params *s3.ListObjectsV2Input, optFns ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	HeadBucket(ctx context.Context, params *s3.HeadBucketInput, optFns ...func(*s3.Options)) (*s3.HeadBucketOutput, error)
}

// S3Server serves the read-only documents/crawl-runs API directly from S3.
type S3Server struct {
	client    s3ReadAPI
	bucket    string
	keyPrefix string
}

// S3ServerOption configures NewS3Server.
type S3ServerOption func(*S3Server)

// WithS3ServerKeyPrefix must match whatever prefix the writer side
// (storage.WithS3KeyPrefix / WithS3RunRecorderKeyPrefix) uses against the
// same bucket, or every lookup here will miss.
func WithS3ServerKeyPrefix(prefix string) S3ServerOption {
	return func(s *S3Server) { s.keyPrefix = strings.Trim(prefix, "/") }
}

// NewS3Server builds an S3Server against bucket using client (already
// constructed by the caller via s3.NewFromConfig, same convention as
// internal/storage's NewS3Writer/NewS3FreshnessChecker/NewS3RunRecorder).
func NewS3Server(client s3ReadAPI, bucket string, opts ...S3ServerOption) *S3Server {
	s := &S3Server{client: client, bucket: bucket}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// Routes returns the HTTP handler for the S3-backed API. Same path table
// as Server.Routes, except /api/v1/documents/count and
// /api/v1/documents/categories, which return 501 -- see their handlers'
// doc comments for why.
func (s *S3Server) Routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", s.handleHealthz)

	mux.HandleFunc("GET /api/v1/documents", s.handleListDocuments)
	mux.HandleFunc("GET /api/v1/documents/count", handleNotImplementedAggregate)
	mux.HandleFunc("GET /api/v1/documents/categories", handleNotImplementedAggregate)

	mux.HandleFunc("GET /api/v1/crawl-runs", s.handleListCrawlRuns)
	mux.HandleFunc("GET /api/v1/crawl-runs/{id}", s.handleGetCrawlRun)

	mux.HandleFunc("GET /openapi.yaml", handleOpenAPISpec)
	mux.HandleFunc("GET /docs", handleSwaggerUI)
	mux.HandleFunc("GET /docs/", handleSwaggerUI)
	mux.HandleFunc("GET /", handleRoot)

	return mux
}

// handleHealthz reports S3 reachability via HeadBucket, not just "the
// process is up" -- see cmd/api's item 9 in the task-split doc. A bucket
// HeadBucket failure is reported as 503 (unhealthy), distinct from any
// other error class this API returns.
func (s *S3Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
	if _, err := s.client.HeadBucket(r.Context(), &s3.HeadBucketInput{Bucket: aws.String(s.bucket)}); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "unhealthy", "error": "bucket unreachable"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func handleNotImplementedAggregate(w http.ResponseWriter, r *http.Request) {
	writeError(w, http.StatusNotImplemented,
		"not implemented under S3 storage: a global count/category-breakdown needs a maintained "+
			"secondary index (Postgres had this via an indexed COUNT/GROUP BY); doing it as a live "+
			"full-bucket scan on every request is a real risk of an accidental self-inflicted DoS on "+
			"first production use, so this deliberately returns 501 instead. See docs/SCHEMA.md.")
}

// handleListDocuments serves
// GET /api/v1/documents?category=&crawl_run_id=&limit=&offset=&country=.
//
// Deviates from Server's Postgres-backed version in one way, documented in
// docs/SCHEMA.md's "category filtering has no S3-side index" tradeoff:
// crawl_run_id is REQUIRED here (it's optional under Postgres). Without a
// category-keyed secondary index, listing "every document in this
// category, across every run ever crawled" would mean a full-bucket
// ListObjectsV2 + GetObject scan with no upper bound -- crawl_run_id
// bounds that scan to one run's worth of objects, an explicit, documented
// behavior change rather than a silent unbounded-cost endpoint.
func (s *S3Server) handleListDocuments(w http.ResponseWriter, r *http.Request) {
	category := r.URL.Query().Get("category")
	if category == "" {
		writeError(w, http.StatusBadRequest, "category query parameter is required")
		return
	}

	rawRunID := r.URL.Query().Get("crawl_run_id")
	if rawRunID == "" {
		writeError(w, http.StatusBadRequest,
			"crawl_run_id query parameter is required under S3 storage (see docs/SCHEMA.md: "+
				"there is no category-only index, so listing must be bounded to one run's prefix)")
		return
	}
	crawlRunID, err := strconv.ParseInt(rawRunID, 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "crawl_run_id must be an integer")
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
	country := strings.ToUpper(r.URL.Query().Get("country"))

	docs, err := s.listRunDocuments(r.Context(), crawlRunID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list documents: "+err.Error())
		return
	}

	filtered := make([]model.Document, 0, len(docs))
	for _, d := range docs {
		if d.Category != category {
			continue
		}
		if country != "" && !strings.EqualFold(d.Country, country) {
			continue
		}
		filtered = append(filtered, d)
	}

	page := paginateDocuments(filtered, limit, offset)

	resp := map[string]any{
		"category":     category,
		"crawl_run_id": crawlRunID,
		"limit":        limit,
		"offset":       offset,
		"count":        len(page),
		"items":        page,
	}
	if country != "" {
		resp["country"] = country
	}
	writeJSON(w, http.StatusOK, resp)
}

// listRunDocuments lists and fetches every Document object under
// crawlRunID's prefix (excluding its _run.json manifest). O(objects in
// this run) GetObject calls -- the "full-prefix-scan cost" documented in
// docs/SCHEMA.md, bounded to one run rather than the whole bucket.
func (s *S3Server) listRunDocuments(ctx context.Context, crawlRunID int64) ([]model.Document, error) {
	prefix := s.prefixed(fmt.Sprintf("%d/", crawlRunID))
	manifestKey := s.prefixed(storage.S3RunManifestKey(crawlRunID))

	var keys []string
	var continuationToken *string
	for {
		out, err := s.client.ListObjectsV2(ctx, &s3.ListObjectsV2Input{
			Bucket:            aws.String(s.bucket),
			Prefix:            aws.String(prefix),
			ContinuationToken: continuationToken,
		})
		if err != nil {
			return nil, fmt.Errorf("list s3://%s/%s: %w", s.bucket, prefix, err)
		}
		for _, obj := range out.Contents {
			key := aws.ToString(obj.Key)
			if key == manifestKey {
				continue
			}
			keys = append(keys, key)
		}
		if !aws.ToBool(out.IsTruncated) {
			break
		}
		continuationToken = out.NextContinuationToken
	}

	docs := make([]model.Document, 0, len(keys))
	for _, key := range keys {
		doc, err := s.getDocument(ctx, key)
		if err != nil {
			return nil, fmt.Errorf("get %s: %w", key, err)
		}
		docs = append(docs, doc)
	}
	return docs, nil
}

func (s *S3Server) getDocument(ctx context.Context, key string) (model.Document, error) {
	out, err := s.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(s.bucket), Key: aws.String(key)})
	if err != nil {
		return model.Document{}, err
	}
	defer out.Body.Close()

	body, err := io.ReadAll(out.Body)
	if err != nil {
		return model.Document{}, fmt.Errorf("read body: %w", err)
	}
	var doc model.Document
	if err := json.Unmarshal(body, &doc); err != nil {
		return model.Document{}, fmt.Errorf("unmarshal: %w", err)
	}
	return doc, nil
}

// paginateDocuments applies limit/offset over an already-filtered,
// in-memory slice -- the filtering happens client-side (see
// handleListDocuments), so pagination has to happen after it, unlike
// Postgres's LIMIT/OFFSET pushed into the query itself.
func paginateDocuments(docs []model.Document, limit, offset int) []model.Document {
	if offset >= len(docs) {
		return []model.Document{}
	}
	end := offset + limit
	if end > len(docs) {
		end = len(docs)
	}
	return docs[offset:end]
}

// crawlRunResponse is the API's public CrawlRun shape (openapi.yaml),
// translated from storage.S3RunManifest -- kept as its own type rather
// than exposing the storage-layer manifest shape directly, since the two
// aren't identical (id vs run_id, the derived finished_at field).
type crawlRunResponse struct {
	ID           int64      `json:"id"`
	Status       string     `json:"status"`
	SeedCount    int        `json:"seed_count"`
	MaxDepth     int        `json:"max_depth"`
	MaxPages     int        `json:"max_pages"`
	Fetched      int        `json:"fetched"`
	Succeeded    int        `json:"succeeded"`
	Failed       int        `json:"failed"`
	Skipped      int        `json:"skipped"`
	DomainCapped int        `json:"domain_capped"`
	Error        string     `json:"error,omitempty"`
	StartedAt    time.Time  `json:"started_at"`
	FinishedAt   *time.Time `json:"finished_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
}

func toCrawlRunResponse(m storage.S3RunManifest) crawlRunResponse {
	resp := crawlRunResponse{
		ID: m.RunID, Status: m.Status, SeedCount: m.SeedCount, MaxDepth: m.MaxDepth,
		MaxPages: m.MaxPages, Fetched: m.Fetched, Succeeded: m.Succeeded, Failed: m.Failed,
		Skipped: m.Skipped, DomainCapped: m.DomainCapped, Error: m.Error,
		StartedAt: m.StartedAt, UpdatedAt: m.UpdatedAt,
	}
	// S3RunManifest has no dedicated "finished" timestamp -- FinishRun's
	// last write is the manifest's last write, so UpdatedAt already is the
	// finish time once status is terminal.
	if m.Status == "completed" || m.Status == "failed" {
		resp.FinishedAt = &m.UpdatedAt
	}
	return resp
}

// handleListCrawlRuns serves GET /api/v1/crawl-runs?limit=&offset=.
//
// Enumerates run prefixes via ListObjectsV2 with Delimiter: "/" at the
// bucket root (CommonPrefixes), skipping "latest/" (the freshness index,
// not a crawl_run_id), then GetObjects each run's _run.json -- one extra
// round-trip per run beyond the listing call itself, same tradeoff
// documented in docs/SCHEMA.md for listing at scale.
func (s *S3Server) handleListCrawlRuns(w http.ResponseWriter, r *http.Request) {
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

	runIDs, err := s.listRunIDs(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list crawl runs: "+err.Error())
		return
	}

	runs := make([]crawlRunResponse, 0, len(runIDs))
	for _, id := range runIDs {
		manifest, err := s.getManifest(r.Context(), id)
		if err != nil {
			continue // a run whose manifest 404s or fails to fetch is skipped, not a whole-request failure
		}
		runs = append(runs, toCrawlRunResponse(manifest))
	}

	sort.Slice(runs, func(i, j int) bool { return runs[i].StartedAt.After(runs[j].StartedAt) })

	end := offset + limit
	if end > len(runs) {
		end = len(runs)
	}
	var page []crawlRunResponse
	if offset < len(runs) {
		page = runs[offset:end]
	} else {
		page = []crawlRunResponse{}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"limit": limit, "offset": offset, "count": len(page), "items": page,
	})
}

func (s *S3Server) listRunIDs(ctx context.Context) ([]int64, error) {
	rootPrefix := s.keyPrefix
	if rootPrefix != "" {
		rootPrefix += "/"
	}

	var ids []int64
	var continuationToken *string
	for {
		out, err := s.client.ListObjectsV2(ctx, &s3.ListObjectsV2Input{
			Bucket:            aws.String(s.bucket),
			Prefix:            aws.String(rootPrefix),
			Delimiter:         aws.String("/"),
			ContinuationToken: continuationToken,
		})
		if err != nil {
			return nil, fmt.Errorf("list bucket root: %w", err)
		}
		for _, cp := range out.CommonPrefixes {
			name := strings.TrimSuffix(strings.TrimPrefix(aws.ToString(cp.Prefix), rootPrefix), "/")
			if name == "latest" {
				continue // the freshness index, not a crawl_run_id
			}
			id, err := strconv.ParseInt(name, 10, 64)
			if err != nil {
				continue // not a crawl_run_id-shaped prefix; ignore rather than fail the whole listing
			}
			ids = append(ids, id)
		}
		if !aws.ToBool(out.IsTruncated) {
			break
		}
		continuationToken = out.NextContinuationToken
	}
	return ids, nil
}

// handleGetCrawlRun serves GET /api/v1/crawl-runs/{id}.
func (s *S3Server) handleGetCrawlRun(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "id must be an integer")
		return
	}

	manifest, err := s.getManifest(r.Context(), id)
	if err != nil {
		if isS3NotFound(err) {
			writeError(w, http.StatusNotFound, "crawl run not found")
			return
		}
		writeError(w, http.StatusInternalServerError, "failed to get crawl run: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, toCrawlRunResponse(manifest))
}

func (s *S3Server) getManifest(ctx context.Context, runID int64) (storage.S3RunManifest, error) {
	key := s.prefixed(storage.S3RunManifestKey(runID))
	out, err := s.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(s.bucket), Key: aws.String(key)})
	if err != nil {
		return storage.S3RunManifest{}, err
	}
	defer out.Body.Close()

	body, err := io.ReadAll(out.Body)
	if err != nil {
		return storage.S3RunManifest{}, fmt.Errorf("read body: %w", err)
	}
	var m storage.S3RunManifest
	if err := json.Unmarshal(body, &m); err != nil {
		return storage.S3RunManifest{}, fmt.Errorf("unmarshal: %w", err)
	}
	return m, nil
}

func (s *S3Server) prefixed(key string) string {
	if s.keyPrefix != "" {
		return s.keyPrefix + "/" + key
	}
	return key
}

// isS3NotFound reports whether err is S3's "no such key" error, checked by
// error code rather than a specific typed error struct: GetObject's
// generated deserializer (unlike HeadObject's, which the SDK's own
// ObjectExists waiter relies on for *s3types.NotFound) doesn't reliably
// construct a typed NoSuchKey, so this checks the generic smithy.APIError
// code instead, which every S3 error implements regardless.
func isS3NotFound(err error) bool {
	var apiErr smithy.APIError
	return errors.As(err, &apiErr) && apiErr.ErrorCode() == "NoSuchKey"
}
