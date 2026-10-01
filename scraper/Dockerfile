# syntax=docker/dockerfile:1
#
# Go crawler: cmd/worker, the Temporal worker that fetches pages and writes the crawled
# documents to NDJSON / PostgreSQL / Kafka (--storage). Every flag can be set through
# the environment variable of the same name (e.g. --kafka-brokers == KAFKA_BROKERS),
# which is how docker-compose.yml configures it.
# Build context: scraper/
#
# The worker never touches the schema: the Python pgs-db migrations own it.

ARG GO_VERSION=1.27

FROM golang:${GO_VERSION}-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .
# Pure-Go dependencies, so a static binary (CGO_ENABLED=0) runs on distroless/static.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/worker ./cmd/worker \
    && mkdir -p /out/data/output

# distroless/static: no shell or package manager; ships CA certificates (HTTPS crawling)
# and tzdata, and runs as the nonroot user (65532).
FROM gcr.io/distroless/static-debian13:nonroot
WORKDIR /app
COPY --from=build /out/worker /app/worker
# The default --output is data/output/documents.ndjson, relative to the working dir.
COPY --from=build --chown=65532:65532 /out/data /app/data
# Prometheus metrics (--metrics-address)
EXPOSE 9090
ENTRYPOINT ["/app/worker"]
