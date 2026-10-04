# CLAUDE.md

Guidance for Claude Code when working in this repository. Read [README.md](README.md) for the
product overview. Each service's own README is the spec for that service.

## Repository map

| Path | What | Language / runtime |
| --- | --- | --- |
| `database/` | `pgs-db`: SQLAlchemy models, Pydantic schemas, repositories, **Alembic migrations**, seed scripts and data. **The source of truth for the PostgreSQL schema.** | Python 3.11 |
| `api/` | FastAPI gateway (`api.main:app`); calls the search engine over gRPC (`api/grpc_client.py`) | Python 3.11 |
| `search-engine/` | gRPC `SearchService` on :50051 (BM25 on OpenSearch, pgvector, NLLB translation, LightGBM rerank) | Python 3.11 |
| `ETL/` | `airflow/` (DAGs; main one `etl_ingestion_pipeline`), `spark/` (`transform.py`, `security_scanner.py` → ClamAV), `kafka/` (`consumer.py`, `tools/`), `OpenSearch/` (JSONL → index) | Python 3.11, Airflow 2.10.4, PySpark 3.5.3 |
| `scraper/` | Go crawler: `cmd/worker` (Temporal worker → S3 / Kafka), `cmd/api` (read-only API over S3), `cmd/scraper` (starts crawls) | Go 1.26 |
| `ui/` | Next.js 16 app (App Router, `src/`) | Node 24 |
| `k8/` | Kubernetes manifests (Kustomize), grouped by resource kind; single-node, non-HA; Airflow on the KubernetesExecutor. See `k8/README.md`. | |

## Running the stack

Everything runs from the root [`docker-compose.yml`](docker-compose.yml). There are no
per-service compose files and no second Dockerfile per service; don't add any (merge into the
existing one, using build targets if a service ships several binaries). The dev machine is WSL
(Ubuntu) + Docker Desktop, so run `docker compose` inside WSL.

```bash
cp .env.example .env
docker compose up -d --build                         # default stack
docker compose --profile scraper up -d --build       # + crawler (Temporal, S3, Chrome, worker, API)
docker compose --profile search up -d                # + search engine (heavy)
docker compose run --rm scraper-cli --seeds=https://example.gov.np   # start a crawl
docker compose run --rm ingestion-signal-publisher   # file-ready signal for the ETL DAG
docker compose run --rm opensearch-indexer           # index the ETL JSONL output
docker compose run --rm etl-spark-test               # standalone Spark check
docker compose run --rm db-migrate python scripts/create_admin.py <user> --email <addr>
docker compose config --quiet                        # validate after editing compose
```

- **Profiles:** `search`, `scraper`, `scraper-sharded` (three host-sharded workers),
  `scraper-cli`, `ui`, `tools`. A service targeted by `docker compose run` gets its profile
  automatically. `ui` doesn't build yet (see "Known breakages").
- **Startup order** comes from health checks plus `depends_on` conditions:
  `postgres` → `db-migrate` → `db-seed` + `db-role-passwords` → app services; `kafka` →
  `kafka-init`; `airflow-db` + `redis` → `airflow-init` → Airflow; `temporal-db` → `temporal`
  (healthy once its `default` namespace exists) → scraper. Never add `sleep`-based waits.
- **One-shot tasks** (`db-migrate`, `db-seed`, `db-role-passwords`, `kafka-init`,
  `airflow-init`, `search-index-init`) re-run on every `up` and must stay idempotent.
- **Ports:** host ports bind to `127.0.0.1` and are all set in `.env` (Airflow owns 8080, so the
  scraper API is on 8082). Inside the network, use service names (`postgres:5432`,
  `kafka:29092`, `opensearch:9200`, `clamav:3310`, `temporal:7233`, `s3:4566`), never
  `localhost`. Kafka's `localhost:9092` listener exists only for host-side scripts.
