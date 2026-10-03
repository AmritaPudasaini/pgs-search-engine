-- Stored as a signed BIGINT holding the uint64 fingerprint's bit pattern
-- (Postgres has no unsigned 64-bit type); round-tripped via a plain Go
-- int64<->uint64 conversion in internal/storage, which preserves every bit.
ALTER TABLE documents ADD COLUMN sim_hash BIGINT NOT NULL DEFAULT 0;
