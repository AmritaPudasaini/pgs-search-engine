# OpenSearch indexing

The ETL OpenSearch integration indexes the transformed JSONL produced by the
Airflow pipeline. It uses `document_id` as the OpenSearch `_id`, so rerunning
the indexer safely replaces the same documents instead of creating copies.

## Start OpenSearch

From `ETL/`:

```powershell
docker compose up -d opensearch
```

OpenSearch is available at `http://localhost:9200`. This local development
service has its security plugin disabled; do not expose it to an untrusted
network.

## Index the transformed output

Run the Airflow workflow first so it creates
`airflow/data/processed/transformed_documents.jsonl`, then run:

```powershell
docker compose run --rm opensearch-indexer
```

The indexer creates `pgs_documents` with the field mapping defined in
`opensearch/create_index.py`, then bulk indexes every non-empty JSONL line.
The default input inside the container is
`/data/transformed_documents.jsonl`, mounted read-only from the Airflow
processed-data directory. It stops with a line number if a record is invalid
or lacks `document_id`.

To use a different endpoint or index, set `OPENSEARCH_URL` or
`OPENSEARCH_INDEX` in the environment before invoking Compose. The standalone
indexer also accepts `--input`, `--index`, `--batch-size`, and
`--max-chunk-bytes` arguments. Bulk requests are capped at 10 MiB by default;
adjust the byte cap alongside the document-count batch size for the available
memory and document sizes.

## Inspect the index

```powershell
Invoke-RestMethod http://localhost:9200/pgs_documents/_mapping
Invoke-RestMethod 'http://localhost:9200/pgs_documents/_search?pretty=true'
```

The mapping covers the fields emitted by `spark/transform.py`, with
`searchable_text` and `title` analyzed for full-text search, exact-match
metadata as keywords, numeric counts, duplicate state, and geo-tag fields.
