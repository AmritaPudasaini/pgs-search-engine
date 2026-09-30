"""Pydantic schemas for the Bronze tables.

Phase 1 scope only: the shapes the scraper writes and the API reads back. Field
constraints mirror the column definitions in `pgs_db.models`, so a payload that
validates here will not be rejected by PostgreSQL.

These validate the *column* shape. The scraper's own JSON (nested `geo` and
`contact_info`, `uint64` simhash, `crawl_run_id: 0`) is converted first by
`pgs_db.repositories`; see `docs/scraper-db-contract.md`.
"""

import re
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from ..enums import CrawlRunStatus, DomainCategory, DomainPriority, DomainStatus, ProcessingStatus
from .base import ReadSchema, SchemaBase

SHA256_PATTERN = r"^[0-9a-f]{64}$"

DOMAIN_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)


def validate_domain_name(value: str) -> str:
    """Normalize and validate a hostname such as example.gov.np (from Biyush's branch)."""
    normalized = value.strip().lower().rstrip(".")
    if "://" in normalized or "/" in normalized:
        raise ValueError("domain must be a hostname, not a complete URL")
    if not DOMAIN_PATTERN.fullmatch(normalized):
        raise ValueError("invalid domain name")
    return normalized


# ----------------------------------------------------------------------- domains


class DomainBase(SchemaBase):
    """Fields shared by all domain schemas."""

    domain: str = Field(
        min_length=1, max_length=255, description="Hostname, lowercase, e.g. mofaga.gov.np"
    )
    website_name: str | None = Field(default=None, max_length=255)
    category: DomainCategory = DomainCategory.OTHER
    status: DomainStatus = DomainStatus.PENDING
    priority: DomainPriority = DomainPriority.NORMAL
    rate_limit_per_sec: int = Field(default=1, gt=0, description="Must be positive (CHECK)")
    local_body_id: int | None = Field(default=None, description="Set for a municipality's own site")

    @field_validator("domain")
    @classmethod
    def check_domain(cls, value: str) -> str:
        return validate_domain_name(value)


class DomainCreate(DomainBase):
    """Data required when registering a domain to crawl."""


class DomainUpdate(SchemaBase):
    """Fields an admin may change on an existing domain."""

    website_name: str | None = Field(default=None, max_length=255)
    category: DomainCategory | None = None
    status: DomainStatus | None = None
    priority: DomainPriority | None = None
    rate_limit_per_sec: int | None = Field(default=None, gt=0)
    local_body_id: int | None = None


class DomainRead(DomainBase, ReadSchema):
    """Domain data returned by the application."""

    last_crawled_at: datetime | None = None


# -------------------------------------------------------------------- crawl runs


class CrawlRunBase(SchemaBase):
    """Fields shared by all crawl-run schemas."""

    category: str | None = Field(default=None, max_length=64)
    temporal_workflow_id: str | None = Field(default=None, max_length=255)
    started_at: datetime
    seed_count: int | None = Field(default=None, ge=0)
    max_depth: int | None = Field(default=None, ge=0)
    max_pages: int | None = Field(default=None, ge=0)


class CrawlRunCreate(CrawlRunBase):
    """Data required when opening a crawl run."""


class CrawlRunStats(SchemaBase):
    """The counters a crawl reports, matching the scraper's `CrawlStats`.

    `CrawlStats.Duration` has no column and is deliberately absent: it is derivable
    from finished_at - started_at.
    """

    fetched_count: int = Field(default=0, ge=0)
    succeeded_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    unique_url_count: int = Field(default=0, ge=0)
    domain_capped_count: int = Field(default=0, ge=0)


class CrawlRunFinish(SchemaBase):
    """Closing a run. A crawl that died must still be closed, as FAILED."""

    status: CrawlRunStatus = CrawlRunStatus.COMPLETED
    finished_at: datetime
    stats: CrawlRunStats | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _must_be_terminal(self) -> "CrawlRunFinish":
        if self.status is CrawlRunStatus.RUNNING:
            raise ValueError("a finished run cannot have status RUNNING")
        return self


class CrawlRunRead(CrawlRunBase, CrawlRunStats, ReadSchema):
    """Crawl-run data returned by the application."""

    status: CrawlRunStatus
    finished_at: datetime | None = None
    error: str | None = None


# --------------------------------------------------------------------- documents


class CrawledDocumentBase(SchemaBase):
    """Column-shaped view of one crawled page.

    Optional strings are `None`, never `""` — the repository converts Go's
    `omitempty` blanks before this schema ever sees them.
    """

    url: str = Field(min_length=1)
    normalized_url: str = Field(min_length=1, description="Dedupe identity with content_hash")
    content_hash: str = Field(pattern=SHA256_PATTERN)
    fetched_at: datetime
    depth: int = Field(default=0, ge=0)

    crawl_run_id: int | None = None
    domain_id: int | None = None

    final_url: str | None = None
    canonical_url: str | None = None
    host: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)

    title: str | None = None
    meta_description: str | None = None
    meta_keywords: list[str] | None = None
    open_graph: dict[str, str] | None = None
    text: str | None = None
    headings: list[dict[str, object]] | None = None
    json_ld: list[str] | None = None

    emails: list[str] | None = None
    phones: list[str] | None = None
    address: str | None = None
    social_links: list[str] | None = None

    links: list[str] | None = None
    anchor_texts: list[str] | None = None
    internal_links: list[str] | None = None
    external_links: list[str] | None = None
    image_links: list[str] | None = None
    video_links: list[str] | None = None

    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lng: float | None = Field(default=None, ge=-180, le=180)
    country: str | None = Field(default=None, min_length=2, max_length=2)

    sim_hash: int | None = Field(default=None, description="Signed int64; Go writes int64(simHash)")
    status_code: int | None = None
    content_type: str | None = Field(default=None, max_length=255)
    fetch_duration_ms: int | None = Field(default=None, ge=0)
    error: str | None = None
    minio_path: str | None = None

    @model_validator(mode="after")
    def _anchor_texts_match_links(self) -> "CrawledDocumentBase":
        # Parallel arrays: same index means same link. The database cannot enforce this.
        if self.anchor_texts is not None and len(self.anchor_texts) != len(self.links or []):
            raise ValueError("anchor_texts must be the same length as links")
        return self


class CrawledDocumentCreate(CrawledDocumentBase):
    """Data required to store one crawled page."""


class CrawledDocumentRead(CrawledDocumentBase, ReadSchema):
    """Crawled-page data returned by the application."""

    processing_status: ProcessingStatus = ProcessingStatus.UNPROCESSED


# ------------------------------------------------------------------ stored files


class StoredFileBase(SchemaBase):
    """Column-shaped view of one object saved to MinIO."""

    source_page_url: str = Field(min_length=1)
    document_url: str = Field(min_length=1, description="Dedupe identity with sha256")
    storage_path: str = Field(min_length=1, description="MinIO object key, not the bytes")
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0, description="`Size` in the scraper's StoredDocument")
    stored_at: datetime
    content_type: str | None = Field(default=None, max_length=255)
    crawled_document_id: int | None = None


class StoredFileCreate(StoredFileBase):
    """Data required to record a stored file."""


class StoredFileRead(StoredFileBase, ReadSchema):
    """Stored-file data returned by the application."""

    processing_status: ProcessingStatus = ProcessingStatus.UNPROCESSED
    processing_error: str | None = None
