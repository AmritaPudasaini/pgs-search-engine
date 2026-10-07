"""Pydantic schemas for Gold and the admin dashboard reads built on it."""

from datetime import datetime
from typing import Any

from pydantic import Field

from ..enums import DomainCategory, DomainPriority, DomainStatus, JudgmentSource
from .base import ReadSchema, SchemaBase
from .silver import QuarantineSummary


class DomainStatsRead(ReadSchema):
    """One `domain_stats` row."""

    domain_id: int
    discovered_links: int = Field(ge=0)
    scraped_pages: int = Field(ge=0)
    failed_pages: int = Field(ge=0)
    page_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    last_fetched_at: datetime | None = None
    computed_at: datetime


class DomainOverview(SchemaBase):
    """One row of `GET /api/v1/admin/domains`: the domain joined with its stats."""

    id: int
    domain: str
    website_name: str | None = None
    category: DomainCategory
    status: DomainStatus
    priority: DomainPriority
    rate_limit_per_sec: int
    last_crawled_at: datetime | None = None
    discovered_links: int = Field(ge=0)
    scraped_pages: int = Field(ge=0)
    failed_pages: int = Field(ge=0)
    page_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    last_fetched_at: datetime | None = None
    stats_computed_at: datetime | None = Field(
        default=None, description="None until the first refresh_domain_stats"
    )


class DomainCounts(SchemaBase):
    total_registered: int = Field(ge=0)
    pending: int = Field(ge=0)
    active_crawling: int = Field(ge=0)
    paused: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed_or_blocked: int = Field(ge=0)


class LinkCounts(SchemaBase):
    total_child_links_discovered: int = Field(ge=0)


class StorageMetrics(SchemaBase):
    """Bronze work queue (crawled pages + stored files) and bytes stored."""

    total_raw_files: int = Field(ge=0)
    unprocessed_files: int = Field(ge=0)
    processing_files: int = Field(ge=0)
    processed_files: int = Field(ge=0)
    failed_files: int = Field(ge=0)
    quarantined_files: int = Field(ge=0)
    unprocessed_size_bytes: int = Field(ge=0, description="Stored files only")
    oldest_unprocessed_at: datetime | None = None
    total_storage_used_bytes: int = Field(ge=0, description="Stored files only")


class ErrorCounts(SchemaBase):
    WARN: int = Field(ge=0)
    ERROR: int = Field(ge=0)
    FATAL: int = Field(ge=0)


class DashboardSummary(SchemaBase):
    """The database's part of `GET /api/v1/admin/dashboard/summary`.

    The API adds `system_status`, the infrastructure block and the scraper's queue
    counts from the services themselves.
    """

    timestamp: datetime
    domains: DomainCounts
    links: LinkCounts
    storage: StorageMetrics
    quarantine: QuarantineSummary
    errors_last_24h: ErrorCounts


class GeoContentCount(SchemaBase):
    """One region of the map's content counts (`StatsRepository.geo_content`)."""

    level: str
    code: str
    page_count: int = Field(ge=0)
    document_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    latest_published_at: datetime | None = None
    by_content_type: dict[str, int]
    by_language: dict[str, int]
    by_category: dict[str, int]
    computed_at: datetime


class PageScoreRead(ReadSchema):
    page_id: int
    pagerank: float = Field(ge=0)
    inbound_links: int = Field(ge=0)
    freshness_score: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    static_rank: float = Field(ge=0, le=1)
    computed_at: datetime


class SearchQueryCreate(SchemaBase):
    """What the API logs for one answered search."""

    query_text: str = Field(max_length=2000)
    result_count: int = Field(ge=0)
    session_id: str | None = Field(default=None, max_length=64)
    query_language: str | None = Field(default=None, max_length=16)
    translated_text: str | None = None
    filters: dict[str, Any] | None = None
    page_number: int = Field(default=1, ge=1)
    latency_ms: int | None = Field(default=None, ge=0)


class SearchQueryRead(ReadSchema):
    searched_at: datetime
    session_id: str | None = None
    query_text: str
    normalized_query: str
    query_language: str | None = None
    translated_text: str | None = None
    filters: dict[str, Any] | None = None
    page_number: int
    result_count: int
    latency_ms: int | None = None


class SearchClickCreate(SchemaBase):
    search_query_id: int
    url: str
    rank_position: int = Field(ge=1)
    page_id: int | None = None
    dwell_ms: int | None = Field(default=None, ge=0)


class SearchClickRead(ReadSchema):
    search_query_id: int
    page_id: int | None = None
    url: str
    rank_position: int
    clicked_at: datetime
    dwell_ms: int | None = None


class RelevanceJudgmentCreate(SchemaBase):
    query: str = Field(min_length=1)
    page_id: int
    grade: int = Field(ge=0, le=3, description="0 irrelevant, 1 marginal, 2 relevant, 3 perfect")
    notes: str | None = None


class RelevanceJudgmentRead(ReadSchema):
    normalized_query: str
    page_id: int
    grade: int
    source: JudgmentSource
    judged_by: str
    notes: str | None = None


class SearchTraffic(SchemaBase):
    """The dashboard's search cards over a time window."""

    searches: int = Field(ge=0)
    queries_per_second: float = Field(ge=0)
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    zero_result_rate: float = Field(ge=0, le=1)
    click_through_rate: float = Field(ge=0)
