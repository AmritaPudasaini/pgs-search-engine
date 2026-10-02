// Command api serves the crawled documents over HTTP for browsing: JSON
// endpoints under /api/v1 plus a Swagger UI at /docs for previewing the
// data and trying the endpoints interactively. It reads only from the S3
// bucket the worker uploads to -- no database -- and is read-only: crawls
// are started via cmd/scraper, not this service.
package main

import (
	"context"
	"flag"
	"log"
	"net/http"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"go.uber.org/automaxprocs/maxprocs"

	"search-engine-scraper/internal/api"
	"search-engine-scraper/internal/envflag"
)

func main() {
	_, _ = maxprocs.Set()

	var (
		addr       = envflag.String("addr", ":8080", "address to listen on")
		s3Bucket   = envflag.String("s3-bucket", "", "S3 bucket the worker writes crawled pages to (required)")
		s3Prefix   = envflag.String("s3-prefix", "", "key prefix inside the bucket; must match the worker's --s3-prefix")
		s3Endpoint = envflag.String("s3-endpoint", "", "S3-compatible endpoint URL for LocalStack/MinIO (empty = real AWS S3)")
		awsRegion  = envflag.String("aws-region", "", "AWS region (empty = resolve from AWS_REGION / shared config)")
	)
	flag.Parse()

	if *s3Bucket == "" {
		log.Fatal("--s3-bucket (or S3_BUCKET) is required")
	}

	var loadOpts []func(*config.LoadOptions) error
	if *awsRegion != "" {
		loadOpts = append(loadOpts, config.WithRegion(*awsRegion))
	}
	cfg, err := config.LoadDefaultConfig(context.Background(), loadOpts...)
	if err != nil {
		log.Fatalf("load aws config: %v", err)
	}
	client := s3.NewFromConfig(cfg, func(o *s3.Options) {
		if *s3Endpoint != "" {
			o.BaseEndpoint = aws.String(*s3Endpoint)
			o.UsePathStyle = true
		}
	})

	server := api.NewS3Server(client, *s3Bucket, api.WithS3ServerKeyPrefix(*s3Prefix))

	log.Printf("api listening on %s (docs at %s/docs), reading s3://%s", *addr, *addr, *s3Bucket)
	if err := http.ListenAndServe(*addr, server.Routes()); err != nil {
		log.Fatalf("api server stopped: %v", err)
	}
}
