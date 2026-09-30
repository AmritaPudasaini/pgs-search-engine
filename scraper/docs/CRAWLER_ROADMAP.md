# Crawler roadmap: what's done, what's left

This project's scope is the **scraping stage only** — a separate team/phase
owns ETL, ranking/search algorithm, and UI on top of what this crawler
produces. This doc exists so a future session (or a teammate) can pick up
where the last one left off without re-deriving context: what was fixed,
why, and what's still a known gap before this crawler's output is fully
"handoff ready" for those other teams.

## Fixed so far

### 1. 429 (rate limit) handling
`internal/activities/activities.go` previously treated HTTP 429 the same as
a 404 — a permanent failure, never retried, no slowdown. Fixed: 429 is now
its own case, returned as a retryable Temporal `ApplicationError` with
`NextRetryDelay` set from the response's `Retry-After` header (seconds or
HTTP-date per RFC 9110; falls back to 30s if absent/unparsable, capped at
5 minutes). See `parseRetryAfter`.

### 2. JSON-LD extraction
`internal/parser/parser.go` now captures the raw text of every
`<script type="application/ld+json">` block that parses as valid JSON, in
`Parsed.JSONLD` / `model.Document.JSONLD`. Kept as raw strings (not
decoded into a fixed struct) so the crawler doesn't need to know every
schema.org type a downstream consumer might care about — that decoding is
the ETL team's job.

### 3. Geo-spatial extraction
`model.GeoPoint{Lat, Lng}` resolved with priority: JSON-LD
`GeoCoordinates` (searched recursively, anywhere in the graph — e.g.
nested under a `Place`/`LocalBusiness`'s `geo` property) → Open Graph
`place:location:latitude/longitude` → `<meta name="geo.position">` →
`<meta name="ICBM">`. See `geoFromJSONLD`/`findGeoCoordinates` and
`parseDelimited`/`parseLatLng` in `parser.go`.

### 4. Anchor text capture
`Parsed.AnchorTexts` / `model.Document.AnchorTexts` is parallel to `Links`
(same index, same length): the visible text of the first `<a>` tag seen
for each URL. This is the input a future ranking/search-algorithm team
needs to build "what text do other pages use to describe this URL" —
without it, `Links` was just a bag of URLs with no relevance signal
attached.

### 5. Postgres schema + OpenAPI kept in sync
Migrations `0002`–`0003` added `json_ld`, `geo_lat`/`geo_lng`, and
`anchor_texts` columns; `sqlc generate` was re-run each time.
`internal/api/openapi.yaml` (the Swagger doc at `/docs`, the actual
contract other teams read) is now in sync with what the API returns —
it had drifted out of sync earlier in this project and briefly documented
a stale schema.

### 6. Crawl-run validation summary (this session)
Added a `crawl_runs` table (migration `0004`) and a
`storage.RunRecorder` interface (`internal/storage/run_recorder.go`,
implemented by `PostgresWriter`, no-op'd by `NoopRunRecorder` when
`--storage=ndjson`) so every crawl gets a health record another team can
check **before consuming a batch of documents**: status
(`running`/`completed`/`failed`), fetched/succeeded/failed/skipped/
domain_capped counts, start/finish times.

- `CrawlWorkflow` (`internal/workflows/crawl_workflow.go`) starts a run on
  its first segment, updates stats on every Continue-As-New handoff (so
  progress is visible mid-crawl, not just after), and finalizes the row
  when the crawl actually terminates (`willContinueAsNew` distinguishes a
  true finish from "hit the per-segment checkpoint at the same moment the
  queue happened to drain" — don't conflate the two when reading this
  code).
- Run-tracking is deliberately **best-effort**: a failure to
  start/update/finish the run record is logged but never fails the crawl
  itself. It's a validation aid, not load-bearing.
- New endpoints: `GET /api/v1/crawl-runs` (list, newest first) and
  `GET /api/v1/crawl-runs/{id}` (single run). `cmd/scraper` prints the
  run ID + a pointer to the endpoint when a crawl finishes.

### 7. Documents linked to their crawl run
Migration `0005` added `documents.crawl_run_id` (nullable FK to
`crawl_runs.id`, indexed). `model.Document.CrawlRunID` is set from the
workflow's `runID` when building each document (0/omitted if no
run-tracking backend was configured for that crawl).
`GET /api/v1/documents` now accepts an optional `crawl_run_id` query param
(`ListDocumentsByCategory` in `queries.sql` uses `sqlc.narg` so the filter
is a no-op when omitted) — so a consuming team can now do both: check
`GET /api/v1/crawl-runs/{id}` for a run's health, then
`GET /api/v1/documents?category=...&crawl_run_id=...` for just that run's
documents, instead of an entire category's full history.

