-- Adds the fields a search-engine-grade crawl needs beyond title/body/links:
-- the SERP-snippet source (meta_description), the page's structural
-- outline (headings, JSONB array of {level, text}), the resolved origin
-- host, and the best-guess origin country used by the crawl's
-- CountryFilter option (see internal/workflows.CrawlWorkflowInput).
ALTER TABLE documents ADD COLUMN meta_description TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN headings JSONB NOT NULL DEFAULT '[]';
ALTER TABLE documents ADD COLUMN host TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN country TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_documents_country ON documents (country);
