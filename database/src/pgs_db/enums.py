"""Fixed status values. Stored as VARCHAR + CHECK (not native PG enums) so the
Go scraper and Spark can insert plain strings without casts."""

import enum


class CrawlRunStatus(enum.StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingStatus(enum.StrEnum):
    UNPROCESSED = "UNPROCESSED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class DomainStatus(enum.StrEnum):
    PENDING = "PENDING"
    CRAWLING = "CRAWLING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DomainPriority(enum.StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class DomainCategory(enum.StrEnum):
    GOVERNMENT = "GOVERNMENT"
    NEWS = "NEWS"
    EDUCATION = "EDUCATION"
    FINANCE = "FINANCE"
    NGO = "NGO"
    COMMERCIAL = "COMMERCIAL"
    OTHER = "OTHER"


class LocalBodyType(enum.StrEnum):
    METROPOLITAN_CITY = "METROPOLITAN_CITY"
    SUB_METROPOLITAN_CITY = "SUB_METROPOLITAN_CITY"
    MUNICIPALITY = "MUNICIPALITY"
    RURAL_MUNICIPALITY = "RURAL_MUNICIPALITY"
