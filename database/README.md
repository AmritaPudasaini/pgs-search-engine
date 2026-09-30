# Database (`pgs-db`)

We design and manage the PostgreSQL database that the scraper, ETL, search engine and API all share.

**Status: complete.** Every layer is built and migrated: Bronze, Silver, Gold, the reference
gazetteer with map boundaries, and the ops tables. Each service has its own database role, a
scheduled jobs runner keeps Gold fresh, and CI checks every migration from an empty database.
What remains is for the other teams to connect to it — see [§8](#8-connecting-the-other-teams).

---

## 1. What the database is for

The database is the project's **record book**. It does not hold the actual web pages. It holds **information about them**:

- which websites we crawl and their status
- which files were downloaded and where they are stored
- clean page details (title, language, date) and where in Nepal each page belongs
- what the map, the admin dashboard and search ranking read
- admin users, quarantined files, error logs and the search log

## 2. What goes where

| Data | Stored in |
|---|---|
| Raw HTML, PDFs, documents | **MinIO** (not the database) |
| Full page text for searching | **OpenSearch** (indexed from `search_documents`) |
| "Already visited" URL list | **Redis** |
| Records, status, relationships, locations, map shapes | **PostgreSQL (this group)** |

`crawled_documents.text` and `pages.body_text` are deliberate exceptions: they are the provenance
the index is built from, so a page can be re-indexed without re-fetching it. Search queries
OpenSearch, not these columns.

## 3. How data is organised

The ER diagram is in [`docs/erd.md`](docs/erd.md).

| Layer | Meaning | Tables |
|---|---|---|
| **Bronze** | Raw: every crawl and every downloaded file, unchanged | `crawl_runs`, `crawled_documents`, `stored_files` |
| **Silver** | Clean: one record per page, deduplicated, geo-tagged | `pages`, `page_geo_tags`, `page_contacts`, `page_sources`, `page_media`, `entities`, `page_entities`, `page_embeddings`, `quarantined_files` |
| **Gold** | Ready to use: summaries, ranking signals, the search log | `domain_stats`, `geo_content_stats`, `page_scores`, `search_queries`, `search_clicks`, `relevance_judgments`; views `search_documents`, `page_geo_codes` |
| **Reference** | What everything links to | `provinces` (7), `districts` (77), `local_bodies` (753) with boundaries and ward counts, `domains`, `region_links` |
| **Ops** | Running the system | `admin_users`, `error_logs` |

`search_documents` and `page_geo_codes` are **Gold views over Silver**: always current, nothing
to refresh. The Gold *tables* are rebuilt by the jobs in [§6](#6-scheduled-jobs).

### What each service uses

| Service | Role | Repository | Reads | Writes |
|---|---|---|---|---|
| Scraper (Go) | `pgs_scraper` | `BronzeRepository` / [`scraper-db-contract.md`](docs/scraper-db-contract.md) | gazetteer, domains | Bronze, `domains` |
| ETL (Spark) | `pgs_etl` | `SilverRepository`, `pgs_db.etl` / [`bronze-silver-contract.md`](docs/bronze-silver-contract.md) | Bronze, gazetteer (`ReferenceRepository.gazetteer`, `locate`) | Silver |
| Search / indexer | `pgs_search` | `SearchRepository` | `search_documents`, `page_embeddings` | `pages` indexing state |
| API | `pgs_api` | `OpsRepository`, `StatsRepository`, `QuarantineRepository`, `ReferenceRepository`, `SearchLogRepository` | everything | admin tables, domains, quick links, search log, labels |
| Scheduled jobs | `pgs_jobs` | `python -m pgs_db.jobs` | everything but `admin_users` | Gold summaries, retention |
| Dashboards | `pgs_readonly` | — | everything but `admin_users` | nothing |

### API endpoints → repository methods

| Endpoint | Method |
|---|---|
| `POST /auth/login` | `OpsRepository.get_admin` (username or email) + `pgs_db.security.verify_password`, then `record_login` |
| `GET /user/search` | OpenSearch, then `SearchLogRepository.log_query`; `regional_card` from `ReferenceRepository.regional_card` |
| `GET /user/documents/download/{id}` | `SearchRepository.file_location` (None for quarantined files: answer 404) |
| `GET /user/geo/hierarchy` | `ReferenceRepository.hierarchy` |
| map shapes / colours | `ReferenceRepository.boundaries_geojson`, `StatsRepository.geo_content` |
| `GET /admin/dashboard/summary` | `StatsRepository.dashboard_summary`, `SearchLogRepository.traffic` |
| `GET /admin/domains`, `POST .../action` | `StatsRepository.list_domains`, `set_domain_status` |
| `GET /admin/storage/metrics` | `StatsRepository.storage_metrics` |
| `GET /admin/logs/errors` | `OpsRepository.list_errors` |
| `GET /admin/security/quarantine` | `QuarantineRepository.list_quarantined`, `mark_deleted` |
| health / readiness probe | `pgs_db.health.check` |

## 4. Design decisions worth knowing

- **Dedupe identity** is `UNIQUE (normalized_url, content_hash)` on `crawled_documents`: the same
  URL with changed content becomes a new row. Silver keys a page on its `canonical_url`.
- **Geo links use codes, not ids** (`P4`, `D38`, `MUN414`), the codes ETL and search already exchange.
- **Statuses are `VARCHAR` + `CHECK`**, not native enums, so Go and Spark insert plain strings.
  Values live in `src/pgs_db/enums.py`.
- **All primary keys are `BIGINT`**; **all timestamps are `timestamptz`** in UTC.
- **`updated_at` is kept by a trigger** on every table, so plain-SQL writers (Go, Spark) keep it
  honest too. An explicit new value is left alone.
- **Work queues** (`claim_bronze`, `claim_stored_files`, `claim_for_indexing`) use
  `FOR UPDATE SKIP LOCKED` in a `MATERIALIZED` CTE: parallel workers never take the same row, and
  a claim never exceeds its `limit`.
- **Every foreign key is indexed** (a test enforces it), so deletes never scan a child table.
- **No personal data in the search log**: an opaque session id only, no IP, user agent or account.
- **Embeddings are per model**: `embedding_models` registers each model and its size (LaBSE,
  768, is the default); a composite foreign key keeps every vector the right size for its model,
  and each model has its own HNSW index. Documents and queries must use the same model.

**Note for the Go scraper:** `sim_hash` is `uint64` in Go but Postgres has no unsigned type. Write
`int64(simHash)` and read back with `uint64(v)`; the bits are unchanged.

## 5. Reference data

### The gazetteer

`data/nepal_geography.json` holds all 837 regions and is committed, so seeding needs no network.
Source: [sagautam5/local-states-nepal](https://github.com/sagautam5/local-states-nepal) — 6
metropolitan, 11 sub-metropolitan, 276 municipalities, 460 rural municipalities = 753.

**Codes are assigned by this project**, not taken from an official registry:

| Level | Format | Example |
|---|---|---|
| Province | `P1`–`P7` | `P4` = Gandaki |
| District | `D01`–`D77` | `D38` = Kaski |
| Local body | `MUN001`–`MUN753` | `MUN414` = Pokhara Metropolitan City |

**This is the contract for `GeoLocation.district_code` and `municipality_id`.** (The API spec's
example `MUN75340` and the ETL README's `D39` for Kaski are illustrative; code against these.)

`local_bodies.phone` / `email` / `address` start empty; the `reference` job fills them from each
municipality's own website once it has been crawled. `region_links` (quick links on a region's
search card) is filled by admins.

### Map boundaries

`data/boundaries/*.geojson.gz` are Open Knowledge Nepal's current boundaries (CC BY 4.0,
[`ATTRIBUTION.md`](data/boundaries/ATTRIBUTION.md)), re-keyed to our codes by
`scripts/build_boundaries.py`, which refuses to write unless every province, district and local
body gets its shape. A test re-checks the mapping by geometry: every local body lies inside its
own district. **Any map showing them must credit "Boundaries © Open Knowledge Nepal, CC BY 4.0".**

The UI should load shapes from `ReferenceRepository.boundaries_geojson` instead of its own GeoJSON,
which predates the 2017 restructuring (75 districts; only 544 of 766 names match the gazetteer).

## 6. Scheduled jobs

`python -m pgs_db.jobs <job>` as the `pgs_jobs` role. Each job runs in its own transaction under
an advisory lock (an overlapping run skips), prints one JSON line, and exits non-zero on failure.

| Job | Does | Schedule |
|---|---|---|
| `stats` | rebuild `domain_stats`, `geo_content_stats` | every 15 min |
| `scores` | rebuild `page_scores` (PageRank, freshness, quality) and domain authority | hourly |
| `reference` | link domains to local bodies, fill missing municipality contacts | daily |
| `release-stale` | return ETL / indexing claims stuck > `--stale-minutes` (30) | every 10 min |
| `purge` | error logs older than `--error-days` (90), searches older than `--search-days` (365) | daily |

`pgs_db.health.check` reports Gold older than 6 hours as `degraded`, so a stopped scheduler shows up.

## 7. Running it

### Local development

Needs **Docker Desktop** (running) and **Python 3.11+**.

```bash
cd database
cp .env.example .env                  # Windows: copy .env.example .env
docker compose up -d --build          # PostgreSQL 16 + PostGIS + pgvector (./Dockerfile)
pip install -e ".[postgres,dev]"

export DATABASE_URL=postgresql+psycopg://pgs:pgs@localhost:5432/pgs
# Windows PowerShell: $env:DATABASE_URL="postgresql+psycopg://pgs:pgs@localhost:5432/pgs"

python -m alembic upgrade head        # all tables, views, triggers and roles
python scripts/seed_geography.py      # 7 provinces, 77 districts, 753 local bodies
python scripts/seed_boundaries.py     # their shapes
python -m pytest                      # 315 tests should pass
```

The tests need a live, seeded database: they read `DATABASE_URL`, and each test runs in a
transaction that is rolled back. Without `DATABASE_URL` the suite skips rather than fails, so check
that tests actually ran. CI (`.github/workflows/database.yml`) runs all of this from an empty
database on every change under `database/`, plus a full downgrade and re-upgrade.

### Production deployment

1. **Migrate** as the schema owner: `python -m alembic upgrade head`. It enables `vector` and
   `postgis` and creates the six service roles (LOGIN, no password, with a `statement_timeout` each).
2. **Seed** (idempotent): `python scripts/seed_geography.py && python scripts/seed_boundaries.py`.
3. **Set a password per role**, per environment, from your secret store:
   `ALTER ROLE pgs_api PASSWORD '...'` (and `pgs_scraper`, `pgs_etl`, `pgs_search`, `pgs_jobs`,
   `pgs_readonly`). Each service connects as its own role.
4. **Create the first admin**: `pip install -e ".[postgres,auth]"`, then
   `python scripts/create_admin.py <username> --email <address>` (asks for the password; Argon2id).
5. **Schedule the jobs** in [§6](#6-scheduled-jobs), and point the API's readiness probe at
   `pgs_db.health.check`.
6. **Back up** with the platform's point-in-time recovery (WAL archiving), or at least a nightly
   `pg_dump -Fc`. Bronze is re-crawlable and Gold is rebuildable, so the tables that cannot be
   recreated are `admin_users`, `domains`, `region_links`, `relevance_judgments`, the search log
   and `quarantined_files` — make sure restores are tested for those.

Per-service connection settings: `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10), `DB_POOL_RECYCLE`
(1800 s), `DB_APPLICATION_NAME` (shows in `pg_stat_activity`). Keep workers × (pool + overflow)
under the server's `max_connections`, or put PgBouncer in front.

### Changing the schema

Every change is an Alembic migration (`python -m alembic revision --autogenerate -m "..."`, then
review it). A migration that adds a table must also: add the `updated_at` trigger, add the table to
`pgs_db/grants.py` and call `grants.apply(op.execute)`, and bump `pgs_db.health.EXPECTED_REVISION`.
`tests/test_hardening.py` fails until all three are done.

**Common problems**

- **`alembic` / `pytest` not recognized:** use `python -m alembic` and `python -m pytest`.
- **`password authentication failed for user "pgs"`:** another PostgreSQL owns port 5432. Set
  `POSTGRES_PORT=5433` in `.env`, `docker compose down && docker compose up -d`, and use 5433 in
  `DATABASE_URL`.
- **`extension "vector" is not available`:** the container is on the old PostGIS-only image. Run
  `docker compose up -d --build`.
- **`column ... does not exist` although `alembic current` says head:** your database was built
  from an earlier draft of a migration. Recreate it (this deletes its data):
  `docker exec pgs-postgres psql -U pgs -d postgres -c "DROP DATABASE pgs WITH (FORCE)" -c "CREATE DATABASE pgs"`,
  then migrate and seed again.
- **Boundary tests skipped:** run `python scripts/seed_boundaries.py`.

**Connection URLs**

| Used by | URL |
|---|---|
| Python (SQLAlchemy, Alembic) | `postgresql+psycopg://<role>:<password>@<host>:5432/pgs` |
| Go scraper (`--storage=postgres`) | `postgres://pgs_scraper:<password>@<host>:5432/pgs` |
| Other containers in the same compose | host `postgres` instead of `localhost` |

