# Kafka Utilities (obsolete)

The scripts in this folder simulated the former hand-offs: a per-file
"file-ready" signal (`publish_ingestion_signal.py`) and per-page crawler
documents on `crawled-documents` (`publish_crawler_document.py`,
`publish_validation_documents.py`, `validate_consumer_idempotency.py`, for
`../consumer.py`). Neither exists any more.

The scraper -> ETL hand-off is now one `site_crawl_completed` event per
crawled website on `scraped_files_topic`, published by the scraper itself
(`scraper/internal/storage/site_events.go`) and processed by the
`etl_ingestion_pipeline` DAG. See `../../ETL_README.md`.
