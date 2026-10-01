"""Websites the scraper crawls."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, IdMixin, TimestampMixin
from ..enums import DomainCategory, DomainPriority, DomainStatus
from ._types import str_enum


class Domain(IdMixin, TimestampMixin, Base):
    __tablename__ = "domains"
    __table_args__ = (CheckConstraint("rate_limit_per_sec > 0", name="rate_limit_positive"),)

    domain: Mapped[str] = mapped_column(String(255), unique=True)  # matches Document.host
    website_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[DomainCategory] = mapped_column(
        str_enum(DomainCategory, "domain_category"), default=DomainCategory.OTHER
    )
    status: Mapped[DomainStatus] = mapped_column(
        str_enum(DomainStatus, "domain_status"), default=DomainStatus.PENDING, index=True
    )
    priority: Mapped[DomainPriority] = mapped_column(
        str_enum(DomainPriority, "domain_priority"), default=DomainPriority.NORMAL
    )
    rate_limit_per_sec: Mapped[int] = mapped_column(Integer, default=1)
    # Set for a municipality's own site (e.g. pokharamun.gov.np -> Pokhara).
    local_body_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("local_bodies.id"), index=True
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
