SHELL := /bin/bash

APP_DB_URL ?= postgres://scraper:scraper@localhost:5433/scraper?sslmode=disable
SCALE      ?= 3
SEEDS      ?=
SEEDS_FILE ?=

.PHONY: run
run: ## One command to bring up the whole stack: Postgres, Temporal, Temporal UI, and a worker. Ctrl-C to stop.
	docker compose up --build

.PHONY: up
up: ## Same as `run` but detached (background).
	docker compose up --build -d

.PHONY: down
down: ## Stop and remove all containers + volumes (wipes Postgres data).
	docker compose down -v

.PHONY: scale
scale: ## Scale worker replicas: make scale SCALE=5
	docker compose up --build -d --scale worker=$(SCALE)

.PHONY: logs
logs:
	docker compose logs -f worker

.PHONY: crawl
crawl: ## Start a crawl against the running compose stack: make crawl SEEDS=https://example.com
	@if [ -z "$(SEEDS)" ] && [ -z "$(SEEDS_FILE)" ]; then \
		echo "usage: make crawl SEEDS=https://example.com   (or SEEDS_FILE=configs/seeds.example.txt)"; exit 1; \
	fi
	docker compose run --rm scraper \
		$(if $(SEEDS),--seeds=$(SEEDS)) \
		$(if $(SEEDS_FILE),--seeds-file=/$(SEEDS_FILE)) \
		--same-host-only=false --max-depth=2 --max-pages=200 --max-pages-per-domain=50

.PHONY: build
build: ## Build the worker, client, and api binaries locally (not in Docker).
	go build -o bin/worker ./cmd/worker
	go build -o bin/scraper ./cmd/scraper
	go build -o bin/api ./cmd/api

.PHONY: api
api: ## Run the documents API + Swagger UI locally against APP_DB_URL. Docs at http://localhost:8080/docs.
	DATABASE_URL="$(APP_DB_URL)" go run ./cmd/api

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

.PHONY: k8s-migrations-configmap
k8s-migrations-configmap: ## Regenerate k8s/04-migrations-configmap.yaml from migrations/*.sql (run after editing migrations).
	kubectl create configmap migrations --from-file=migrations -n search-engine-scraper \
		--dry-run=client -o yaml > k8s/04-migrations-configmap.yaml

.PHONY: k8s-apply
k8s-apply: k8s-migrations-configmap ## Deploy to the current kubectl context.
	kubectl apply -f k8s/

.PHONY: k8s-delete
k8s-delete:
	kubectl delete -f k8s/ --ignore-not-found

.PHONY: k8s-crawl
k8s-crawl: ## Run a one-off crawl Job in the cluster: make k8s-crawl SEEDS=https://example.com
	@test -n "$(SEEDS)" || (echo "usage: make k8s-crawl SEEDS=https://example.com" && exit 1)
	JOB_NAME=crawl-$$(date +%s) SEEDS="$(SEEDS)" envsubst < k8s/scraper-job.yaml.tmpl | kubectl apply -f -

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
