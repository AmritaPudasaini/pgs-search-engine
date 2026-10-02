-- The original constraint was UNIQUE (normalized_url, content_hash), which
-- meant a page whose content changed between crawls got a NEW row instead
-- of updating the existing one in place (the ON CONFLICT target wouldn't
-- match, since content_hash now differs) -- silently accumulating one row
-- per URL per distinct content version ever seen, contrary to the original
-- migration's own comment claiming changed pages get "refreshed in place".
--
-- One row per normalized_url is both the correct semantics for "current
-- known state of this page" and a prerequisite for a freshness/revisit
-- policy: "how long ago was this URL last crawled" only makes sense
-- against a single current row, not an unbounded history of versions.
--
-- Note for a real production migration: this would need a backfill step to
-- collapse any pre-existing duplicate normalized_url rows first, or this
-- ALTER fails on the conflict. Fine for this project's dev-stage database.
ALTER TABLE documents DROP CONSTRAINT documents_normalized_url_content_hash_key;
ALTER TABLE documents ADD CONSTRAINT documents_normalized_url_key UNIQUE (normalized_url);
