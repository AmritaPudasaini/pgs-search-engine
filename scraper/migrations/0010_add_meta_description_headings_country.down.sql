DROP INDEX idx_documents_country;
ALTER TABLE documents DROP COLUMN country;
ALTER TABLE documents DROP COLUMN host;
ALTER TABLE documents DROP COLUMN headings;
ALTER TABLE documents DROP COLUMN meta_description;