### 8. Boilerplate stripping from `Text`
`parser.go`'s `extractMainText` now excludes text two ways, while still
crawling any links found inside the excluded regions (a nav menu's links
are still worth fetching even though its text isn't article content):

- **Structural tags** (`boilerplateTags`): `nav`, `header`, `footer`,
  `aside`, `form` contribute no text at all. Trade-off: an in-article
  `<header>` (some blog themes wrap the headline/byline in one) also gets
  excluded — accepted since `Title` is captured separately from `<title>`.
- **Link density** (`blockTags` + `linkDensityThreshold`): a `p`/`li`/`td`/
  heading/etc. block whose text is ≥60% link characters (and at least 20
  chars, so short blocks aren't misjudged off a tiny sample) is dropped as
  a teaser/menu list even when it isn't wrapped in a semantic chrome tag.
  A paragraph with one or two inline links stays well under the threshold
  and is kept.

**Known limitation**: the link-density check only runs at `blockTags`
granularity. A large non-semantic wrapper (e.g. a `<div class="sidebar">`
full of links with no `<aside>` and no per-item `<li>`/`<p>` wrapping)
isn't caught — this would need density computed on arbitrary `div`/
`section` containers, which risks false positives on legitimate content
divs and was left out of this pass.

### 9. `<link rel="canonical">` handling
`parser.go` now extracts the first `<link rel="canonical" href="...">`
found in `<head>` (absolute + canonicalized via the same `normalize.Resolve`
used for `<a>` hrefs) into `Parsed.CanonicalURL`. `activities.ProcessPage`
then uses it as the document's dedupe identity when present and different
from the fetched URL's own normalized form: `NormalizedURL` becomes the
*declared* canonical, and `CanonicalURL` records what was declared,
separately, for transparency (`model.Document.CanonicalURL`, migration
`0006`). Two fetched URLs that both declare the same canonical (tracking
params, an AMP variant, ...) now collapse to one row via the
`(normalized_url, content_hash)` unique constraint instead of duplicating.

As a bonus, `crawl_workflow.go` also marks a declared canonical target as
`seen` right after processing the page that named it — so if some other
page later links directly to that canonical URL, the frontier skips
re-fetching a duplicate of content already captured under that identity.

**Known limitation**: this only catches duplicates where the page itself
declares its canonical. Two URLs that both lack a `rel=canonical` tag but
happen to serve identical content (no declared relationship between them)
still land as separate documents — that's the near-duplicate-detection gap
(simhash/minhash) below, a different and harder problem.

### 10. Charset/encoding detection
`parser.Parse` now takes a third argument, the HTTP response's raw
Content-Type header value, and wraps the body in
`golang.org/x/net/html/charset.NewReader` before handing it to
`html.Parse`. That function determines the encoding by checking, in order:
a byte-order-mark, the `charset=` param on the Content-Type header, a
`<meta charset>`/`<meta http-equiv=Content-Type>` tag sniffed from the
first 1024 bytes of the document, then finally defaulting to UTF-8 -- the
same precedence the HTML5 spec defines. `activities.go`'s call site passes
`out.ContentType` (already captured from the fetch) as that third
argument. `golang.org/x/text` moved from an indirect to a direct
dependency (the test suite imports `encoding/charmap` directly to
construct ISO-8859-1 fixtures).

Before this, a non-UTF-8 page would parse "successfully" but produce
garbled `Title`/`Text` with no error flag -- wrong data indistinguishable
from valid data, which is worse than an explicit failure.

### 11. Per-host concurrency limit
`CrawlWorkflowInput.MaxConcurrentPerHost` (CLI: `--max-concurrent-per-host`,
default 0/unlimited) caps how many fetches to any single host may be in
flight at once, independent of the global `Concurrency`/`--concurrency`
cap. `crawl_workflow.go`'s `startNext` now scans the whole queue (not just
its front) for the first startable item: one whose host is already at
`MaxConcurrentPerHost` is skipped (left in the queue, retried once that
host frees a slot) rather than dropped, while one whose host already hit
`MaxPagesPerDomain` is still dropped permanently as before. A new
`activeHostCounts` map tracks fetches currently in flight per host
(distinct from `domainCounts`, which is a running total across the whole
crawl for `MaxPagesPerDomain`) -- incremented when a fetch starts,
decremented when it completes.

Covered by `internal/workflows/crawl_workflow_test.go` -- the project's
first workflow-level test, using `go.temporal.io/sdk/testsuite`. Two
tests: one proves `MaxConcurrentPerHost=1` actually serializes 5 same-host
fetches (a real sleep + counter in the mocked activity catches genuine
overlap, not just "did it crash"), the other is a control case proving
`MaxConcurrentPerHost=0` still allows real overlap under the same
`Concurrency=5` -- guards against a fix that accidentally always
throttles to 1 regardless of the setting.

### 12. `sitemap.xml` discovery
`internal/robots/robots.go`'s `parse()` now also collects `Sitemap:`
directives (`ruleSet.sitemaps`) -- these aren't scoped to a `User-agent`
group per the sitemaps.org convention, so they're attached to whichever
ruleSet ends up returned regardless of matched agent. New `Guard.Sitemaps()`
accessor exposes them.

New package `internal/sitemap` parses both sitemap document shapes with one
generic struct (`url>loc` for a plain urlset, `sitemap>loc` for a
sitemapindex -- `encoding/xml` doesn't require the root element's own name
to match, so one struct handles both without a type switch). New activity
`activities.DiscoverSitemapURLs`: checks `robots.txt` for declared
sitemaps, falls back to the conventional `/sitemap.xml` path if none are
declared, fetches each one, and recurses into a sitemapindex's children
(capped at `maxChildSitemaps = 10`, total pages capped at
`maxSitemapURLs = 1000` so one activity result stays bounded). Called once
per seed on a crawl's first segment (`crawl_workflow.go`, under its own
60s/2-attempt `ActivityOptions` since it makes several sequential fetches),
with discovered URLs merged into the initial frontier at depth 0 the same
way seeds are. Best-effort throughout: any failure (bad seed URL, no
sitemap anywhere, malformed XML) yields an empty result and a `nil` error
rather than failing the crawl, since link-following still works without it.

