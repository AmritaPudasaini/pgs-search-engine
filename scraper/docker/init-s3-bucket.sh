#!/bin/sh
# Runs inside LocalStack once S3 is ready: creates the bucket crawled pages go to.
awslocal s3 mb s3://crawled-pages
