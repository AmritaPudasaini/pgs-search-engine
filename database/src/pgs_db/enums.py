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
    # Bronze only: ClamAV flagged the payload. Never claimed again; see quarantined_files.
    QUARANTINED = "QUARANTINED"


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


class ContactType(enum.StrEnum):
    """Kind of contact detail extracted from a page.

    Mirrors the three contact sources Bronze already carries on
    `crawled_documents`: `emails`, `phones` and `social_links`.
    """

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    SOCIAL = "SOCIAL"


class Language(enum.StrEnum):
    """Dominant language of a page's body text."""

    NE = "NE"
    EN = "EN"
    MIXED = "MIXED"
    OTHER = "OTHER"


class GeoTagMethod(enum.StrEnum):
    """How a geo tag was resolved against the gazetteer."""

    GAZETTEER = "GAZETTEER"  # place name matched in body text
    NER = "NER"  # named-entity recognition
    DOMAIN = "DOMAIN"  # the site itself belongs to a local body
    GEO_META = "GEO_META"  # geo.* meta tags / structured data


class MediaType(enum.StrEnum):
    """What a `page_media` row points at."""

    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    DOCUMENT = "DOCUMENT"  # a linked PDF / DOCX / ...


class EntityType(enum.StrEnum):
    """Named-entity class for `entities` (places are geo tags, not entities)."""

    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    EVENT = "EVENT"
    OTHER = "OTHER"


class QuarantineStatus(enum.StrEnum):
    """State of a `quarantined_files` row."""

    QUARANTINED = "QUARANTINED"  # isolated in the quarantine bucket
    DELETED = "DELETED"  # an admin erased the object; the row stays as the audit record


class AdminRole(enum.StrEnum):
    """What an `admin_users` row may do in the admin API (see api/README.md §2.1)."""

    SUPER_ADMIN = "SUPER_ADMIN"  # everything, including managing admin users
    SYSTEM_OPERATOR = "SYSTEM_OPERATOR"  # domains, crawls, quarantine actions
    AUDITOR = "AUDITOR"  # read-only


class ServiceName(enum.StrEnum):
    """Which service wrote an `error_logs` row: the API's `service` filter values."""

    SCRAPER = "SCRAPER"
    ETL = "ETL"
    SECURITY = "SECURITY"  # the ClamAV scan
    SEARCH = "SEARCH"
    API = "API"


class LogSeverity(enum.StrEnum):
    """Severity of an `error_logs` row. INFO and DEBUG belong in service logs, not here."""

    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class JudgmentSource(enum.StrEnum):
    """Where a `relevance_judgments` label came from."""

    HUMAN = "HUMAN"  # an admin graded it
    CLICK_MODEL = "CLICK_MODEL"  # inferred from search_clicks
