// Package model defines the data shapes shared across the crawler pipeline.
package model

import "time"

// Document is the ETL record produced by the crawler for a single crawled
// page. It is intentionally storage-agnostic: the same struct is written to
// NDJSON in Phase 1 and can be marshalled onto a queue (Kafka/NATS) or a
// document store in later phases without changing the crawler internals.
type Document struct {
	URL string `json:"url"`
	// NormalizedURL is this document's dedupe identity: normalize.Canonical
	// of the fetched URL, UNLESS the page declared a
	// <link rel="canonical">, in which case it's that declared target
	// instead (see CanonicalURL) -- two different fetched URLs (tracking
	// params, an AMP variant, ...) that both declare the same canonical
	// collapse to one row via the (normalized_url, content_hash) unique
	// constraint instead of duplicating.
	NormalizedURL string `json:"normalized_url"`
	// Host is the fetched page's hostname, kept as its own field (beyond
	// being derivable from URL) so downstream consumers -- and the
	// CountryFilter crawl option -- can group/filter documents by site
	// without re-parsing a URL.
	Host string `json:"host,omitempty"`
	// FinalURL is where the response actually came from after following
	// any redirects (absolute, canonicalized), or "" if the request wasn't
	// redirected at all. Without this, a 301'd URL's real destination is
	// only visible via NormalizedURL, indistinguishable from a page
	// reached directly.
	FinalURL string `json:"final_url,omitempty"`
	// CanonicalURL is the page's declared canonical target (absolute,
	// canonicalized), or "" if it didn't declare one or the declared
	// target matched its own NormalizedURL. Kept separately so it's
	// visible which documents were canonicalized vs. fetched directly.
	CanonicalURL string `json:"canonical_url,omitempty"`
	Category     string `json:"category,omitempty"`
	Title        string `json:"title"`
	// MetaDescription is <meta name="description"> content, falling back to
	// og:description when the page declares only the Open Graph variant --
	// the snippet a real search engine shows under a result's title, so
	// it's carried as its own field rather than left buried in Text.
	MetaDescription string            `json:"meta_description,omitempty"`
	MetaKeywords    []string          `json:"meta_keywords,omitempty"`
	OpenGraph       map[string]string `json:"open_graph,omitempty"`
	ContactInfo     ContactInfo       `json:"contact_info,omitempty"`
	SocialLinks     []string          `json:"social_links,omitempty"`
	// Text is marshalled as "text" here, but internal/api/openapi.yaml's
	// Document schema calls this field "body_text" -- a pre-existing drift
	// that didn't matter while the API read from Postgres (its response
	// JSON was built from sqlc-generated column-named structs, not from
	// this type directly), but now does: with S3 storage, the JSON this
	// struct marshals to *is* the object body the API reads back verbatim.
	// Not renamed here -- NDJSON output and the Kafka stream (ETL's
	// consumption point) already depend on "text" being the wire name; see
	// docs/SCHEMA.md for the full list of drifted fields and Person 5's
	// options for reconciling them without breaking those consumers.
	Text string `json:"text"`
	// Headings is the page's h1-h6 outline, in document order -- the part of
	// the HTML structure a search engine actually uses as a ranking/snippet
	// signal (section headers), as opposed to the full markup tree, which
	// has no ranking value and would bloat every document for no benefit.
	Headings []Heading `json:"headings,omitempty"`
	Links    []string  `json:"links"`
	// InternalLinks/ExternalLinks split Links by whether they share the
	// page's host; ImageLinks/VideoLinks are media URLs found on the page.
	InternalLinks []string `json:"internal_links,omitempty"`
	ExternalLinks []string `json:"external_links,omitempty"`
	ImageLinks    []string `json:"image_links,omitempty"`
	VideoLinks    []string `json:"video_links,omitempty"`
	// AnchorTexts is parallel to Links (same index, same length): the
	// visible anchor text used to link to each URL, or "" if none.
	AnchorTexts []string `json:"anchor_texts,omitempty"`
	// JSONLD holds the raw text of each <script type="application/ld+json">
	// block found on the page (each element is valid JSON on its own).
	// Kept raw rather than decoded so the crawler doesn't need to know
	// about every schema.org type a downstream consumer might care about.
	JSONLD []string `json:"json_ld,omitempty"`
	// Geo is marshalled as a nested "geo": {"lat":.., "lng":..} object, but
	// openapi.yaml's Document schema has this flattened into two top-level
	// properties, geo_lat and geo_lng. See the Text field's comment above
	// for why this isn't renamed/reshaped here.
	Geo *GeoPoint `json:"geo,omitempty"`
	// Country is the page's best-guess origin country, as an ISO 3166-1
	// alpha-2 code (e.g. "NP", "IN"), or "" if no signal on the page
	// resolved one. See internal/parser.DetectCountry for the signals
	// checked and their priority order.
	Country string `json:"country,omitempty"`
	// SimHash is a 64-bit near-duplicate fingerprint of Text (see
	// internal/simhash). Two documents whose SimHash values differ in only
	// a few bits (Hamming distance) are likely near-duplicates -- useful
	// for a downstream corpus-wide dedup pass beyond the in-crawl check
	// crawl_workflow.go already does (see docs/CRAWLER_ROADMAP.md).
	SimHash uint64 `json:"sim_hash,omitempty"`
	// CrawlRunID identifies the crawl_runs row that produced this document
	// (0 if no run-tracking backend was configured for the crawl). Lets a
	// consumer filter documents down to one validated batch instead of an
	// entire category's full history -- see GET /api/v1/crawl-runs/{id}
	// for that run's health/validation summary.
	CrawlRunID  int64     `json:"crawl_run_id,omitempty"`
	Depth       int       `json:"depth"`
	StatusCode  int       `json:"status_code"`
	ContentType string    `json:"content_type"`
	ContentHash string    `json:"content_hash"`
	FetchedAt   time.Time `json:"fetched_at"`
	FetchDurMs  int64     `json:"fetch_duration_ms"`
	// Error is marshalled as "error" here, but openapi.yaml's Document
	// schema calls this field "fetch_error". See the Text field's comment
	// above for why this isn't renamed here.
	Error string `json:"error,omitempty"`
}

