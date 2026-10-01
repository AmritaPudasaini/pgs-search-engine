"""Gold layer: what the API, the map and ranking read, built from Bronze and Silver.

Two kinds of table live here:

- **Rebuilt summaries** -- `domain_stats`, `geo_content_stats`, `page_scores`. Nothing
  writes them directly; `StatsRepository` / `RankingRepository` recompute them, so they
  can always be dropped and rebuilt. `python -m pgs_db.jobs` runs the refreshes.
- **Search logs** -- `search_queries`, `search_clicks`, `relevance_judgments`. Written
  by the API as users search and admins label results; the reranker trains on them.
  No IP address or user agent is stored: a query is tied only to an opaque session id.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, IdMixin, TimestampMixin
from ..enums import JudgmentSource
from ._types import str_enum
from .domain import Domain


class DomainStats(IdMixin, TimestampMixin, Base):
    """Per-domain crawl, processing and authority figures for `GET /api/v1/admin/domains`.

    Counts are over distinct normalized URLs, not Bronze rows, so a page crawled
    ten times counts once. A URL's outcome is its latest fetch. The link figures
    (`inbound_link_count`, `authority_score`) come from `RankingRepository.refresh_scores`.
    """

    __tablename__ = "domain_stats"
    __table_args__ = (
        CheckConstraint(
            "discovered_links >= 0 AND scraped_pages >= 0 AND failed_pages >= 0"
            " AND page_count >= 0 AND quarantined_count >= 0 AND inbound_link_count >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "authority_score >= 0 AND authority_score <= 1", name="authority_score_range"
        ),
    )

    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), unique=True
    )
    # Distinct same-site links found on the domain's pages (the API's discovered_child_links).
    discovered_links: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # URLs whose latest fetch succeeded / failed (error set, or HTTP status >= 400).
    scraped_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Silver pages built from the domain, duplicates excluded.
    page_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Files still in quarantine (not yet deleted by an admin).
    quarantined_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Links into the domain's pages from pages on other domains.
    inbound_link_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 0..1: the domain's share of PageRank, log-scaled against the strongest domain.
    authority_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    domain: Mapped[Domain] = relationship()


class GeoContentStats(IdMixin, TimestampMixin, Base):
    """What the map shows per region: how much content is tagged there.

    One row per province, district and local body (837). A page counts in a region
    when any of its geo tags falls inside it, so a page tagged Pokhara counts for
    Pokhara, Kaski and Gandaki. Duplicates are excluded. The `by_*` maps break
    `page_count` down, e.g. `by_language = {"NE": 120, "EN": 64}`.
    """

    __tablename__ = "geo_content_stats"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(province_code, district_code, local_body_code) = 1",
            name="exactly_one_region",
        ),
        CheckConstraint(
            "page_count >= 0 AND document_count >= 0 AND domain_count >= 0",
            name="counts_non_negative",
        ),
        UniqueConstraint(
            "province_code",
            "district_code",
            "local_body_code",
            name="uq_geo_content_stats_region",
            postgresql_nulls_not_distinct=True,
        ),
    )

    province_code: Mapped[str | None] = mapped_column(
        ForeignKey("provinces.code", ondelete="CASCADE"), index=True
    )
    district_code: Mapped[str | None] = mapped_column(
        ForeignKey("districts.code", ondelete="CASCADE"), index=True
    )
    local_body_code: Mapped[str | None] = mapped_column(
        ForeignKey("local_bodies.code", ondelete="CASCADE"), index=True
    )
    page_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Pages built from stored files (PDFs, DOCX, ...).
    document_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    domain_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latest_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    by_content_type: Mapped[dict[str, int]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    by_language: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, server_default="{}")
    by_category: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, server_default="{}")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PageScore(IdMixin, TimestampMixin, Base):
    """Query-independent ranking signals for one canonical page.

    Rebuilt by `RankingRepository.refresh_scores` from the crawled link graph and
    Silver. All scores are 0..1 except `pagerank`, whose values sum to 1 over the
    graph. `static_rank` blends them (weights in `pgs_db.repositories.ranking`).
    """

    __tablename__ = "page_scores"
    __table_args__ = (
        CheckConstraint("pagerank >= 0", name="pagerank_non_negative"),
        CheckConstraint("inbound_links >= 0", name="inbound_links_non_negative"),
        CheckConstraint(
            "freshness_score BETWEEN 0 AND 1 AND quality_score BETWEEN 0 AND 1"
            " AND static_rank BETWEEN 0 AND 1",
            name="scores_in_range",
        ),
        Index("ix_page_scores_static_rank", "static_rank"),
    )

    page_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pages.id", ondelete="CASCADE"), unique=True
    )
    pagerank: Mapped[float] = mapped_column(Float)
    # Links from other pages (any domain) that resolve to this page.
    inbound_links: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    freshness_score: Mapped[float] = mapped_column(Float)
    quality_score: Mapped[float] = mapped_column(Float)
    static_rank: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SearchQuery(IdMixin, TimestampMixin, Base):
    """One search a user ran, as the API received and answered it."""

    __tablename__ = "search_queries"
    __table_args__ = (
        CheckConstraint("result_count >= 0", name="result_count_non_negative"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_non_negative"),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        # Time-ordered, append-only: BRIN is tiny and serves "the last N days" scans.
        Index("ix_search_queries_searched_at", "searched_at", postgresql_using="brin"),
        Index("ix_search_queries_normalized_query", "normalized_query"),
        Index("ix_search_queries_session_id", "session_id"),
    )

    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Opaque, rotating client session id. Never an account, IP or device id.
    session_id: Mapped[str | None] = mapped_column(String(64))
    query_text: Mapped[str] = mapped_column(Text)
    # Lowercased, whitespace-collapsed: what judgments and analytics group by.
    normalized_query: Mapped[str] = mapped_column(Text)
    query_language: Mapped[str | None] = mapped_column(String(16))
    translated_text: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    page_number: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    result_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    clicks: Mapped[list["SearchClick"]] = relationship(
        back_populates="search_query", cascade="all, delete-orphan"
    )


class SearchClick(IdMixin, TimestampMixin, Base):
    """A result the user opened from a search."""

    __tablename__ = "search_clicks"
    __table_args__ = (
        CheckConstraint("rank_position >= 1", name="rank_position_positive"),
        CheckConstraint("dwell_ms IS NULL OR dwell_ms >= 0", name="dwell_non_negative"),
    )

    search_query_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("search_queries.id", ondelete="CASCADE"), index=True
    )
    # SET NULL: the click stays in the log after the page is gone; `url` keeps what it was.
    page_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pages.id", ondelete="SET NULL"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    rank_position: Mapped[int] = mapped_column(Integer)  # 1 = top result
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Time until the user came back to the results, when the client reports it.
    dwell_ms: Mapped[int | None] = mapped_column(Integer)

    search_query: Mapped[SearchQuery] = relationship(back_populates="clicks")


class RelevanceJudgment(IdMixin, TimestampMixin, Base):
    """How relevant a page is to a query: the reranker's training label.

    `grade` uses the reranker's scale: 0 irrelevant, 1 marginal, 2 relevant,
    3 perfect. One label per (query, page, judge); a judge re-labelling updates it.
    """

    __tablename__ = "relevance_judgments"
    __table_args__ = (
        CheckConstraint("grade BETWEEN 0 AND 3", name="grade_range"),
        UniqueConstraint(
            "normalized_query", "page_id", "judged_by", name="uq_relevance_judgments_label"
        ),
    )

    normalized_query: Mapped[str] = mapped_column(Text, index=True)
    page_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int] = mapped_column(SmallInteger)
    source: Mapped[JudgmentSource] = mapped_column(str_enum(JudgmentSource, "judgment_source"))
    # The admin's username for HUMAN labels, the model name for CLICK_MODEL ones.
    judged_by: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
