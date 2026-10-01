"""Pydantic schemas for the Silver tables.

Field constraints mirror the column definitions in
`pgs_db.models.silver`, which in turn trace to `ETL/spark/README.md` §5.2 and the
search team's `SearchDocument` / `GeoLocation`.

`GeoLocationOut` is the one schema that is *not* column-shaped: it rebuilds §5.2's
denormalized `geo_location` block by joining the gazetteer, so the ETL and search
teams get back exactly the payload they expect without storing names per page.
"""

from datetime import datetime

from pydantic import Field, model_validator

from ..enums import (
    ContactType,
    EntityType,
    GeoTagMethod,
    Language,
    LocalBodyType,
    MediaType,
    ProcessingStatus,
    QuarantineStatus,
)
from .base import ReadSchema, SchemaBase
from .bronze import SHA256_PATTERN


class PageContactBase(SchemaBase):
    """One contact detail extracted from a page."""

    type: ContactType
    value: str = Field(min_length=1)


class PageContactCreate(PageContactBase):
    """Data required to attach a contact to a page."""


class PageContactRead(PageContactBase, ReadSchema):
    """Contact data returned by the application."""

    page_id: int


class PageGeoTagBase(SchemaBase):
    """One administrative location a page is about.

    Codes only. All three levels are optional because geo resolution is partial in
    practice, but at least one must be present -- the same rule the CHECK enforces.
    """

    province_code: str | None = Field(default=None, pattern=r"^P[1-7]$")
    district_code: str | None = Field(default=None, pattern=r"^D[0-7][0-9]$")
    local_body_code: str | None = Field(default=None, max_length=16)
    ward_number: int | None = Field(default=None, gt=0)

    method: GeoTagMethod
    confidence: float = Field(ge=0.0, le=1.0)
    mention_text: str | None = None

    @model_validator(mode="after")
    def _at_least_one_level(self) -> "PageGeoTagBase":
        if (
            self.province_code is None
            and self.district_code is None
            and self.local_body_code is None
        ):
            raise ValueError(
                "a geo tag needs at least one of province_code, district_code, local_body_code"
            )
        return self


class PageGeoTagCreate(PageGeoTagBase):
    """Data required to tag a page with a location."""


class PageGeoTagRead(PageGeoTagBase, ReadSchema):
    """Geo-tag data returned by the application."""

    page_id: int


class GeoLocationOut(SchemaBase):
    """§5.2's `geo_location` block, rebuilt from the gazetteer.

    This is what the ETL and search teams consume. The names are never stored on
    the page; they come from `provinces`, `districts` and `local_bodies`.
    """

    province_code: str | None = None
    province_name_en: str | None = None
    province_name_ne: str | None = None

    district_code: str | None = None
    district_name_en: str | None = None
    district_name_ne: str | None = None

    municipality_id: str | None = None
    municipality_type: LocalBodyType | None = None
    municipality_name_en: str | None = None
    municipality_name_ne: str | None = None

    ward_number: int | None = None

    @classmethod
    def from_tag(cls, tag: object) -> "GeoLocationOut":
        """Build the block from a `PageGeoTag` with its relationships loaded."""
        province = getattr(tag, "province", None)
        district = getattr(tag, "district", None)
        local_body = getattr(tag, "local_body", None)
        # A tag resolved only to a local body still knows its district and province.
        if district is None and local_body is not None:
            district = getattr(local_body, "district", None)
        if province is None and district is not None:
            province = getattr(district, "province", None)
        return cls(
            province_code=getattr(province, "code", None),
            province_name_en=getattr(province, "name_en", None),
            province_name_ne=getattr(province, "name_ne", None),
            district_code=getattr(district, "code", None),
            district_name_en=getattr(district, "name_en", None),
            district_name_ne=getattr(district, "name_ne", None),
            municipality_id=getattr(local_body, "code", None),
            municipality_type=getattr(local_body, "type", None),
            municipality_name_en=getattr(local_body, "name_en", None),
            municipality_name_ne=getattr(local_body, "name_ne", None),
            ward_number=getattr(tag, "ward_number", None),
        )


class PageBase(SchemaBase):
    """Column-shaped view of one Silver page."""

    canonical_url: str = Field(min_length=1, description="The page's identity")
    content_hash: str = Field(pattern=SHA256_PATTERN)

    # Exactly one source: a crawled page or a stored file (PDF, image, ...).
    crawled_document_id: int | None = None
    stored_file_id: int | None = None
    domain_id: int | None = None

    title: str | None = None
    description: str | None = None
    body_text: str = Field(min_length=1)
    word_count: int = Field(ge=0)
    keywords: list[str] | None = None
    language: Language
    language_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    content_type: str = Field(default="web_page", max_length=32)
    category: str | None = Field(default=None, max_length=64)
    author: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None
    quality_flags: list[str] | None = None

    sim_hash: int | None = None
    duplicate_of_id: int | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "PageBase":
        if (self.crawled_document_id is None) == (self.stored_file_id is None):
            raise ValueError("a page needs exactly one of crawled_document_id, stored_file_id")
        return self


