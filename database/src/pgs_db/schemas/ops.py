"""Pydantic schemas for the ops tables: admin accounts and the error log."""

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from ..enums import AdminRole, LogSeverity, ServiceName
from .base import ReadSchema, SchemaBase

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


class AdminUserCreate(SchemaBase):
    """A new admin account. The API hashes the password; only the hash comes here."""

    username: str = Field(pattern=USERNAME_PATTERN, description="Stored lowercase")
    email: str | None = Field(default=None, max_length=255)
    password_hash: str = Field(min_length=1, description="argon2 / bcrypt hash, never plaintext")
    role: AdminRole

    @field_validator("username", "email", mode="before")
    @classmethod
    def lowercase(cls, value: str | None) -> str | None:
        return value.strip().lower() if isinstance(value, str) else value


class AdminUserUpdate(SchemaBase):
    """Fields a SUPER_ADMIN may change on another account."""

    role: AdminRole | None = None
    is_active: bool | None = None


class AdminUserRead(ReadSchema):
    """An admin account as the API returns it. The password hash is never included."""

    username: str
    email: str | None = None
    role: AdminRole
    is_active: bool
    last_login_at: datetime | None = None


class ErrorLogCreate(SchemaBase):
    """One failure a service reports. Only service, severity and message are required."""

    service: ServiceName
    severity: LogSeverity
    message: str = Field(min_length=1)
    instance: str | None = Field(default=None, max_length=128)
    error_type: str | None = Field(default=None, max_length=128)
    url: str | None = None
    context: dict[str, Any] | None = None
    domain_id: int | None = None
    crawl_run_id: int | None = None
    crawled_document_id: int | None = None
    page_id: int | None = None
    occurred_at: datetime | None = None


class ErrorLogRead(ReadSchema):
    """One entry of `GET /api/v1/admin/logs/errors`."""

    occurred_at: datetime
    service: ServiceName
    instance: str | None = None
    severity: LogSeverity
    error_type: str | None = None
    message: str
    url: str | None = None
    context: dict[str, Any] | None = None
    domain_id: int | None = None
    crawl_run_id: int | None = None
    crawled_document_id: int | None = None
    page_id: int | None = None
