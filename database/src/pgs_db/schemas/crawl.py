"""Pydantic schemas for Bronze-layer crawling records."""

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from pgs_db.enums import CrawlRunStatus, ProcessingStatus

from .base import ReadSchema, SchemaBase


class CrawlRunBase(SchemaBase):
    """Fields shared by all crawl-run schemas."""

    category: str | None = Field(default=None, max_length=64)
    status: CrawlRunStatus = CrawlRunStatus.RUNNING
    temporal_workflow_id: str | None = Field(default=None, max_length=255)
    started_at: datetime
    finished_at: datetime | None = None
    fetched_count: int = Field(default=0, ge=0)
    succeeded_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    unique_url_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_dates(self) -> "CrawlRunBase":
        """Ensure that a crawl cannot finish before it starts."""

        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be earlier than started_at")

        return self


class CrawlRunCreate(CrawlRunBase):
    """Data required when creating a crawl run."""


class CrawlRunUpdate(SchemaBase):
    """Fields that may be updated while a crawl is running."""

    status: CrawlRunStatus | None = None
    finished_at: datetime | None = None
    fetched_count: int | None = Field(default=None, ge=0)
    succeeded_count: int | None = Field(default=None, ge=0)
    failed_count: int | None = Field(default=None, ge=0)
    skipped_count: int | None = Field(default=None, ge=0)
    unique_url_count: int | None = Field(default=None, ge=0)


class CrawlRunRead(CrawlRunBase, ReadSchema):
    """Crawl-run data returned by the application."""

    class CrawledDocumentBase(SchemaBase):
    """Fields shared by all crawled-document schemas."""

    crawl_run_id: int | None = Field(default=None, gt=0)
    domain_id: int | None = Field(default=None, gt=0)

    url: str = Field(min_length=1)
    normalized_url: str = Field(min_length=1)
    final_url: str | None = None
    canonical_url: str | None = None
    host: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)

    title: str | None = None
    meta_description: str | None = None
    meta_keywords: list[str] | None = None
    open_graph: dict[str, str] | None = None
    text: str | None = None
    headings: list[dict[str, Any]] | None = None
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

    sim_hash: int | None = None
    depth: int = Field(default=0, ge=0)
    status_code: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=255)
    content_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    fetched_at: datetime
    fetch_duration_ms: int | None = Field(default=None, ge=0)
    error: str | None = None

    minio_path: str | None = None
    processing_status: ProcessingStatus = ProcessingStatus.UNPROCESSED

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, value: str | None) -> str | None:
        """Normalize a country code such as np to NP."""

        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_parallel_links(self) -> "CrawledDocumentBase":
        """Ensure that links and anchor texts match by position."""

        if (
            self.links is not None
            and self.anchor_texts is not None
            and len(self.links) != len(self.anchor_texts)
        ):
            raise ValueError(
                "links and anchor_texts must have the same number of items"
            )

        return self


class CrawledDocumentCreate(CrawledDocumentBase):
    """Data required when creating a crawled-document record."""


class CrawledDocumentUpdate(SchemaBase):
    """Fields that may be changed after processing a document."""

    title: str | None = None
    meta_description: str | None = None
    text: str | None = None
    minio_path: str | None = None
    processing_status: ProcessingStatus | None = None
    error: str | None = None


class CrawledDocumentRead(CrawledDocumentBase, ReadSchema):
    """Crawled-document data returned by the application."""

class StoredFileBase(SchemaBase):
    """Fields shared by all stored-file schemas."""

    crawled_document_id: int | None = Field(default=None, gt=0)
    source_page_url: str = Field(
        min_length=1,
        description="Page where the stored file was discovered",
    )
    document_url: str = Field(
        min_length=1,
        description="Original URL of the downloaded file",
    )
    storage_path: str = Field(
        min_length=1,
        description="Path of the file in MinIO",
    )
    content_type: str | None = Field(default=None, max_length=255)
    sha256: str = Field(
        pattern=r"^[0-9a-fA-F]{64}$",
        description="SHA-256 hash used to identify the file",
    )
    size_bytes: int = Field(
        ge=0,
        description="Size of the downloaded file in bytes",
    )
    stored_at: datetime
    processing_status: ProcessingStatus = ProcessingStatus.UNPROCESSED


class StoredFileCreate(StoredFileBase):
    """Data required when recording a stored file."""


class StoredFileUpdate(SchemaBase):
    """Fields that may be changed while processing a stored file."""

    processing_status: ProcessingStatus | None = None


class StoredFileRead(StoredFileBase, ReadSchema):
    """Stored-file data returned by the application."""