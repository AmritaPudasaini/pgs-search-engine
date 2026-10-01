# CLAUDE.md

Guidance for Claude Code when working in this repository. Read [README.md](README.md) for the
product overview. Each service's own README is the spec for that service.

## Repository map

| Path | What | Language / runtime |
| --- | --- | --- |
| `database/` | `pgs-db`: SQLAlchemy models, Pydantic schemas, repositories, **Alembic migrations**, seed scripts and data. **The source of truth for the PostgreSQL schema.** | Python 3.11 |
| `api/` | FastAPI gateway (`api.main:app`); calls the search engine over gRPC (`api/grpc_client.py`) | Python 3.11 |
| `search-engine/` | gRPC `SearchService` on :50051 (BM25 on OpenSearch, pgvector, NLLB translation, LightGBM rerank) | Python 3.11 |
| `ETL/` | `airflow/` (DAGs, CeleryExecutor), `kafka/consumer.py` (scraper → ETL handoff), `spark/` (`transform.py`, `security_scanner.py`) | Python 3.11, Airflow 2.10.4, PySpark 3.5.3 |
| `scraper/` | Go crawler (`cmd/worker`, a Temporal worker) + library packages under `internal/` | Go |
| `ui/` | Next.js 16 app (App Router, `src/`) | Node 24 |
| `docker/` | Compose-only assets (`postgres/set-role-passwords.sql`) | |

## Running the stack

Everything runs from the root [`docker-compose.yml`](docker-compose.yml). There are no
per-service compose files; don't add any. The dev machine is WSL (Ubuntu) + Docker Desktop, so
run `docker compose` inside WSL.

```bash
cp .env.example .env
docker compose up -d --build                    # default stack
docker compose --profile search up -d           # + search engine (heavy)
docker compose config --quiet                   # validate after editing compose
docker compose run --rm etl-spark-test          # standalone Spark check
docker compose run --rm db-migrate python scripts/create_admin.py <user> --email <addr>
```

- **Profiles:** `search`, `ui`, `scraper`, `tools` (see the README). `ui` and `scraper` don't
  build yet (see "Known breakages").
- **Startup order** comes from health checks plus `depends_on` conditions:
  `postgres` → `db-migrate` → `db-seed` + `db-role-passwords` → app services; `kafka` →
  `kafka-init`; `airflow-db` + `redis` → `airflow-init` → Airflow. Never add `sleep`-based waits.
- **One-shot tasks** (`db-migrate`, `db-seed`, `db-role-passwords`, `kafka-init`,
  `airflow-init`, `search-index-init`) re-run on every `up` and must stay idempotent.
- **Ports:** host ports bind to `127.0.0.1`. Inside the network, use service names
  (`postgres:5432`, `kafka:29092`, `opensearch:9200`, `search-engine:50051`), never `localhost`.
  Kafka's `localhost:9092` listener exists only for host-side scripts.
- **Config:** all variables live in `.env` (template: `.env.example`). Secrets use
  `${VAR:?...}` in compose, so they fail fast when missing; nothing secret goes in a Dockerfile.

## Docker conventions

- **One Dockerfile per application service:** `api/`, `ETL/`, `search-engine/`, `scraper/`, `ui/`.
  `database/` has two: `Dockerfile` is the PostgreSQL server image; `migrate.Dockerfile` is the
  migration/bootstrap image (also used by `db-seed`).
- **Build contexts:** `api`, `ETL` and `search-engine` build from the **repository root**,
  because they need `database/` as well. The root `.dockerignore` is an allow-list; re-include
  any new top-level directory one of them must copy. `ui`, `scraper` and `database` use their own
  directory and `.dockerignore`.
- **The shared package** is installed into images from `./database` with
  `-c database/constraints.txt`, never copied into other service directories. After changing
  `database/pyproject.toml` dependencies, regenerate `constraints.txt` (command in its header).
- **Images run as non-root, with numeric `USER`s.** Python images use 10001, `ui` uses 1000
  (node), ETL uses 50000 (airflow), scraper uses distroless nonroot. Base images are pinned
  (no `latest`). Lint with `hadolint`.

## Things that are easy to get wrong

- **Schema changes go only through Alembic migrations in `database/`.** The Go scraper and the
  search engine never create tables or extensions. A new table also needs the `updated_at`
  trigger, an entry in `pgs_db/grants.py`, and a bump of `pgs_db.health.EXPECTED_REVISION` (see
  `database/README.md` §7). Extensions (`vector`, `postgis`) are created by the migrations, not
  by the Postgres image.
- **Services connect as their own DB role** (`pgs_api`, `pgs_etl`, `pgs_search`, `pgs_scraper`),
  never as the schema owner. Only `db-migrate`/`db-seed` use `POSTGRES_USER`. URL forms:
  Python uses `postgresql+psycopg://`, Go uses `postgres://...?sslmode=disable`.
- **Airflow 2.10 requires SQLAlchemy < 2; `pgs-db` requires SQLAlchemy 2**, so they can never
  share an environment. In the ETL image, `pgs_db` lives in `/opt/etl-venv`. Run DB-writing ETL
  code with `/opt/etl-venv/bin/python` (as `etl-consumer` does), or from a DAG via
  `@task.external_python(python="/opt/etl-venv/bin/python")`. Don't `pip install` pgs-db into
  Airflow's own environment.
- **DAGs hardcode** `kafka:29092`, `/opt/airflow/spark_lib` and `/opt/airflow/data/...`. The
  compose bind mounts keep those paths; don't rename them.
- **The search engine must run from its source layout** (`PYTHONPATH=/app/src`). It locates
  `models/` and `vector_search/` relative to its files, so don't pip-install it as a package.
  Its image uses CPU-only torch.
- **UI env vars:** `NEXT_PUBLIC_*` values are inlined at **build** time (a build arg in compose),
  and the browser hits the API via the host URL. `next.config.ts` uses `output: "standalone"`
  for the image. Before writing UI code, read `ui/AGENTS.md`: Next 16 has breaking changes, and
  its docs are in `ui/node_modules/next/dist/docs/`.

## Known breakages (as of 2026-10-01; not Docker issues)

- `database/src/pgs_db/schemas/geography.py` and `schemas/crawl.py` have broken
  indentation (`geography.py` also has stray Markdown code fences), so `import pgs_db` fails, and with
  it `db-migrate` and every image that imports the package. Fix the indentation in those files.
- `ui/` doesn't build. `src/lib/` (imported as `@/lib/...`) isn't in the repo, because the root
  `.gitignore` rule `lib/` hides it. And `package.json` lacks `leaflet`, `react-leaflet`,
  `recharts`, `lucide-react` and `clsx`, which are listed only in the stray `package copy.json`.
- `scraper/cmd/worker` doesn't compile. It imports `search-engine-scraper/internal/{activities,
  envflag,workflows}` (missing, and under the wrong module path) plus Temporal, Prometheus and
  automaxprocs, which `go.mod` doesn't require. `cmd/searchengine` is an empty `main`. The
  `internal/...` packages build and their tests pass.

## Checks

```bash
docker compose config --quiet                      # compose syntax and interpolation
cd scraper && go vet ./internal/... && go test ./internal/...
cd ETL/kafka && python -m unittest test_consumer
cd database && DATABASE_URL=postgresql+psycopg://pgs:pgs@localhost:5432/pgs python -m pytest
ruff check . && pyright                            # Python lint/type check (root pyproject.toml)
```
