"""Translate the Go scraper's JSON into Bronze-table column dicts.

The scraper marshals `internal/model.Document`, `CrawlStats` and `StoredDocument`
straight to JSON (NDJSON file, Kafka message, or a direct Postgres write). Every
quirk of that encoding is handled here, in one place, so no caller has to know
about it:

* `omitempty` renders an absent string as `""` -- stored as NULL, not an empty row value.
* `CrawlRunID` is `0` when no run-tracking backend was configured -- stored as NULL,
  since 0 is not a valid `crawl_runs.id` and would violate the foreign key.
* `SimHash` is `uint64`; Postgres has no unsigned type. Values above int64 max are
  wrapped to their two's-complement signed form, exactly as Go's `int64(v)` does.
  The bits are unchanged, so Hamming distance still works after reading back.
* `Geo` is a nullable pointer holding `{lat, lng}` -- flattened to two columns.
* `ContactInfo` is a nested object -- flattened to `emails`/`phones`/`address`.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

UINT64_WRAP = 1 << 64
INT64_MAX = (1 << 63) - 1

# Document JSON key -> crawled_documents column, for fields that need no conversion.
_DIRECT: tuple[tuple[str, str], ...] = (
    ("url", "url"),
    ("normalized_url", "normalized_url"),
    ("final_url", "final_url"),
    ("canonical_url", "canonical_url"),
    ("host", "host"),
    ("category", "category"),
    ("title", "title"),
    ("meta_description", "meta_description"),
    ("meta_keywords", "meta_keywords"),
    ("open_graph", "open_graph"),
    ("text", "text"),
    ("headings", "headings"),
    ("json_ld", "json_ld"),
    ("social_links", "social_links"),
    ("links", "links"),
    ("anchor_texts", "anchor_texts"),
    ("internal_links", "internal_links"),
    ("external_links", "external_links"),
    ("image_links", "image_links"),
    ("video_links", "video_links"),
    ("country", "country"),
    ("content_type", "content_type"),
    ("content_hash", "content_hash"),
    ("error", "error"),
)


def blank_to_none(value: Any) -> Any:
    """Go's `omitempty` gives `""` for an absent string; the column wants NULL."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def signed_simhash(value: int | None) -> int | None:
    """uint64 -> int64 with identical bits, matching Go's `int64(simHash)`."""
    if value is None:
        return None
    return value - UINT64_WRAP if value > INT64_MAX else value


def unsigned_simhash(value: int | None) -> int | None:
    """int64 -> uint64, matching Go's `uint64(v)`. Inverse of signed_simhash."""
    if value is None:
        return None
    return value + UINT64_WRAP if value < 0 else value


def parse_timestamp(value: Any, field: str) -> datetime:
    """Parse Go's RFC 3339 output. A naive value is assumed UTC (rule 3 in the README)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{field} is required and must be an RFC 3339 timestamp")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def document_row(
    doc: Mapping[str, Any],
    *,
    crawl_run_id: int | None = None,
    domain_id: int | None = None,
    minio_path: str | None = None,
) -> dict[str, Any]:
    """Build the `crawled_documents` column dict for one scraper Document.

    `crawl_run_id` / `domain_id` override whatever the document carries, so a caller
    that has already resolved them does not pay for the lookup twice.
    """
    row: dict[str, Any] = {col: blank_to_none(doc.get(key)) for key, col in _DIRECT}

    for required in ("url", "normalized_url", "content_hash"):
        if not row.get(required):
            raise ValueError(f"document is missing required field {required!r}")

    # `depth` is NOT NULL with no server default, so it always has to be sent.
    row["depth"] = int(doc.get("depth") or 0)
    row["status_code"] = doc.get("status_code")
    row["fetch_duration_ms"] = doc.get("fetch_duration_ms")
    row["fetched_at"] = parse_timestamp(doc.get("fetched_at"), "fetched_at")
    row["sim_hash"] = signed_simhash(doc.get("sim_hash"))

    contact = doc.get("contact_info") or {}
    row["emails"] = contact.get("emails")
    row["phones"] = contact.get("phones")
    row["address"] = blank_to_none(contact.get("address"))

    geo = doc.get("geo") or {}
    row["geo_lat"] = geo.get("lat")
    row["geo_lng"] = geo.get("lng")

    # 0 means "no run-tracking backend configured", not crawl_runs.id = 0.
    run_id = crawl_run_id if crawl_run_id is not None else doc.get("crawl_run_id") or None
    row["crawl_run_id"] = run_id or None
    row["domain_id"] = domain_id
    row["minio_path"] = blank_to_none(minio_path)
    return row


def stored_file_row(
    stored: Mapping[str, Any], *, crawled_document_id: int | None = None
) -> dict[str, Any]:
    """Build the `stored_files` column dict for one scraper StoredDocument."""
    row: dict[str, Any] = {
        "source_page_url": blank_to_none(stored.get("source_page_url")),
        "document_url": blank_to_none(stored.get("document_url")),
        "storage_path": blank_to_none(stored.get("storage_path")),
        "content_type": blank_to_none(stored.get("content_type")),
        "sha256": blank_to_none(stored.get("sha256")),
        "size_bytes": int(stored.get("size") or 0),
        "stored_at": parse_timestamp(stored.get("stored_at"), "stored_at"),
        "crawled_document_id": crawled_document_id,
    }
    for required in ("source_page_url", "document_url", "storage_path", "sha256"):
        if not row.get(required):
            raise ValueError(f"stored document is missing required field {required!r}")
    return row


def crawl_stats_columns(stats: Mapping[str, Any] | None) -> dict[str, int]:
    """Map CrawlStats onto the crawl_runs counters. `Duration` is intentionally
    dropped: it is derivable from started_at/finished_at and has no column."""
    stats = stats or {}
    return {
        "fetched_count": int(stats.get("fetched") or 0),
        "succeeded_count": int(stats.get("succeeded") or 0),
        "failed_count": int(stats.get("failed") or 0),
        "skipped_count": int(stats.get("skipped") or 0),
        "unique_url_count": int(stats.get("unique_urls") or 0),
        # URLs dropped by the per-domain page cap (the Temporal scraper's run recorder).
        "domain_capped_count": int(stats.get("domain_capped") or 0),
    }
