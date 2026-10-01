"""Admin reads and actions on `quarantined_files` (the API's security endpoints).

The ETL writes this table through `SilverRepository.quarantine`; this module is what
`GET /api/v1/admin/security/quarantine` and the dashboard's `quarantine_store` block
(count, size_mb, latest_threat_detected) read from.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import QuarantineStatus
from ..models import QuarantinedFile


class QuarantineRepository:
    """Quarantine lookups and the admin delete action for one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_quarantined(
        self,
        *,
        status: QuarantineStatus | None = QuarantineStatus.QUARANTINED,
        domain_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QuarantinedFile], int]:
        """One page of records, newest scan first, plus the total matching count.

        `status=None` lists every record, deleted ones included (the audit view).
        """
        stmt = select(QuarantinedFile)
        if status is not None:
            stmt = stmt.where(QuarantinedFile.status == status)
        if domain_id is not None:
            stmt = stmt.where(QuarantinedFile.domain_id == domain_id)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.order_by(QuarantinedFile.scanned_at.desc(), QuarantinedFile.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), int(total)

    def summary(self) -> dict[str, Any]:
        """The dashboard's `quarantine_store` block, over files still in quarantine.

        `size_mb` counts only files whose size is known (stored files; a crawled
        page's size is not recorded).
        """
        active = QuarantinedFile.status == QuarantineStatus.QUARANTINED
        count, size = self.session.execute(
            select(func.count(), func.coalesce(func.sum(QuarantinedFile.size_bytes), 0)).where(
                active
            )
        ).one()
        latest = self.session.execute(
            select(QuarantinedFile.threat_signature, QuarantinedFile.scanned_at)
            .where(active)
            .order_by(QuarantinedFile.scanned_at.desc(), QuarantinedFile.id.desc())
            .limit(1)
        ).one_or_none()
        return {
            "count": int(count),
            "size_bytes": int(size),
            "size_mb": round(int(size) / (1024 * 1024)),
            "latest_threat_detected": latest[0] if latest else None,
            "latest_scanned_at": latest[1] if latest else None,
        }

    def mark_deleted(
        self, quarantine_id: int, *, deleted_by: str, when: datetime | None = None
    ) -> QuarantinedFile:
        """Record that an admin erased the isolated object. The row stays as the audit trail.

        Erase the object from the quarantine bucket first; this only records it.
        """
        if not deleted_by.strip():
            raise ValueError("deleted_by must name the admin")
        record = self.session.get(QuarantinedFile, quarantine_id)
        if record is None:
            raise LookupError(f"quarantined file {quarantine_id} does not exist")
        if record.status == QuarantineStatus.DELETED:
            raise ValueError(f"quarantined file {quarantine_id} is already deleted")
        record.status = QuarantineStatus.DELETED
        record.deleted_at = when or datetime.now(UTC)
        record.deleted_by = deleted_by.strip()
        return record
