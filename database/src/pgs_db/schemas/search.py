"""Pydantic schemas for what search and the API read: documents, vector hits, the map
tree, the regional card and its quick links."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from ..enums import LocalBodyType
from .base import ReadSchema, SchemaBase
from .silver import GeoLocationOut

# ---------------------------------------------------------------- documents


class FileInfo(SchemaBase):
    """Set for pages built from a stored file (PDF, DOCX, image, ...)."""

    extension: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class SearchDocumentOut(SchemaBase):
    """One document for the search index.

    A superset of the search team's `pgs_search.models.document.SearchDocument`:
    its fields, plus `category`, `geo_location`, `geo_tags` and `file_info` for
    filtering and the API's result card. `geo` is the primary location.
    """

    document_id: str
    title: str
    description: str | None = None
    searchable_text: str
    source_url: str
    domain: str
    language: str = Field(description="ne | en | mixed | unknown, as pgs_search expects")
    content_type: str
    category: str | None = None
    published_at: datetime | None = None
    keywords: list[str] = Field(default_factory=list)
    geo: GeoLocationOut
    geo_location: GeoLocationOut = Field(
        description="Same as `geo`, under the name search-engine/geo filters on"
    )
    geo_tags: list[GeoLocationOut] = Field(default_factory=list)
    file_info: FileInfo | None = None


class VectorHit(SchemaBase):
    """One result of `SearchRepository.vector_search`."""

    page_id: int
    title: str | None = None
    url: str
    domain: str | None = None
    content_type: str
    province_code: str | None = None
    district_code: str | None = None
    local_body_code: str | None = None
    ward_number: int | None = None
    score: float = Field(description="Cosine similarity of the best chunk, 1 = identical")


# ---------------------------------------------------------------- map tree


class LocalBodyNode(SchemaBase):
    code: str
    name_en: str
    name_ne: str
    type: LocalBodyType


class DistrictNode(SchemaBase):
    code: str
    name_en: str
    name_ne: str
    local_bodies: list[LocalBodyNode]


class ProvinceNode(SchemaBase):
    """One province of `GET /api/v1/user/geo/hierarchy`."""

    code: str
    name_en: str
    name_ne: str
    districts: list[DistrictNode]


# ----------------------------------------------------------- regional card


class RegionLinkCreate(SchemaBase):
    """A quick link an admin adds to a province, district or local body."""

    code: str = Field(min_length=2, max_length=16, description="P4, D38 or MUN414")
    title_en: str = Field(min_length=1, max_length=255)
    title_ne: str | None = Field(default=None, max_length=255)
    url: str = Field(pattern=r"^https?://", description="http(s) only (CHECK)")
    position: int = 0


class RegionLinkRead(ReadSchema):
    province_code: str | None = None
    district_code: str | None = None
    local_body_code: str | None = None
    title_en: str
    title_ne: str | None = None
    url: str
    position: int


class QuickLink(SchemaBase):
    title: str
    title_ne: str | None = None
    url: str


class RegionContact(SchemaBase):
    phone: str | None = None
    email: str | None = None
    address: str | None = None


class RegionRef(SchemaBase):
    code: str
    name_en: str
    name_ne: str


class RegionalCard(SchemaBase):
    """The search response's `regional_card` for the region a search is filtered to."""

    level: Literal["province", "district", "local_body"]
    code: str
    region_name_en: str
    region_name_ne: str
    local_body_type: LocalBodyType | None = None
    official_website: str | None = None
    contact: RegionContact | None = Field(default=None, description="Local bodies only")
    district: RegionRef | None = None
    province: RegionRef | None = None
    quick_links: list[QuickLink] = Field(default_factory=list)