- **Config:** all variables live in `.env` (template: `.env.example`). Secrets use
  `${VAR:?...}` in compose, so they fail fast when missing; nothing secret goes in a Dockerfile.

## Docker conventions

- **One Dockerfile per application service:** `api/`, `ETL/`, `search-engine/`, `scraper/`, `ui/`.
  `scraper/Dockerfile` has one target per binary (`worker`, `api`, `cli`; compose sets
  `build.target`). `ETL/Dockerfile` is one image for Airflow, the consumer, the indexer and the
  Spark check. `database/` has two: `Dockerfile` is the PostgreSQL server image;
  `migrate.Dockerfile` is the migration/bootstrap image (also used by `db-seed`). The
  role-password SQL (`database/sql/set-role-passwords.sql`) is baked into the PostgreSQL image
  and run with `psql` by compose's `db-role-passwords` and the k8s `db-bootstrap` Job.
- **Build contexts:** `api`, `ETL` and `search-engine` build from the **repository root**,
  because they need `database/` as well. The root `.dockerignore` is an allow-list; re-include
  any new top-level directory one of them must copy. `ui`, `scraper` and `database` use their own
  directory and `.dockerignore`.
- **The shared package** is installed into images from `./database` with
  `-c database/constraints.txt`, never copied into other service directories. After changing
  `database/pyproject.toml` dependencies, regenerate `constraints.txt` (command in its header).
- **Images run as non-root, with numeric `USER`s.** Python images use 10001, `ui` uses 1000
  (node), ETL uses 50000 (airflow), scraper uses distroless nonroot. Base images are pinned
  (no `latest`); PyTorch is always the CPU build. Lint with `hadolint`.

## Kubernetes (`k8/`)

```bash
cp k8/secrets/secrets.env.example k8/secrets/secrets.env && kubectl apply -k k8/
kubectl kustomize k8/ | kubeconform -strict -kubernetes-version 1.30.0 -summary   # validate
```

- **Grouped by resource kind, one resource per file:** `namespaces/`, `configmaps/`,
  `secrets/`, `persistentvolumeclaims/`, `serviceaccounts/`, `roles/`, `rolebindings/`,
  `services/`, `statefulsets/`, `deployments/`, `jobs/`, `cronjobs/`. A new resource goes in its
  kind's folder as `<name>.yaml` and is listed in `k8/kustomization.yaml`.
- Same services as compose. The compose profiles are commented-out blocks at the end of
  `resources:` in `k8/kustomization.yaml` (uncomment to enable; Kustomize components can't
  reference files outside their own folder). One-shot tools are Jobs in `k8/jobs/on-demand/`
  (`generateName`, run with `kubectl create -f`); `k8/jobs/` itself holds the bootstrap Jobs.
- **Airflow runs on the KubernetesExecutor**: no Celery worker or Redis; the scheduler launches
  one pod per task from the pod template in `k8/configmaps/airflow-pod-template.yaml` (container `base`, ETL
  image). That template is a string in a ConfigMap, so Kustomize doesn't rewrite its image or
  Secret name: the Secret keeps the fixed name `pgs-secrets` (`disableNameSuffixHash`).
  DAGs are baked into the ETL image (no bind mounts in k8s).
- No `depends_on`: ordering comes from init containers (wait until the service can log in as its
  DB role and sees the seeded data; `airflow db check-migrations`; Temporal namespace / S3 bucket /
  Kafka topic checks). Bootstrap Jobs use `ttlSecondsAfterFinished`, so every
  `kubectl apply -k` re-runs them; they must stay idempotent.
- Image tags are set once, in `images:` of `k8/kustomization.yaml`. Kubernetes 1.30's bundled
  Kustomize is v5.0: avoid YAML anchors in these manifests.
- Shared ReadWriteOnce volumes (Airflow logs, ETL output, model cache) assume a single node.

## Things that are easy to get wrong

