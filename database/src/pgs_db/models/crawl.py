"""Bronze layer: exactly what the scraper produces.

Columns mirror scraper/internal/model (Document, CrawlStats, StoredDocument)
so the Go writer can insert with no transformation.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, IdMixin, TimestampMixin
from ..enums import CrawlRunStatus, ProcessingStatus
from ._types import str_enum

TextArray = ARRAY(Text)


class CrawlRun(IdMixin, TimestampMixin, Base):
    """One crawl batch (Document.crawl_run_id points here). Counts = CrawlStats."""

    __tablename__ = "crawl_runs"

    category: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[CrawlRunStatus] = mapped_column(
        str_enum(CrawlRunStatus, "crawl_run_status"), default=CrawlRunStatus.RUNNING
    )
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_url_count: Mapped[int] = mapped_column(Integer, default=0)

    documents: Mapped[list["CrawledDocument"]] = relationship(back_populates="crawl_run")


class CrawledDocument(IdMixin, TimestampMixin, Base):
    """One crawled page = scraper model.Document."""

    __tablename__ = "crawled_documents"
    __table_args__ = (UniqueConstraint("normalized_url", "content_hash"),)

    crawl_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("crawl_runs.id"), index=True
    )
    domain_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("domains.id"), index=True)

    # URLs
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(64))

    # Page content
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    meta_keywords: Mapped[list[str] | None] = mapped_column(TextArray)
    open_graph: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    text: Mapped[str | None] = mapped_column(Text)
    headings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)  # [{level, text}]
    json_ld: Mapped[list[str] | None] = mapped_column(TextArray)

    # Contacts (Document.contact_info + social_links)
    emails: Mapped[list[str] | None] = mapped_column(TextArray)
    phones: Mapped[list[str] | None] = mapped_column(TextArray)
    address: Mapped[str | None] = mapped_column(Text)
    social_links: Mapped[list[str] | None] = mapped_column(TextArray)

    # Links (anchor_texts is parallel to links, same index)
    links: Mapped[list[str] | None] = mapped_column(TextArray)
    anchor_texts: Mapped[list[str] | None] = mapped_column(TextArray)
    internal_links: Mapped[list[str] | None] = mapped_column(TextArray)
    external_links: Mapped[list[str] | None] = mapped_column(TextArray)
    image_links: Mapped[list[str] | None] = mapped_column(TextArray)
    video_links: Mapped[list[str] | None] = mapped_column(TextArray)

    # Location signals from the page
    geo_lat: Mapped[float | None] = mapped_column(Float)
    geo_lng: Mapped[float | None] = mapped_column(Float)
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2

    # Fetch details
    # Go uint64 -> stored as signed BIGINT: write int64(simHash), read uint64(v).
    # The bits are identical, so Hamming distance still works.
    sim_hash: Mapped[int | None] = mapped_column(BigInteger)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetch_duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)

    # Pipeline
    minio_path: Mapped[str | None] = mapped_column(Text)  # DFSPayload object key
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        str_enum(ProcessingStatus, "processing_status"),
        default=ProcessingStatus.UNPROCESSED,
        server_default=ProcessingStatus.UNPROCESSED.value,
        index=True,
    )

    crawl_run: Mapped[CrawlRun | None] = relationship(back_populates="documents")
    stored_files: Mapped[list["StoredFile"]] = relationship(back_populates="crawled_document")


class StoredFile(IdMixin, TimestampMixin, Base):
    """A PDF/doc/image saved to MinIO = scraper model.StoredDocument."""

    __tablename__ = "stored_files"
    __table_args__ = (UniqueConstraint("document_url", "sha256"),)

    crawled_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("crawled_documents.id"), index=True
    )
    source_page_url: Mapped[str] = mapped_column(Text)
    document_url: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        str_enum(ProcessingStatus, "processing_status"),
        default=ProcessingStatus.UNPROCESSED,
        server_default=ProcessingStatus.UNPROCESSED.value,
    )

    crawled_document: Mapped[CrawledDocument | None] = relationship(back_populates="stored_files")
