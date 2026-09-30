"""Reference data: Nepal's 7 provinces, 77 districts and 753 local bodies, plus the
curated links shown on each region's card.

Codes match the search team's GeoLocation model (province_code, district_code,
municipality_id).

`boundary` is each region's shape (PostGIS MultiPolygon, WGS 84), loaded by
`scripts/seed_boundaries.py` from Open Knowledge Nepal's CC BY 4.0 data. NULL until
seeded; see `data/boundaries/ATTRIBUTION.md`.
"""

from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, IdMixin, TimestampMixin
from ..enums import LocalBodyType
from ._types import str_enum


def boundary_column() -> Any:
    """A region's shape. The GiST index is declared per table, so it gets a stable name.

    Deferred: a local body's polygon is tens of KB, and every other query on these
    tables (gazetteer, hierarchy, regional card) must not drag it along.
    """
    return mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=True, deferred=True
    )


class Province(IdMixin, TimestampMixin, Base):
    __tablename__ = "provinces"
    __table_args__ = (Index("ix_provinces_boundary", "boundary", postgresql_using="gist"),)

    code: Mapped[str] = mapped_column(String(4), unique=True)  # P1..P7
    name_en: Mapped[str] = mapped_column(String(100))
    name_ne: Mapped[str] = mapped_column(String(100))
    boundary: Mapped[Any] = boundary_column()

    districts: Mapped[list["District"]] = relationship(back_populates="province")


class District(IdMixin, TimestampMixin, Base):
    __tablename__ = "districts"
    __table_args__ = (Index("ix_districts_boundary", "boundary", postgresql_using="gist"),)

    code: Mapped[str] = mapped_column(String(4), unique=True)  # D01..D77
    province_code: Mapped[str] = mapped_column(ForeignKey("provinces.code"), index=True)
    name_en: Mapped[str] = mapped_column(String(100))
    name_ne: Mapped[str] = mapped_column(String(100))
    boundary: Mapped[Any] = boundary_column()

    province: Mapped[Province] = relationship(back_populates="districts")
    local_bodies: Mapped[list["LocalBody"]] = relationship(back_populates="district")


class LocalBody(IdMixin, TimestampMixin, Base):
    __tablename__ = "local_bodies"
    __table_args__ = (
        Index("ix_local_bodies_boundary", "boundary", postgresql_using="gist"),
        CheckConstraint("ward_count IS NULL OR ward_count > 0", name="ward_count_positive"),
    )

    code: Mapped[str] = mapped_column(String(16), unique=True)  # = search's municipality_id
    district_code: Mapped[str] = mapped_column(ForeignKey("districts.code"), index=True)
    type: Mapped[LocalBodyType] = mapped_column(str_enum(LocalBodyType, "local_body_type"))
    name_en: Mapped[str] = mapped_column(String(150))
    name_ne: Mapped[str] = mapped_column(String(150))
    website: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    # Wards in the local body (from the gazetteer); bounds page_geo_tags.ward_number.
    ward_count: Mapped[int | None] = mapped_column(Integer)
    boundary: Mapped[Any] = boundary_column()

    district: Mapped[District] = relationship(back_populates="local_bodies")


class RegionLink(IdMixin, TimestampMixin, Base):
    """A curated link shown on a region's card in search (the API's `quick_links`).

    Belongs to exactly one province, district or local body. A local body's card
    also shows its district's links (e.g. the District Administration Office), so
    district-level offices are entered once, on the district.
    """

    __tablename__ = "region_links"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(province_code, district_code, local_body_code) = 1",
            name="exactly_one_region",
        ),
        CheckConstraint("url ~* '^https?://'", name="url_http"),
        UniqueConstraint(
            "province_code",
            "district_code",
            "local_body_code",
            "url",
            name="uq_region_links_region_url",
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
    title_en: Mapped[str] = mapped_column(String(255))
    title_ne: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    # Display order on the card, lowest first.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
