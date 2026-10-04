SHELL := /bin/bash

APP_DB_URL ?= postgres://scraper:scraper@localhost:5433/scraper?sslmode=disable
SCALE      ?= 3
SEEDS      ?=
SEEDS_FILE ?=

# The scraper runs in the repository-root docker-compose.yml (profile `scraper`):
# Temporal (+UI), LocalStack S3 (+browser), headless Chrome, the worker and the API,
# next to the rest of the stack.
COMPOSE := docker compose -f ../docker-compose.yml --profile scraper

.PHONY: run
run: ## Bring up the stack with the scraper (Temporal, Temporal UI, S3, Chrome, worker, API). Ctrl-C to stop.
	$(COMPOSE) up --build

.PHONY: up
up: ## Same as `run` but detached (background).
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop and remove the stack's containers (volumes are kept; the stack is shared).
	$(COMPOSE) down

.PHONY: scale
scale: ## Scale worker replicas: make scale SCALE=5
	$(COMPOSE) up --build -d --scale scraper-worker=$(SCALE)

.PHONY: logs
logs:
	$(COMPOSE) logs -f scraper-worker

.PHONY: crawl
crawl: ## Start a crawl against the running stack: make crawl SEEDS=https://example.com
	@if [ -z "$(SEEDS)" ] && [ -z "$(SEEDS_FILE)" ]; then \
		echo "usage: make crawl SEEDS=https://example.com   (or SEEDS_FILE=configs/seeds.example.txt)"; exit 1; \
	fi
	docker compose -f ../docker-compose.yml run --rm scraper-cli \
		$(if $(SEEDS),--seeds=$(SEEDS)) \
		$(if $(SEEDS_FILE),--seeds-file=/$(SEEDS_FILE)) \
		--same-host-only=false --max-depth=2 --max-pages=200 --max-pages-per-domain=50

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

.PHONY: sqlc
sqlc: ## Regenerate internal/db from internal/db/queries.sql + migrations/*.sql.
	sqlc generate

.PHONY: migrate-up
migrate-up: ## Apply migrations to APP_DB_URL (defaults to the local dev Postgres below).
	migrate -path migrations -database "$(APP_DB_URL)" up

.PHONY: migrate-down
migrate-down: ## Roll back one migration on APP_DB_URL.
	migrate -path migrations -database "$(APP_DB_URL)" down 1

.PHONY: migrate-new
migrate-new: ## Create a new migration pair: make migrate-new NAME=add_something
	@test -n "$(NAME)" || (echo "usage: make migrate-new NAME=add_something" && exit 1)
	migrate create -ext sql -dir migrations -seq $(NAME)

.PHONY: devdb-up
devdb-up: ## Start a standalone local Postgres for `go test`/manual runs against --storage=postgres, outside of docker compose.
	docker run -d --name scraper-devdb -e POSTGRES_USER=scraper -e POSTGRES_PASSWORD=scraper -e POSTGRES_DB=scraper -p 5433:5432 postgres:16-alpine
	@until docker exec scraper-devdb pg_isready -U scraper >/dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate-up

.PHONY: devdb-down
devdb-down:
	docker rm -f scraper-devdb

# Kubernetes manifests for the whole project live in ../k8 (Kustomize); the scraper is
# its `scraper` component -- enable it in ../k8/kustomization.yaml. Its migrations/ are not
# applied there: the Python pgs-db migrations own the database schema.
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
