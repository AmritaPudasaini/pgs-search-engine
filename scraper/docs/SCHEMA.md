# S3 storage schema

The bucket layout, object shapes, and known gaps for the S3-backed storage
introduced in `internal/storage/s3_writer.go`, `s3_freshness.go`, and
`s3_run_recorder.go` (Person 4 of
`docs/TASK-SPLIT-search-engine-scraper.md`).

**Status:** implemented and unit-tested (fakes, not LocalStack -- see
"Known gaps" below). Not yet wired into `cmd/worker`'s `--storage` flag --
see the coordination note in the task-split doc's Person 4 section for
why. `internal/api/s3_server.go` (Person 5) now reads from this schema
directly; see "Category filtering" below for the tradeoff decision that
came out of that work.

## Bucket layout

Every key below may be prefixed with a fixed string (`WithS3KeyPrefix` /
`WithS3FreshnessKeyPrefix` / `WithS3RunRecorderKeyPrefix`, all three must
be set to the *same* prefix against one bucket, or documents/freshness
lookups/manifests silently stop seeing each other) -- e.g. to share one
bucket across environments: `staging/42/<hash>.json` instead of
`42/<hash>.json`.

```
<prefix?>/
├── <crawl_run_id>/
│   ├── _run.json                  # this run's manifest (see below)
│   └── <sha256(normalized_url)>.json   # one Document, written under this run
├── <crawl_run_id>/...             # every other run's own prefix
└── latest/
    └── <sha256(normalized_url)>.json   # this URL's most recent Document, any run
```

### Document objects: `<crawl_run_id>/<sha256(normalized_url)>.json`

- Content-addressed by `(crawl_run_id, normalized_url)` -- see
  `S3ObjectKey`. Concurrent worker replicas writing the same document
  within the same run overwrite the same key with identical bytes: this is
  what makes S3 storage replica-safe without a central DB doing dedupe.
- Body is exactly `model.Document` marshalled to JSON (`ContentType:
  application/json`). **This is a behavior change from Postgres**: the
  wire shape is no longer translated through sqlc-generated,
  SQL-column-named structs -- it's `model.Document`'s own JSON tags,
  verbatim. See "Known drift vs. openapi.yaml" below.