class PageCreate(PageBase):
    """Data required to store one Silver page."""


class PageRead(PageBase, ReadSchema):
    """Silver page data returned by the application."""

    processing_status: ProcessingStatus = ProcessingStatus.UNPROCESSED
    processing_error: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    version: int = Field(ge=1)


# ------------------------------------------------------------------ page sources


class PageSourceRead(ReadSchema):
    """One Bronze row that fed a page (fetch history). Written only by save_page."""

    page_id: int
    crawled_document_id: int | None = None
    stored_file_id: int | None = None
    fetched_at: datetime
    content_changed: bool


# --------------------------------------------------------------------- page media


class PageMediaBase(SchemaBase):
    """An image, video or linked document on a page."""

    url: str = Field(min_length=1)
    media_type: MediaType
    alt_text: str | None = None
    extracted_text: str | None = Field(default=None, description="OCR or parsed text")
    context_text: str | None = Field(default=None, description="Caption / nearby text")
    stored_file_id: int | None = None


class PageMediaCreate(PageMediaBase):
    """Data required to attach media to a page."""


class PageMediaRead(PageMediaBase, ReadSchema):
    """Media data returned by the application."""

    page_id: int


# ----------------------------------------------------------------------- entities


class EntityBase(SchemaBase):
    """A person, organization or event, shared by every page that names it."""

    normalized_key: str = Field(min_length=1, max_length=255)
    type: EntityType
    name_en: str | None = Field(default=None, max_length=255)
    name_ne: str | None = Field(default=None, max_length=255)


class EntityCreate(EntityBase):
    """Data required to record an entity."""


class EntityRead(EntityBase, ReadSchema):
    """Entity data returned by the application."""


class PageEntityBase(SchemaBase):
    """How strongly one page mentions one entity."""

    entity_id: int
    mention_count: int = Field(default=1, ge=1)
    salience: float | None = Field(default=None, ge=0.0, le=1.0)


class PageEntityCreate(PageEntityBase):
    """Data required to link an entity to a page."""


class PageEntityRead(PageEntityBase, ReadSchema):
    """Page-entity link returned by the application."""

    page_id: int


# --------------------------------------------------------------------- embeddings


class PageEmbeddingBase(SchemaBase):
    """One embedded chunk of a page."""

    model_name: str = Field(min_length=1, max_length=128)
    model_version: str | None = Field(default=None, max_length=64)
    chunk_index: int = Field(ge=0)
    chunk_text: str = Field(min_length=1)
    # The size is the model's (embedding_models.dimensions), checked on save.
    embedding: list[float] = Field(min_length=1, max_length=2000)


class PageEmbeddingCreate(PageEmbeddingBase):
    """Data required to store one embedded chunk."""


class PageEmbeddingRead(PageEmbeddingBase, ReadSchema):
    """Embedded chunk returned by the application."""

    page_id: int
    dimensions: int
    content_hash: str = Field(pattern=SHA256_PATTERN)
    embedded_at: datetime


class PageWithRelations(PageRead):
    """A page together with everything hanging off it except its embeddings."""

    geo_tags: list[PageGeoTagRead] = Field(default_factory=list)
    contacts: list[PageContactRead] = Field(default_factory=list)
    media: list[PageMediaRead] = Field(default_factory=list)
    entities: list[PageEntityRead] = Field(default_factory=list)
    sources: list[PageSourceRead] = Field(default_factory=list)


# --------------------------------------------------------------------- quarantine


class QuarantinedFileRead(ReadSchema):
    """One file ClamAV flagged, as the admin security endpoint returns it."""

    crawled_document_id: int | None = None
    stored_file_id: int | None = None
    domain_id: int | None = None
    document_url: str
    source_page_url: str | None = None
    original_path: str | None = None
    quarantine_path: str
    sha256: str
    size_bytes: int | None = None
    content_type: str | None = None
    threat_signature: str
    scanner_engine: str
    scanner_version: str | None = None
    scanned_at: datetime
    status: QuarantineStatus
    deleted_at: datetime | None = None
    deleted_by: str | None = None


class QuarantineSummary(SchemaBase):
    """The dashboard's `quarantine_store` block."""

    count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    size_mb: int = Field(ge=0)
    latest_threat_detected: str | None = None
    latest_scanned_at: datetime | None = None
