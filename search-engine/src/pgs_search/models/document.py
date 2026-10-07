from datetime import datetime

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    province_code: str | None = None
    province_name_en: str | None = None
    province_name_ne: str | None = None

    district_code: str | None = None
    district_name_en: str | None = None
    district_name_ne: str | None = None

    municipality_id: str | None = None
    municipality_name_en: str | None = None
    municipality_name_ne: str | None = None

    ward_number: int | None = None


class SearchDocument(BaseModel):
    document_id: str

    title: str
    description: str | None = None
    searchable_text: str

    source_url: str
    domain: str

    language: str = "unknown"
    content_type: str = "web_page"

    published_at: datetime | None = None

    keywords: list[str] = Field(default_factory=list)

    geo: GeoLocation = Field(default_factory=GeoLocation)