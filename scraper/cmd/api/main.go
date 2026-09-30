// Command api serves the crawled documents over HTTP for browsing: JSON
// endpoints under /api/v1 plus a Swagger UI at /docs for previewing the
// data and trying the endpoints interactively. It is read-only -- crawls
// are started via cmd/scraper, not this service.
package main

import (
	"context"
	"flag"
	"log"
	"net/http"

	"go.uber.org/automaxprocs/maxprocs"

	"search-engine-scraper/internal/api"
	"search-engine-scraper/internal/db"
	"search-engine-scraper/internal/envflag"

	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	_, _ = maxprocs.Set()

	var (
		addr        = envflag.String("addr", ":8080", "address to listen on")
		databaseURL = envflag.String("database-url", "", "Postgres connection string, e.g. postgres://user:pass@host:5432/scraper")
	)
	flag.Parse()

	if *databaseURL == "" {
		log.Fatal("--database-url (or DATABASE_URL) is required")
	}

	ctx := context.Background()
	pool, err := pgxpool.New(ctx, *databaseURL)
	if err != nil {
		log.Fatalf("connect to postgres: %v", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		log.Fatalf("ping postgres: %v", err)
	}

	server := api.NewServer(db.New(pool))

	log.Printf("api listening on %s (docs at %s/docs)", *addr, *addr)
	if err := http.ListenAndServe(*addr, server.Routes()); err != nil {
		log.Fatalf("api server stopped: %v", err)
	}
}