- **Schema changes go only through Alembic migrations in `database/`.** The Go scraper and the
  search engine never create tables or extensions; `scraper/migrations/` (and its Makefile
  `migrate-*` targets) are not used by the stack. A new table also needs the `updated_at`
  trigger, an entry in `pgs_db/grants.py`, and a bump of `pgs_db.health.EXPECTED_REVISION` (see
  `database/README.md` §7). Extensions (`vector`, `postgis`) are created by the migrations, not
  by the Postgres image. Temporal keeps its own database in `temporal-db`.
- **Services connect as their own DB role** (`pgs_api`, `pgs_etl`, `pgs_search`), never as the
  schema owner. Only `db-migrate`/`db-seed` use `POSTGRES_USER`. URL forms: Python uses
  `postgresql+psycopg://`, Go uses `postgres://...?sslmode=disable`.
- **Airflow 2.10 requires SQLAlchemy < 2; `pgs-db` requires SQLAlchemy 2**, so they can never
  share an environment. In the ETL image, `pgs_db` (plus the Kafka and OpenSearch clients) lives
  in `/opt/etl-venv`. Run DB-writing ETL code with `/opt/etl-venv/bin/python` (as `etl-consumer`
  and `opensearch-indexer` do), or from a DAG via
  `@task.external_python(python="/opt/etl-venv/bin/python")`. Don't `pip install` pgs-db into
  Airflow's own environment. Packages DAG tasks import go into Airflow's environment in
  `ETL/Dockerfile`, with `apache-airflow==${AIRFLOW_VERSION}` in the same `pip install`.
- **DAGs hardcode** `kafka:29092`, `/opt/airflow/spark_lib` and `/opt/airflow/data/...`. The
  compose bind mounts keep those paths; don't rename them. The intake scanner reaches ClamAV via
  `CLAMD_HOST`/`CLAMD_PORT` and fails closed, so `clamav` must be running for the DAG.
- **OpenSearch is pinned to 2.19:** the ETL index (`ETL/OpenSearch/opensearch/create_index.py`)
  uses the `nmslib` k-NN engine, which OpenSearch 3.x refuses for new indexes. Moving to 3.x
  means switching that mapping to `faiss` or `lucene` first.
- **The search engine must run from its source layout** (`PYTHONPATH=/app/src`). It locates
  `models/` and `vector_search/` relative to its files, so don't pip-install it as a package.
- **UI env vars:** `NEXT_PUBLIC_*` values are inlined at **build** time (a build arg in compose),
  and the browser hits the API via the host URL. `next.config.ts` uses `output: "standalone"`
  for the image. Before writing UI code, read `ui/AGENTS.md`: Next 16 has breaking changes, and
  its docs are in `ui/node_modules/next/dist/docs/`.

## Known breakages (as of 2026-10-03; not Docker issues)

- `database/src/pgs_db/schemas/geography.py` and `schemas/crawl.py` have broken indentation
  (`geography.py` also has stray Markdown code fences), so `import pgs_db` fails, and with it
  `db-migrate` and every image that imports the package. Fix the indentation in those files.
- `ui/` doesn't build. `src/lib/` (imported as `@/lib/...`) isn't in the repo, because the root
  `.gitignore` rule `lib/` hides it. And `package.json` lacks `leaflet`, `react-leaflet`,
  `recharts`, `lucide-react` and `clsx`, which are listed only in the stray `package copy.json`.
- Root `requirements.txt` lists `clamav==1.0.2`; the scanner imports `clamd` (`clamd==1.0.2`).

## Checks

```bash
docker compose config --quiet                      # compose syntax and interpolation
cd scraper && go vet ./... && go test ./...
cd ETL/kafka && python -m unittest test_consumer
cd database && DATABASE_URL=postgresql+psycopg://pgs:pgs@localhost:5432/pgs python -m pytest
ruff check . && pyright                            # Python lint/type check (root pyproject.toml)
```
