ALTER TABLE documents ADD COLUMN crawl_run_id BIGINT REFERENCES crawl_runs (id);
CREATE INDEX idx_documents_crawl_run_id ON documents (crawl_run_id);