Tests: `internal/robots/robots_test.go` (sitemaps apply regardless of
matched UA group), `internal/sitemap/sitemap_test.go` (both document
shapes + invalid XML), `internal/activities/activities_test.go` (an
`httptest.Server` fixture proving sitemapindex recursion and the
`/sitemap.xml` fallback actually work end-to-end, not just parse in
isolation), and `internal/workflows/crawl_workflow_test.go` (proving
discovered URLs actually reach the frontier and get fetched, not just
requested).

### 13. Page-level `noindex` handling
`internal/parser/parser.go` now extracts `<meta name="robots" content="...">`
into `Parsed.RobotsNoIndex`/`RobotsNoFollow` via a new exported
`ParseRobotsDirectives` helper (handles `noindex`, `nofollow`, and `none` as
shorthand for both; unrecognized tokens like `noarchive` are ignored).
`activities.ProcessPage` combines that with any `X-Robots-Tag` response
header(s) via the same helper -- `xRobotsTagDirectives` strips an optional
bot-name prefix (`"googlebot: noindex"`) before parsing, since that header
can be bot-scoped per Google's spec.

The two directives are deliberately independent, not one combined
"skip this page" flag: NoIndex means don't persist it as a Document,
NoFollow means don't follow its links -- a page can be either without the
other. `crawl_workflow.go`'s switch was restructured around a `parsedOK`
flag (true whenever a page was actually fetched+parsed, regardless of
whether it gets written) so link-traversal and canonical-seen-marking now
happen for a NoIndex page too, gated separately on `!res.NoFollow`.
NoIndexed pages are counted under the existing `Skipped` stat rather than a
new counter -- deliberately not expanding `crawl_runs`' schema again for a
third "fetched but not indexed" reason alongside robots.txt-disallowed and
non-HTML.

