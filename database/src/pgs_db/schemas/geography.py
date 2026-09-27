"""Pydantic schemas for Nepal's geographic reference data."""

from pydantic import Field

from pgs_db.enums import LocalBodyType

from .base import ReadSchema, SchemaBase


class ProvinceBase(SchemaBase):
    """Fields shared by all province schemas."""

    code: str = Field(
        pattern=r"^P[1-7]$",
        description="Province code from P1 through P7",
    )
    name_en: str = Field(
        min_length=1,
        max_length=100,
        description="Province name in English",
    )
    name_ne: str = Field(
        min_length=1,
        max_length=100,
        description="Province name in Nepali",
    )


class ProvinceCreate(ProvinceBase):
    """Data required when creating a province."""


class ProvinceUpdate(SchemaBase):
    """Fields that may be changed for an existing province."""

    name_en: str | None = Field(default=None, min_length=1, max_length=100)
    name_ne: str | None = Field(default=None, min_length=1, max_length=100)


class ProvinceRead(ProvinceBase, ReadSchema):
    """Province data returned by the application."""


class DistrictBase(SchemaBase):
    """Fields shared by all district schemas."""

    code: str = Field(
        pattern=r"^D(?:0[1-9]|[1-6][0-9]|7[0-7])$",
        description="District code from D01 through D77",
    )

    province_code: str = Field(
        pattern=r"^P[1-7]$",
        description="Code of the province containing the district",
    )
    name_en: str = Field(
        min_length=1,
        max_length=100,
        description="District name in English",
    )
    name_ne: str = Field(
        min_length=1,
        max_length=100,
        description="District name in Nepali",
    )


class DistrictCreate(DistrictBase):
    """Data required when creating a district."""


class DistrictUpdate(SchemaBase):
    """Fields that may be changed for an existing district."""

    province_code: str | None = Field(
        default=None,
        pattern=r"^P[1-7]$",
    )
    name_en: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    name_ne: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )


class DistrictRead(DistrictBase, ReadSchema):
    """District data returned by the application."""

    class LocalBodyBase(SchemaBase):
    """Fields shared by all local-body schemas."""

    code: str = Field(
        min_length=1,
        max_length=16,
        description="Unique code assigned to the local body",
    )
    district_code: str = Field(
        pattern=r"^D(?:0[1-9]|[1-6][0-9]|7[0-7])$",
        description="Code of the district containing the local body",
    )
    type: LocalBodyType
    name_en: str = Field(min_length=1, max_length=150)
    name_ne: str = Field(min_length=1, max_length=150)
    website: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)


class LocalBodyCreate(LocalBodyBase):
    """Data required when creating a local body."""


class LocalBodyUpdate(SchemaBase):
    """Fields that may be changed for an existing local body."""

    district_code: str | None = Field(
        default=None,
        pattern=r"^D(?:0[1-9]|[1-6][0-9]|7[0-7])$",
    )
    type: LocalBodyType | None = None
    name_en: str | None = Field(default=None, min_length=1, max_length=150)
    name_ne: str | None = Field(default=None, min_length=1, max_length=150)
    website: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)


class LocalBodyRead(LocalBodyBase, ReadSchema):
    """Local-body data returned by the application."""