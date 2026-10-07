"""Ops tables: admin accounts and the shared error log.

Neither belongs to a data layer. `admin_users` is the API's login store;
`error_logs` is where every service (scraper, ETL, security scan, search, API)
records failures an admin should see, read by `GET /api/v1/admin/logs/errors`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, IdMixin, TimestampMixin
from ..enums import AdminRole, LogSeverity, ServiceName
from ._types import str_enum
from .domain import Domain


class AdminUser(IdMixin, TimestampMixin, Base):
    """One admin account for the API's JWT login.

    The API hashes the password (argon2 or bcrypt) and stores only the hash;
    plaintext never reaches the database. Accounts are deactivated, not deleted,
    so audit columns that name an admin (e.g. `quarantined_files.deleted_by`)
    stay meaningful.
    """

    __tablename__ = "admin_users"
    __table_args__ = (
        # Stored lowercase, so the plain unique indexes are case-insensitive.
        CheckConstraint("username = lower(username)", name="username_lowercase"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        # Login takes a username or an email; "@" is what tells them apart.
        CheckConstraint("position('@' in username) = 0", name="username_no_at"),
        CheckConstraint("length(password_hash) > 0", name="password_hash_not_empty"),
    )

    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[AdminRole] = mapped_column(str_enum(AdminRole, "admin_role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ErrorLog(IdMixin, TimestampMixin, Base):
    """A failure one service reports for the admin dashboard.

    Append-only. The optional ids point at what failed; they are SET NULL when
    Bronze or Silver retention deletes the row, so the log outlives its subject.
    """

    __tablename__ = "error_logs"
    __table_args__ = (
        # The API's filter: service and severity, newest first.
        Index("ix_error_logs_service_severity_occurred_at", "service", "severity", "occurred_at"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    service: Mapped[ServiceName] = mapped_column(str_enum(ServiceName, "service_name"))
    # Which replica or worker, e.g. "Scraper-Go-Worker-12".
    instance: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[LogSeverity] = mapped_column(str_enum(LogSeverity, "log_severity"))
    # Short machine-readable kind, e.g. "HTTP_503" or "TimeoutError".
    error_type: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # stack trace, request ids, ...

    domain_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="SET NULL"), index=True
    )
    crawl_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("crawl_runs.id", ondelete="SET NULL"), index=True
    )
    crawled_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("crawled_documents.id", ondelete="SET NULL"), index=True
    )
    page_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pages.id", ondelete="SET NULL"), index=True
    )

    domain: Mapped[Domain | None] = relationship()