// Fields openapi.yaml's Document schema has that this type deliberately
// doesn't: `id`, `created_at`, and `updated_at` were Postgres row metadata
// (a SERIAL primary key and trigger-maintained timestamps), not part of
// the crawler's own domain model -- this type has no equivalent for "id"
// under S3 (the object key *is* the identity) or "updated_at" (a document
// isn't mutated in place; a re-fetch is a new write with its own
// FetchedAt). Adding fabricated equivalents here would be worse than
// leaving the gap for Person 5 to resolve at the API layer, e.g. by
// serving an S3 GetObject response's real LastModified for created_at, or
// by dropping these three properties from openapi.yaml as no-longer-
// applicable under S3 storage.

// ContactInfo contains public contact details extracted from a page.
type ContactInfo struct {
	Emails  []string `json:"emails,omitempty"`
	Phones  []string `json:"phones,omitempty"`
	Address string   `json:"address,omitempty"`
}

// Heading is one h1-h6 element from a page's outline.
type Heading struct {
	Level int    `json:"level"`
	Text  string `json:"text"`
}

// GeoPoint is a page's geo-spatial location, resolved from whichever source
// on the page had it (JSON-LD GeoCoordinates, Open Graph place tags, or
// geo.position/ICBM meta tags) -- see internal/parser for extraction order.
type GeoPoint struct {
	Lat float64 `json:"lat"`
	Lng float64 `json:"lng"`
}

// CrawlStats is emitted at the end of a run for observability. Later phases
// can push this to metrics/monitoring instead of stdout.
type CrawlStats struct {
	Fetched    int           `json:"fetched"`
	Succeeded  int           `json:"succeeded"`
	Failed     int           `json:"failed"`
	Skipped    int           `json:"skipped"`
	Duration   time.Duration `json:"duration"`
	UniqueURLs int           `json:"unique_urls"`
}
