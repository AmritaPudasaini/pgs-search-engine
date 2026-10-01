"""Import every model here so Alembic autogenerate sees all tables."""

from .crawl import CrawledDocument, CrawlRun, StoredFile
from .domain import Domain
from .geography import District, LocalBody, Province

__all__ = [
    "CrawlRun",
    "CrawledDocument",
    "StoredFile",
    "Domain",
    "Province",
    "District",
    "LocalBody",
]
