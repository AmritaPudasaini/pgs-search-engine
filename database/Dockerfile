# syntax=docker/dockerfile:1
#
# PostgreSQL 16 + pgvector (page embeddings) + PostGIS (map geometry).
# Built as the `postgres` service of the root docker-compose.yml.
#
# Base: the official pgvector image, i.e. the official postgres:16 image on Debian 13
# with pgvector compiled in. PostGIS comes from the PGDG apt repository the base image
# already trusts -- the same packages the postgis/postgis images install. (The Debian
# postgis/postgis:16-* tags are still on Debian 11, whose PGDG repository has been
# retired, so pgvector can no longer be apt-installed on top of them.)
#
# No extension is created here: the Alembic migrations own the schema and run
# CREATE EXTENSION IF NOT EXISTS vector / postgis themselves (db-migrate service).
FROM pgvector/pgvector:0.8.6-pg16-trixie

# PGDG publishes PostGIS 3.x per PostgreSQL major and retires superseded builds, so the
# package is pinned to its major (in the name) rather than to an exact build.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        "postgresql-${PG_MAJOR}-postgis-3" \
        "postgresql-${PG_MAJOR}-postgis-3-scripts" \
    && rm -rf /var/lib/apt/lists/*

# Run after the migrations (not at init: the roles do not exist yet) by the compose
# db-role-passwords service and the k8s db-bootstrap Job: sets each service role's login
# password from the environment.
COPY sql/set-role-passwords.sql /opt/pgs/set-role-passwords.sql