Tests: `parser_test.go` (meta directive combinations, `none` shorthand,
absence, unrecognized tokens), `activities_test.go` (`ProcessPage` against
a real `httptest.Server`, table-driven over meta+header combinations
including the bot-prefixed header case), and a `crawl_workflow_test.go`
case proving NoIndex and NoFollow are actually handled independently end
to end -- a NoIndex seed's link still gets fetched, a NoFollow seed still
gets written but its link is never fetched.

### 14. Redirect chain / final-URL tracking
`internal/fetcher/fetcher.go`'s `Result` gained `FinalURL` (where the
response actually came from after following redirects) and `RedirectChain`
(each hop's target, in order). Captured via a per-`Get()`-call accumulator
threaded through `context.WithValue` -- **not** a mutable field on the
shared `*http.Client`/`CheckRedirect` closure, which would have been a real
concurrency bug (interleaved chains from concurrent `Get()` calls sharing
one accumulator). Go's redirect-following loop copies the *original*
request's context onto every subsequent redirect request
(`net/http/client.go`, `req.ctx = ireq.ctx`), so each top-level call's chain
only ever sees its own hops regardless of how many other fetches are
running concurrently on the same `*Fetcher` -- verified by
`fetcher_test.go`'s `TestGet_ConcurrentRedirectsDontCrossContaminate`
(20 concurrent redirect chains, asserting none of them saw another's hops).

`activities.ProcessPage` uses `FinalURL` (canonicalized) as the dedupe
identity when a redirect actually changed it, with the same precedence
rule already established for `CanonicalURL`: a `<link rel="canonical">`
declared on the final page still overrides a same-identity-via-redirect
result. `crawl_workflow.go` also marks `res.FinalURL` `seen` after
processing a page, mirroring the existing `CanonicalURL` dedup so a link
discovered elsewhere pointing straight at a redirect's destination doesn't
trigger a duplicate fetch. New `model.Document.FinalURL` field (migration
`0007`, `final_url` column) records it distinctly from `URL` (the
originally requested one) and `NormalizedURL` (the resolved identity).

`RedirectChain` (the full hop-by-hop path, not just start/end) is
available on `fetcher.Result` but deliberately **not** threaded through to
`model.Document`/Postgres -- the stated gap was specifically about losing
the final destination, and a full chain column would be schema growth
beyond what's actually needed; it stays available at the fetcher level if
a future need for it shows up (e.g. debugging a specific site's redirect
behavior).

### 15. Near-duplicate detection (simhash)
New package `internal/simhash` implements Charikar's simhash: word-frequency
weighted bit-voting over per-word FNV-1a hashes, producing a 64-bit
fingerprint where similar documents differ in only a few bits (unlike a
cryptographic content hash, where a single differing byte produces a
completely unrelated digest). `parser.Parse` computes it from the full
extracted `Text` (`Parsed.SimHash`) and it flows through
`ProcessPageOutput.SimHash` to `model.Document.SimHash` (migration `0008`,
stored as a signed `BIGINT` holding the `uint64` bit pattern -- Postgres has
no unsigned 64-bit type, so it round-trips via a plain `int64(uint64(...))`
conversion in `internal/storage`, never arithmetic).

`crawl_workflow.go` carries every written document's fingerprint forward in
`CrawlWorkflowInput.SimHashes` (across Continue-As-New, same pattern as
`Seen`/`DomainCounts`) and checks each new page against it
(`simhash.AnyWithin`, threshold `nearDupHammingThreshold = 3` bits) --
a match means "already have equivalent content this crawl", so the page is
skipped (same `Skipped` stat as `NoIndex`, for the same "don't grow
`crawl_runs`' schema for a fourth 'fetched but not indexed' reason"
rationale already established there) rather than written as a second,
seemingly-unrelated document. Guarded by `minTextLenForNearDupCheck = 100`:
below that, a low-text or truly empty page's fingerprint is low-signal (an
all-zero fingerprint for empty text would otherwise spuriously "match"
every other empty-text page), so the check is skipped entirely rather than
risk collapsing genuinely distinct low-text pages together.

**Known scaling limitation** (stated directly in the code): this is an
**in-crawl** check only, comparing against fingerprints from the current
crawl's own history, not the whole persisted corpus -- catching duplicates
across separate crawl runs (or against years of accumulated history) would
need a real approximate-nearest-neighbor index (LSH banding across multiple
hash tables), which is corpus-scale infrastructure appropriately left to
whichever team owns search/ranking, not this crawler. Even within one
crawl, the check is an O(n) scan per page against everything written so
far, so a very large `MaxPages` run pays O(n²) total -- fine at this
project's scale, not at web scale.

Tests: `simhash_test.go` (identical/near-duplicate/unrelated text,
symmetry, `AnyWithin`), a `parser_test.go` case proving two pages sharing a
body but differing by a timestamp land within the threshold end-to-end,
and a `crawl_workflow_test.go` case proving a near-duplicate seed is
actually skipped (not written) while an unrelated one still is.

### 16. Observability/metrics
New package `internal/metrics` defines three Prometheus metrics, all
registered via `promauto` against the default registry:

- `crawler_pages_fetched_total{outcome}` -- every `ProcessPage` attempt,
  labeled by outcome (`success`, `client_error`, `server_error`,
  `rate_limited`, `network_error`, `parse_error`, `skipped_robots`,
  `skipped_non_html`). `rate(crawler_pages_fetched_total[1m])` is pages/sec;
  the error-ish outcomes' rate over the total rate is error rate -- no
  separate gauge needed for either, that's what Prometheus's `rate()`
  already gives you over a counter.
- `crawler_fetch_duration_seconds` -- a histogram of HTTP fetch duration,
  for requests that got a response (excludes `skipped_robots`, which never
  fetches, and `network_error`, which never gets one).
- `crawler_rate_limited_total{host}` -- 429s specifically, broken down by
  host, since the all-outcomes-together counter above can't answer "which
  site is throttling us" on its own.

`activities.ProcessPage` records these inline at each of its return points
(explicit per-branch, not a single deferred classifier -- with ~7 distinct
outcomes each needing different context to identify, explicit recording at
each site is clearer and less fragile than reverse-engineering the outcome
from the returned error afterward). `cmd/worker/main.go` serves them on
`--metrics-address` (default `:9090`) via `promhttp.Handler()`, started
best-effort in a goroutine before the Temporal client connects -- a
metrics-port conflict shouldn't take down the crawler itself, only
observability into it.

This is deliberately **activity/fetch-level** only, distinct in kind from
the crawl-runs validation summary (fixed item #6): that's a post-hoc/polled
per-run health record queried through the API; these are real-time,
scrape-based, and survive across runs/workers for a dashboard or alert rule
("429 rate spiked in the last 5 minutes") that a database row polled
per-run can't give you. Workflow-level business decisions (a page being
skipped for `NoIndex` or as a near-duplicate) are intentionally NOT
reflected here -- those aren't fetch outcomes, and folding them in would
blur what these metrics answer ("is fetching working") with what the
crawl-runs summary already answers ("was this run's output healthy").

Tests: `metrics_test.go` covers the counters directly and, importantly,
serves them through a real `promhttp.Handler()` over an actual HTTP server
to prove the exact registration/scrape wiring `cmd/worker` uses actually
works (catches a defined-but-unregistered metric or a name typo that would
silently produce an empty scrape). `activities_test.go` proves `ProcessPage`
increments the right counter for five different real HTTP outcomes
(success, 404, 500, 429, wrong-content-type) against an `httptest.Server`.

### 17. Revisit/freshness policy
New `CrawlWorkflowInput.RevisitAfter` (CLI: `--revisit-after`, default 0 =
disabled) is the policy: a candidate URL -- seed, sitemap-discovered, or a
discovered link -- with a document already on file fetched more recently
than `RevisitAfter` is skipped rather than (re-)fetched, so a repeated
crawl (e.g. a nightly run against the same seeds) doesn't blindly re-fetch
everything every time, nor sit on stale content forever. Zero disables the
policy entirely -- no `CheckFreshness` activity calls happen at all, and
every candidate is fetched, the exact pre-existing behavior.

**A real bug was found and fixed along the way**: the original
`documents` table had `UNIQUE (normalized_url, content_hash)`, and its own
migration comment claimed "a changed page's fields are refreshed in place"
-- but that's only true if the row's `content_hash` happens to match the
new fetch's. Since a content change necessarily changes `content_hash`,
`ON CONFLICT` would never match an existing row for a page whose content
changed, silently INSERTING A SECOND ROW per URL per distinct content
version ever seen, rather than updating in place. This would have made the
revisit policy nearly pointless (revisiting + content changing = growing
duplicate rows instead of one current one), so migration `0009` drops that
constraint for `UNIQUE (normalized_url)` alone -- one row per URL,
always reflecting its latest crawled state -- and `content_hash` (which
was missing from the `UPDATE SET` list entirely, since it never needed
updating under the old constraint) was added there too.

New `storage.FreshnessChecker` interface (implemented by `PostgresWriter`
via a batched `= ANY($1)` query against the new `ListFreshDocumentURLs`
query; `NoopFreshnessChecker` for `--storage=ndjson`, which has no
queryable history) mirrors the existing `RunRecorder` pattern. New
`activities.CheckFreshness` takes a batch of candidate URLs (not one call
per URL -- same batching philosophy as `DiscoverSitemapURLs`) and returns
which are fresh. `crawl_workflow.go` calls it once per logical group
(all seeds together, each seed's sitemap results, each page's discovered
links) via a shared `enqueueFresh` helper, rather than once per individual
URL.

Best-effort throughout, consistent with every other cross-cutting check
this crawler makes: if the freshness check activity itself fails, nothing
is treated as fresh (fetch everything) rather than risk silently dropping
pages the crawl should have visited -- wasteful, not wrong.

Tests: `activities_test.go` covers `CheckFreshness`'s delegation and its
`MaxAge` → `since` conversion, plus the empty-input short-circuit.
`crawl_workflow_test.go` proves, end to end, that a URL `CheckFreshness`
reports as fresh is never fetched while an unrelated one still is, and
(separately) that leaving `RevisitAfter` at zero makes zero `CheckFreshness`
calls at all -- the test doesn't mock that activity, so the workflow
calling it anyway would surface as a failure.

### 18. Nil-slice NOT NULL violation (found by live-running the stack)
After finishing item 17, the whole stack (`docker compose up --build`) was
actually run end-to-end for the first time this session -- migrations
against a real Postgres, a real crawl through the worker, and the API --
rather than relying on unit/mocked tests alone. A real crawl against
`https://example.com` immediately failed on write:

```
ERROR: null value in column "json_ld" of relation "documents"
violates not-null constraint (SQLSTATE 23502)
```

Cause: `pgx` sends a nil Go `[]string` as SQL `NULL` for a `TEXT[]`
parameter. `documents.json_ld`/`anchor_texts`/`links` are all
`NOT NULL DEFAULT '{}'`, but that default only applies when a column is
*omitted* from the `INSERT`, not when it's explicitly given `NULL` --
`UpsertDocument` always includes all three. A page with no JSON-LD (the
overwhelmingly common case), or no outbound links, produced a nil slice
and broke the write. No unit test caught this because every test that
builds `UpsertDocumentParams` was either mocked at the workflow level or
constructed its params with non-nil slices already.

Fixed in `internal/storage/postgres.go`: a `nonNilStrings` helper
coalesces nil to `[]string{}` for all three array fields before the
query call. Covered by `postgres_test.go` -- the `storage` package's first
test.

**Takeaway for future sessions**: this class of bug (works in every mock,
breaks on the first real write) is exactly why `make run` +
`make crawl SEEDS=...` against the real Docker stack belongs in the loop
before calling a Postgres-touching change done, not just `go test ./...`.

## Remaining gaps

None currently identified. Every gap surfaced during the audit that
produced this document (items 1–18 above) has been addressed. This section
is kept (rather than deleted) so a future session knows the roadmap was
worked through to completion, not merely never populated -- if you're
picking this up next, the natural next step is a fresh audit pass (or
addressing feedback from whichever team is now consuming this crawler's
output) rather than assuming there's a backlog waiting here.

## Explicitly out of scope for this crawler

These belong to other teams/phases, not this repo, per the stated project
split:
- Inverted index / full-text search (`tsvector`, Elasticsearch, etc.)
- Ranking algorithm (BM25, PageRank-style authority from the link graph
  now that anchor text + links are captured, ML relevance models)
- Query API / search UI

The crawler's job is to make sure whatever lands in Postgres/NDJSON for
those teams is complete, deduped, structurally clean, and verifiably
healthy (see the crawl-runs validation summary) — not to rank or serve it.
