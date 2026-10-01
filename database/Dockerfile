# PostgreSQL 16 + PostGIS (map geometry) + pgvector (page embeddings).
# Built by docker-compose.yml; the base image already carries the PGDG apt repo.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