- `crawl_run_id` is not stored inside the object body as the *only* copy of
  that information -- it's also the key's own prefix, so a prefix-scoped
  `ListObjectsV2` (what `GET /api/v1/documents?crawl_run_id=N` will need to
  become, per Person 5's item 3) doesn't require reading every object's
  body just to filter by run.
- **`category` filtering has no S3-side index** -- see "Category filtering
  under S3" below for the decision Person 5 made about this.

### Latest-index objects: `latest/<sha256(normalized_url)>.json`

- Content-addressed by `normalized_url` alone, independent of
  `crawl_run_id` -- see `S3LatestObjectKey`.
- Always overwritten with the most recently fetched version of that URL,
  regardless of which run fetched it.
- **Why this exists**: a run-scoped-only key scheme
  (`<crawl_run_id>/<hash>.json`) has no single stable address to
  `HeadObject` for "was this URL fetched recently" -- a URL's
  `crawl_run_id` isn't known until it's actually been fetched. Without this
  second index, `S3FreshnessChecker` (item 3) would be impossible to
  implement as specified (a batched `HeadObject` per candidate). This was a
  gap in the original task-split plan, found and fixed while implementing
  item 2/3.
- `S3Writer.Write` PUTs both objects per document (same bytes, two keys).
  Cost: 2x the PUT volume of a run-scoped-only scheme. Not measured against
  a real bucket -- see "Known gaps."

### Run manifest objects: `<crawl_run_id>/_run.json`

- One per run, at `S3RunManifestKey(runID)`. `runID` is
  `time.Now().UnixNano()` (see `S3RunRecorder.newRunID`) -- not
  coordinated across a fleet the way a Postgres `SERIAL` is, but
  collision-checked at creation via `PutObject`'s `If-None-Match: "*"`
  (`StartRun` fails loudly on a collision rather than silently clobbering
  an in-progress run).
- Shape (`s3RunManifest`, unexported -- the read API will need its own
  equivalent, or this type should move somewhere `internal/api` can import
  it from):

  ```json
  {
    "run_id": 1735500000000000000,
    "status": "running",
    "seed_count": 3,
    "max_depth": 2,
    "max_pages": 100,
    "fetched": 42,
    "succeeded": 38,
    "failed": 2,
    "skipped": 2,
    "domain_capped": 0,
    "error": "",
    "started_at": "2026-09-29T12:00:00Z",
    "updated_at": "2026-09-29T12:03:12Z"
  }
  ```

- `status` transitions `"running"` -> `"completed"` or `"failed"`,
  read-modify-written under `If-Match: <etag>` with a bounded (3-attempt)
  retry loop on a mismatch -- see `s3_run_recorder.go`'s `updateManifest`.
- Listing every run (`GET /api/v1/crawl-runs`) becomes a
  `ListObjectsV2` scoped to `*/​_run.json`-shaped keys at the top level of
  the bucket, i.e. one level of prefixes -- S3 doesn't support that kind of
  wildcard directly. **Implemented** in `internal/api/s3_server.go`'s
  `listRunIDs`: `ListObjectsV2` with `Delimiter: "/"` against the bucket
  root to enumerate `crawl_run_id` "directories" (skipping `latest/`),
  then a `GetObject` per manifest -- no secondary `_runs_index` object,
  so this is one extra round-trip per run beyond the listing call itself.

## Category filtering under S3 (Person 5 checklist item 3)

`GET /api/v1/documents?category=X` under Postgres was an indexed `WHERE`
clause covering every document ever crawled, in any run. Two options
existed for S3:

1. **A category-keyed secondary index**, analogous to the `latest/`
   freshness index (e.g. `by-category/<category>/<hash>.json`) -- O(1)
   lookups, but a third object per `S3Writer.Write` call, and the API
   would still need to bound *that* listing somehow (a popular category
   across years of crawls is itself unbounded).
2. **A full prefix scan, client-side filter**, bounded to one
   `crawl_run_id` at a time -- what `internal/api/s3_server.go` actually
   does: `crawl_run_id` is a **required** query parameter under
   `S3Server` (optional under the Postgres-backed `Server` -- documented
   as a deliberate per-backend difference in `openapi.yaml`'s parameter
   description), `listRunDocuments` lists and `GetObject`s every Document
   under that run's prefix, and `category`/`country` are filtered
   in-memory before `limit`/`offset` pagination is applied.

**Chose option 2.** Reasoning: option 1 still doesn't solve unbounded
scope (a category spanning many runs), just moves where the scan happens;
option 2's `crawl_run_id` requirement gives a real, enforceable upper
bound (one run's worth of objects, which `--max-pages` already caps at
crawl time) with no extra write-side cost. The real downside: a caller
who genuinely wants "every `tech` document ever crawled, across all runs"
now has to issue one request per `crawl_run_id` (from `GET
/api/v1/crawl-runs`) and merge results client-side -- a real capability
loss vs. Postgres, not just a performance tradeoff, and worth flagging to
whoever consumes this API if that use case actually comes up.

## Known drift vs. `openapi.yaml`

Documented in detail as comments on the affected fields in
`internal/model/document.go` (Person 4 item 5); summarized here since it's
a storage-schema concern too:

| Go JSON tag | `openapi.yaml` property | |
| --- | --- | --- |
| `text` | `body_text` | name mismatch |
| `error` | `fetch_error` | name mismatch |
| `geo: {lat, lng}` (nested) | `geo_lat` / `geo_lng` (flat) | shape mismatch |
| *(none)* | `id`, `created_at`, `updated_at` | Postgres row metadata with no domain-model equivalent |

Not fixed in `internal/model` (would break NDJSON output and the Kafka
ETL stream, which already depend on the current names) -- Person 5 owns
reconciling this at the API layer or in `openapi.yaml` itself.

## Lifecycle policy recommendation

Run manifests (`<crawl_run_id>/_run.json`) and their documents have no
automatic expiry. Recommended bucket lifecycle rule for Person 1's
Terraform/CloudFormation/console setup (not applied here -- this package
has no bucket-provisioning code, only an S3 client):

- Expire (or transition to Glacier/Infrequent-Access) objects under
  `<crawl_run_id>/*` after some retention window (e.g. 90 days) once a
  run's documents have been consumed downstream -- there's no code path
  in this repo that reads old runs' documents after the fact, only the
  read API's `crawl_run_id` filter for a specific, presumably recent, run.
- **Do not** apply the same lifecycle rule to `latest/*` -- those objects
  are the freshness index's only source of truth and must survive as long
  as the URL they represent is still being (re-)crawled, independent of
  which run last wrote them.
- Consider S3 versioning + MFA delete on `latest/*` if freshness-check
  correctness ever becomes security/compliance-relevant (out of scope for
  this crawler today).

## Load-test plan (`ListObjectsV2` pagination at scale)

**Not run against a real or emulated bucket as part of this branch**: no
AWS CLI or LocalStack binary/image was available in the environment this
was written in, and `docker-compose.yml` doesn't have a LocalStack service
yet (Person 1's item 3). Rather than fabricate numbers, `scripts/
s3_listing_loadtest.go` (build-tag `ignore`, so `go build ./...` skips it)
is a ready-to-run tool for whoever has bucket access next:

```bash
# Against LocalStack, once Person 1's docker-compose service exists:
go run scripts/s3_listing_loadtest.go \
    -bucket scraper-docs -run-id 999999 -count 10000 \
    -endpoint http://localhost:4566

# Against a real dev bucket (uses default AWS credential chain):
go run scripts/s3_listing_loadtest.go \
    -bucket my-dev-bucket -run-id 999999 -count 10000
```

It seeds `-count` tiny Document-shaped objects under one `crawl_run_id`
prefix (concurrent `PutObject`, `-seed-concurrency` in flight), then times
a full `ListObjectsV2` pagination pass (default `MaxKeys` is 1000, so
10,000 objects means 10 pages), and prints a linear extrapolation to
1,000,000 objects (1,000 pages) based on the measured per-page latency.

**Why extrapolate instead of literally running 1M objects**: seeding 1M
real objects costs real time and, against real AWS S3, real money (PUT
request pricing), for a number this script can estimate reasonably well
-- `ListObjectsV2`'s per-page cost is dominated by one HTTP round-trip
returning up to 1000 keys, which doesn't get slower as the *total* object
count grows (S3's key-space is not sorted-scan-from-zero per request; each
page continues from its continuation token). The one thing a 1M-object run
would catch that a 10K-object extrapolation can't is any degradation
specific to very large single-prefix listings (undocumented by AWS, but
worth actually checking before relying on this at production scale) --
flagged, not verified, here.

## Known gaps

- **No LocalStack integration test.** `s3_writer_test.go`,
  `s3_freshness_test.go`, and `s3_run_recorder_test.go` all use hand-written
  fakes of the S3 client interfaces, not a real (or emulated) bucket.
  This proves the key-derivation and JSON-encoding logic is correct, but
  not IAM permissions, bucket region/endpoint config, or real S3
  conditional-write semantics under concurrent load. `docs/GETTING_STARTED.md`
  and `docker-compose.yml` don't yet have a LocalStack service (Person 1's
  item 3) to run such a test against.
- **`ListObjectsV2` at scale (1M+ objects under one `crawl_run_id`) is
  unmeasured**, not just untested -- see "Load-test plan" above for the
  script and why it wasn't run here.
- **`category` filtering has no index** -- resolved via a documented
  behavior change (required `crawl_run_id`) rather than left open; see
  "Category filtering under S3" above.
