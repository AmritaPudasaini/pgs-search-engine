SHELL := /bin/bash

# The shared database of the root compose stack (migrated by its db-migrate service),
# as the scraper's own role; for `make test-db`.
PGS_TEST_DATABASE_URL ?= postgres://pgs_scraper:pgs_scraper_dev@localhost:5432/pgs?sslmode=disable
SEEDS      ?=

# The scraper is only Go code plus its Dockerfile: it runs in the repository-root
# docker-compose.yml (profile `scraper`), which is driven from the repository root, e.g.
#   docker compose --profile scraper up -d --build
#   docker compose --profile scraper up -d --scale scraper-worker=5
#   docker compose logs -f scraper-worker
#   docker compose exec airflow-scheduler airflow dags trigger scraper_crawl_schedule

.PHONY: build
build: ## Build the worker, client, and api binaries locally (not in Docker).
	go build -o bin/worker ./cmd/worker
	go build -o bin/scraper ./cmd/scraper
	go build -o bin/api ./cmd/api

.PHONY: api
api: ## Run the documents API + Swagger UI locally against an S3 bucket (S3_BUCKET, S3_ENDPOINT). Docs at http://localhost:8080/docs.
	go run ./cmd/api

.PHONY: test
test:
	go test ./...

.PHONY: vet
vet:
	go vet ./...
	gofmt -l .

# The scraper has no schema of its own and migrates nothing: database/ (the pgs_db models
# and Alembic) owns it. sqlc reads ../database/sql/scraper_schema.sql, which
# database/scripts/export_scraper_schema.py generates from the models, only to generate
# the Go models. After a database/ change to one of the scraper's tables, re-run that
# script, then this. (The repository root is mounted so sqlc can read ../database.)
.PHONY: sqlc
sqlc: ## Regenerate internal/db from ../database/sql/scraper_schema.sql + internal/db/queries.sql.
	docker run --rm -v "$(abspath $(CURDIR)/..):/repo" -w /repo/scraper -u "$$(id -u):$$(id -g)" sqlc/sqlc:1.31.1 generate

.PHONY: test-db
test-db: ## Run the Postgres writer against the migrated shared database (root stack's postgres).
	PGS_TEST_DATABASE_URL="$(PGS_TEST_DATABASE_URL)" go test -count=1 -run AgainstMigratedSchema -v ./internal/storage/

# Kubernetes manifests for the whole project live in ../k8 (Kustomize); the scraper is
# its `scraper` component -- enable it in ../k8/kustomization.yaml.
.PHONY: k8s-apply
k8s-apply: ## Deploy the project (incl. enabled components) to the current kubectl context.
	kubectl apply -k ../k8

.PHONY: k8s-delete
k8s-delete:
	kubectl delete -k ../k8 --ignore-not-found

.PHONY: k8s-crawl
k8s-crawl: ## Run a one-off crawl Job in the cluster: make k8s-crawl SEEDS=https://example.com
	@test -n "$(SEEDS)" || (echo "usage: make k8s-crawl SEEDS=https://example.com" && exit 1)
	SEEDS="$(SEEDS)" envsubst < ../k8/jobs/on-demand/scraper-crawl.yaml.tmpl | kubectl create -f -

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
