"""Import every model here so Alembic autogenerate sees all tables."""

from .crawl import CrawledDocument, CrawlRun, StoredFile
from .domain import Domain
from .geography import District, LocalBody, Province, RegionLink
from .gold import (
    DomainStats,
    GeoContentStats,
    PageScore,
    RelevanceJudgment,
    SearchClick,
    SearchQuery,
)
from .ops import AdminUser, ErrorLog
from .views import page_geo_codes, search_documents
from .silver import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingModel,
    Entity,
    Page,
    PageContact,
    PageEmbedding,
    PageEntity,
    PageGeoTag,
    PageMedia,
    PageSource,
    QuarantinedFile,
)

__all__ = [
    # bronze
    "CrawlRun",
    "CrawledDocument",
    "StoredFile",
    # reference
    "Domain",
    "Province",
    "District",
    "LocalBody",
    "RegionLink",
    # silver
    "Page",
    "PageGeoTag",
    "PageContact",
    "PageSource",
    "PageMedia",
    "Entity",
    "PageEntity",
    "PageEmbedding",
    "QuarantinedFile",
    "EmbeddingModel",
    "DEFAULT_EMBEDDING_MODEL",
    # gold
    "DomainStats",
    "GeoContentStats",
    "PageScore",
    "SearchQuery",
    "SearchClick",
    "RelevanceJudgment",
    # ops
    "AdminUser",
    "ErrorLog",
    # views (read-only)
    "page_geo_codes",
    "search_documents",
]
