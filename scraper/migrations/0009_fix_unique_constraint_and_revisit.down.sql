ALTER TABLE documents DROP CONSTRAINT documents_normalized_url_key;
ALTER TABLE documents ADD CONSTRAINT documents_normalized_url_content_hash_key UNIQUE (normalized_url, content_hash);
