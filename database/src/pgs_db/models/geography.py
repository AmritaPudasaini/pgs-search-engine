"""Reference data: Nepal's 7 provinces, 77 districts and 753 local bodies.

Codes match the search team's GeoLocation model (province_code, district_code,
municipality_id). Boundary shapes (PostGIS) are added in a later migration.
"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, IdMixin, TimestampMixin
from ..enums import LocalBodyType
from ._types import str_enum


class Province(IdMixin, TimestampMixin, Base):
    __tablename__ = "provinces"

    code: Mapped[str] = mapped_column(String(4), unique=True)  # P1..P7
    name_en: Mapped[str] = mapped_column(String(100))
    name_ne: Mapped[str] = mapped_column(String(100))

    districts: Mapped[list["District"]] = relationship(back_populates="province")


class District(IdMixin, TimestampMixin, Base):
    __tablename__ = "districts"

    code: Mapped[str] = mapped_column(String(4), unique=True)  # D01..D77
    province_code: Mapped[str] = mapped_column(ForeignKey("provinces.code"), index=True)
    name_en: Mapped[str] = mapped_column(String(100))
    name_ne: Mapped[str] = mapped_column(String(100))

    province: Mapped[Province] = relationship(back_populates="districts")
    local_bodies: Mapped[list["LocalBody"]] = relationship(back_populates="district")


class LocalBody(IdMixin, TimestampMixin, Base):
    __tablename__ = "local_bodies"

    code: Mapped[str] = mapped_column(String(16), unique=True)  # = search's municipality_id
    district_code: Mapped[str] = mapped_column(ForeignKey("districts.code"), index=True)
    type: Mapped[LocalBodyType] = mapped_column(str_enum(LocalBodyType, "local_body_type"))
    name_en: Mapped[str] = mapped_column(String(150))
    name_ne: Mapped[str] = mapped_column(String(150))
    website: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))

    district: Mapped[District] = relationship(back_populates="local_bodies")
