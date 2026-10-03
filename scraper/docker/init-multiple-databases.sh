#!/bin/sh
# Runs once when the postgres container's data volume is first created
# (standard postgres image behavior for /docker-entrypoint-initdb.d).
# Temporal's own persistence layer and this app's `documents` table live in
# separate databases on the same postgres instance, so a college-project
# deployment doesn't need to run two database containers.
#
# The `temporal` database itself is NOT created here: the official postgres
# image auto-creates a default database named after $POSTGRES_DB (set to
# "temporal" in docker-compose.yml) before this script runs, so creating it
# again here would fail with "database already exists".
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE scraper;
EOSQL
