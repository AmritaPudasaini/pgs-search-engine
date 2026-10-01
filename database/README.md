# Database (`pgs-db`)

We design and manage the PostgreSQL database that the scraper, ETL, search engine and API all share.

**Status:** Bronze layer and reference tables are built and migrated. Silver, Gold and the
operational tables are still to come — see [§5](#5-table-status).

---

## 1. What the database is for

The database is the project's **record book**. It does not hold the actual web pages. It holds **information about them**:

- which websites we crawl and their status
- which files were downloaded and where they are stored
- clean page details (title, language, date)
- which province, district and municipality each page belongs to
- admin users, blocked files and error logs

## 2. What goes where

| Data | Stored in |
|---|---|
| Raw HTML, PDFs, documents | **MinIO** (not the database) |
| Full page text for searching | **OpenSearch** |
| "Already visited" URL list | **Redis** |
| Records, status, relationships, locations | **PostgreSQL (this group)** |

If you are unsure where your data should go, ask us.

`crawled_documents.text` is the one deliberate exception: Bronze keeps the scraper's extracted
text as provenance, so a page can be re-processed without re-fetching it. Search still reads
from OpenSearch, never from this column.

## 3. How data is organised

We use three layers:

| Layer | Meaning | Tables | Status |
|---|---|---|---|
| **Bronze** | Raw: a record of every crawl and every downloaded file, unchanged | `crawl_runs`, `crawled_documents`, `stored_files` | **Built** |
| | | `quarantined_files` | Planned |
| **Silver** | Clean: one record per page, duplicates removed, location tagged | `pages`, `page_geo_tags`, `page_contacts` | Planned |
| **Gold** | Ready to use: summaries for the map and dashboard | `district_stats`, `domain_stats` | Planned |

Plus **reference tables** that everything links to:

- `provinces` (7), `districts` (77), `local_bodies` (753) — tables built; only the 7 provinces are seeded so far
- `domains`: the list of websites to crawl — built
- `admin_users` — planned

## 4. What is built

One migration is in place: `20260922_95e7b8aa6ec5_create_bronze_and_reference_tables`.

| Table | Layer | Written by | Read by | Mirrors |
|---|---|---|---|---|
| `crawl_runs` | Bronze | Scraper | API | scraper `CrawlStats` / `Document.crawl_run_id` |
| `crawled_documents` | Bronze | Scraper | ETL, API | scraper `model.Document` |
| `stored_files` | Bronze | Scraper | ETL, API | scraper `model.StoredDocument` |
| `domains` | Reference | API (admin) | Scraper, ETL | the seed registry / domain→municipality map |
| `provinces` | Reference | Database group | ETL, API, UI | search `GeoLocation.province_code` |
| `districts` | Reference | Database group | ETL, API, UI | search `GeoLocation.district_code` |
| `local_bodies` | Reference | Database group | ETL, API, UI | search `GeoLocation.municipality_id` |

Design decisions worth knowing:

- **Dedupe identity** is `UNIQUE (normalized_url, content_hash)` on `crawled_documents`. Two URLs
  that declare the same canonical collapse to one row; the same URL with changed content becomes
  a new row.
- **Statuses are `VARCHAR` + `CHECK`**, not native Postgres enums, so the Go scraper and Spark can
  insert plain strings with no casts. Values live in `src/pgs_db/enums.py`.
- **All primary keys are `BIGINT`**, matching the scraper's `int64` ids.
- **All timestamps are `timestamptz`**, stored in UTC.

**Note for the Go scraper:** `sim_hash` is `uint64` in Go but Postgres has no unsigned type. Write
`int64(simHash)` and read back with `uint64(v)`; the bits are unchanged, so Hamming distance still
works.

## 5. Table status

| Table | Layer | Status |
|---|---|---|
| `crawl_runs` | Bronze | Built |
| `crawled_documents` | Bronze | Built |
| `stored_files` | Bronze | Built |
| `domains` | Reference | Built |
| `provinces` | Reference | Built, seeded (7) |
| `districts` | Reference | Built, **not seeded** (77 expected) |
| `local_bodies` | Reference | Built, **not seeded** (753 expected) |
| `quarantined_files` | Bronze | Not built — ClamAV quarantine log |
| `pages` | Silver | Not built — ETL output |
| `page_geo_tags` | Silver | Not built — province/district/municipality/ward per page |
| `page_contacts` | Silver | Not built — emails, phones, socials per page |
| `district_stats` | Gold | Not built — page counts for the UI map |
| `domain_stats` | Gold | Not built — pages scraped/failed per domain |
| `error_logs` | Ops | Not built — all services write here |
| `admin_users` | Ops | Not built — API auth |

Also outstanding:

- **Geo seed data** — the gazetteer (77 districts, 753 local bodies, with Devanagari names) that
  the ETL's geo-tagging stage and the search team's `GeoLocation` both depend on.
- **Pydantic schemas** — `src/pgs_db/schemas/` is still empty.
- **PostGIS boundary geometry** — the container image has PostGIS, but the extension is not yet
  enabled and `local_bodies` has no boundary column. `crawled_documents` carries plain
  `geo_lat` / `geo_lng` for now.
- **Write contract for non-Python services** — the exact upsert statements the Go scraper's
  `PostgresWriter` should use.

## 6. Rules everyone should follow

1. **Don't create or change tables yourself.** Ask the Database group. All changes go through migrations (Alembic) so everyone stays in sync.
2. **Never store file contents in PostgreSQL.** Store the MinIO path instead.
3. **All times in UTC.**
4. **Use the fixed status values** we publish in `src/pgs_db/enums.py`, e.g. `PENDING`, `CRAWLING`, `COMPLETED`, `FAILED`.
5. **Python services** can use our package: `pip install -e ./database`, then `import pgs_db`.
6. **Non-Python services** (Go scraper, Spark) write to the same tables using the column list we publish.

## 7. Quick start 

Needs **Docker Desktop** (running) and **Python 3.11+**.

```bash
cd database
cp .env.example .env                  # Windows: copy .env.example .env
docker compose up -d                  # PostgreSQL 16 + PostGIS
pip install -e ".[postgres,dev]"

export DATABASE_URL=postgresql+psycopg://pgs:pgs@localhost:5432/pgs
# Windows PowerShell:
# $env:DATABASE_URL="postgresql+psycopg://pgs:pgs@localhost:5432/pgs"

python -m alembic upgrade head        # create all tables
python scripts/seed_provinces.py      # load the 7 provinces
python -m pytest                      # 8 tests should pass
```

The tests need a live database: they read `DATABASE_URL` and each test runs in a transaction that
is rolled back. Without `DATABASE_URL` set, the suite skips rather than fails, so check that
tests actually ran (`8 passed`), not just that the command exited green.

Look inside the database:

```bash
docker exec -it pgs-postgres psql -U pgs -d pgs -c "\dt"
docker exec -it pgs-postgres psql -U pgs -d pgs -c "SELECT * FROM provinces;"
```

**Common problems**

- **`alembic` / `pytest` not recognized:** use `python -m alembic` and `python -m pytest`.
- **`password authentication failed for user "pgs"`:** another PostgreSQL on your PC is using
  port 5432. Add `POSTGRES_PORT=5433` to `.env`, run `docker compose down` then
  `docker compose up -d`, and use port `5433` in `DATABASE_URL`.
- **`connection refused`:** the container is still starting or stopped. Run `docker compose up -d`
  and wait a few seconds.

**Connection URLs**

| Used by | URL |
|---|---|
| Python (SQLAlchemy, Alembic) | `postgresql+psycopg://pgs:pgs@localhost:5432/pgs` |
| Go scraper (`--storage=postgres`) | `postgres://pgs:pgs@localhost:5432/pgs` |
| Other containers in the same compose | host `postgres` instead of `localhost` |

