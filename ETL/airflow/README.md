# Airflow In ETL

Airflow orchestrates the ETL development workflow while the final scraper, MinIO,
PostgreSQL, OpenSearch, and malware-scanning pieces are still outside this
folder.

Use the root ETL compose file:

```bash
cd ETL
docker compose up --build
```

Airflow UI: http://localhost:8080

Login:

```text
airflow / airflow
```

## Main DAG

`etl_ingestion_pipeline`

Tasks:

```text
poll_kafka_signal -> transform_document -> persist_transformed_document
```

The DAG consumes one manual signal from Kafka topic `scraped_files_topic`, reads
the matching file from `/opt/airflow/data/local_dfs_store`, runs the shared
transform logic mounted from `ETL/spark`, and appends the transformed output to
`/opt/airflow/data/processed/transformed_documents.jsonl`.

## Sample Run

Start the stack, then from another terminal:

```bash
cd ETL
docker compose run --rm ingestion-signal-publisher
```

Trigger `etl_ingestion_pipeline` in the Airflow UI and inspect the
`persist_transformed_document` task log for the transformed record.

## Notes

The healthcheck and extraction-check DAGs are support workflows; the ingestion
pipeline is the main ETL workflow.
