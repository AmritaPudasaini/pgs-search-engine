"""The only place that writes the Bronze tables.

Every statement the Go scraper needs lives here, so SQL never has to be scattered
through crawler code. The Go ``PostgresWriter`` issues the same statements -- see
``docs/WRITE_CONTRACT.md``.

Crawl lifecycle::

    run_id = repo.start_crawl_run(category="government")
    repo.save_document(doc, crawl_run_id=run_id)        # per page
    repo.save_stored_file(sf, crawled_document_id=...)  # per PDF/image
    repo.update_crawl_run_stats(run_id, stats)          # periodically
    repo.finish_crawl_run(run_id, stats=stats)          # once, at the end
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..enums import CrawlRunStatus, DomainCategory, DomainPriority, DomainStatus
from ..models import CrawledDocument, CrawlRun, Domain, StoredFile
from ._mapping import crawl_stats_columns, document_row, stored_file_row


@dataclass(frozen=True)
class SaveResult:
    """Outcome of an upsert: the row id, and whether this call created it."""

    id: int
    inserted: bool

    @property
    def duplicate(self) -> bool:
        return not self.inserted


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BronzeRepository:
    """Bronze-layer writes and lookups for one SQLAlchemy session.

    The caller owns the transaction: nothing here commits, so a crawl activity can
    group several writes into one unit of work and roll the whole thing back.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ domains

    def domain_id_for_host(self, host: str | None) -> int | None:
        """Resolve ``Document.host`` to ``domains.id``, or None when the host is unknown.

        Unknown is not an error: the crawler may follow a link off a seeded domain, and
        ``crawled_documents.domain_id`` is nullable precisely so those pages still store.
        """
        if not host:
            return None
        return self.session.scalar(select(Domain.id).where(Domain.domain == host.lower()))

    def ensure_domain(
        self,
        host: str,
        *,
        category: DomainCategory = DomainCategory.OTHER,
        priority: DomainPriority = DomainPriority.NORMAL,
        status: DomainStatus = DomainStatus.PENDING,
        website_name: str | None = None,
    ) -> int:
        """Return ``domains.id`` for ``host``, registering it if not yet known.

        An existing row keeps its admin-set category/priority/status; only the id comes
        back. Use this when the crawler should auto-register the hosts it meets.
        """
        normalized = host.lower()
        inserted_id = self.session.scalar(
            insert(Domain)
            .values(
                domain=normalized,
                website_name=website_name,
                category=category,
                priority=priority,
                status=status,
            )
            .on_conflict_do_nothing(index_elements=[Domain.domain])
            .returning(Domain.id)
        )
        if inserted_id is not None:
            return inserted_id
        # DO NOTHING returns no row when the domain already existed.
        existing = self.domain_id_for_host(normalized)
        if existing is None:  # pragma: no cover - only on a concurrent delete
            raise RuntimeError(f"could not resolve domain {host!r} after upsert")
        return existing

    def touch_domain_crawled(self, domain_id: int, *, when: datetime | None = None) -> None:
        """Record that a crawl just visited this domain."""
        domain = self.session.get(Domain, domain_id)
        if domain is not None:
            domain.last_crawled_at = when or _utcnow()

    # ----------------------------------------------------------- crawl lifecycle

    def start_crawl_run(
        self,
        *,
        category: str | None = None,
        temporal_workflow_id: str | None = None,
        started_at: datetime | None = None,
        seed_count: int | None = None,
        max_depth: int | None = None,
        max_pages: int | None = None,
    ) -> int:
        """Open a crawl run and return its id (the scraper's ``Document.crawl_run_id``).

        `seed_count` / `max_depth` / `max_pages` record the run's configuration, so a
        short run can be told apart from a run that was configured small.
        """
        run = CrawlRun(
            category=category,
            temporal_workflow_id=temporal_workflow_id,
            started_at=started_at or _utcnow(),
            status=CrawlRunStatus.RUNNING,
            seed_count=seed_count,
            max_depth=max_depth,
            max_pages=max_pages,
            **crawl_stats_columns(None),
        )
        self.session.add(run)
        self.session.flush()
        return run.id

    def update_crawl_run_stats(self, run_id: int, stats: Mapping[str, Any]) -> None:
        """Overwrite the run's counters from a ``CrawlStats`` payload."""
        run = self._require_run(run_id)
        for column, value in crawl_stats_columns(stats).items():
            setattr(run, column, value)

    def finish_crawl_run(
        self,
        run_id: int,
        *,
        status: CrawlRunStatus = CrawlRunStatus.COMPLETED,
        stats: Mapping[str, Any] | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Close the run with final counters. Pass status=FAILED and `error` for a crashed crawl."""
        run = self._require_run(run_id)
        if stats is not None:
            for column, value in crawl_stats_columns(stats).items():
                setattr(run, column, value)
        run.status = status
        run.finished_at = finished_at or _utcnow()
        run.error = error or None

    def _require_run(self, run_id: int) -> CrawlRun:
        run = self.session.get(CrawlRun, run_id)
        if run is None:
            raise LookupError(f"crawl run {run_id} does not exist")
        return run

    # ---------------------------------------------------------------- documents

    def save_document(
        self,
        doc: Mapping[str, Any],
        *,
        crawl_run_id: int | None = None,
        minio_path: str | None = None,
        resolve_domain: bool = True,
        register_unknown_domains: bool = False,
    ) -> SaveResult:
        """Upsert one scraper Document, keyed on (normalized_url, content_hash).

        Re-crawling an unchanged page updates the existing row instead of failing or
        duplicating; changed content produces a new row, which is what turns the pair
        into a content-version history. ``SaveResult.duplicate`` tells the two apart.
        """
        domain_id: int | None = None
        if resolve_domain:
            raw_host = doc.get("host")
            host = raw_host if isinstance(raw_host, str) and raw_host.strip() else None
            if host and register_unknown_domains:
                domain_id = self.ensure_domain(host)
            else:
                domain_id = self.domain_id_for_host(host)

        row = document_row(
            doc, crawl_run_id=crawl_run_id, domain_id=domain_id, minio_path=minio_path
        )
        return self._upsert(
            CrawledDocument,
            row,
            conflict=[CrawledDocument.normalized_url, CrawledDocument.content_hash],
            skip_on_update=("normalized_url", "content_hash"),
        )

    def save_stored_file(
        self, stored: Mapping[str, Any], *, crawled_document_id: int | None = None
    ) -> SaveResult:
        """Upsert one MinIO object record, keyed on (document_url, sha256)."""
        row = stored_file_row(stored, crawled_document_id=crawled_document_id)
        return self._upsert(
            StoredFile,
            row,
            conflict=[StoredFile.document_url, StoredFile.sha256],
            skip_on_update=("document_url", "sha256"),
        )

    def _upsert(
        self,
        model: type[CrawledDocument] | type[StoredFile],
        row: dict[str, Any],
        *,
        conflict: list[Any],
        skip_on_update: tuple[str, ...],
    ) -> SaveResult:
        stmt = insert(model).values(row)
        # The conflict target identifies the row; never overwrite it with itself.
        updates = {col: getattr(stmt.excluded, col) for col in row if col not in skip_on_update}
        # xmax is 0 only on a genuine insert, which is how insert and update are told apart.
        result = self.session.execute(
            stmt.on_conflict_do_update(index_elements=conflict, set_=updates).returning(
                model.id, text("(xmax = 0)")
            )
        ).one()
        return SaveResult(id=int(result[0]), inserted=bool(result[1]))

    # --------------------------------------------------------------- freshness

    def is_known(self, normalized_url: str, content_hash: str) -> bool:
        """True when this exact content has already been stored for this URL.

        Backs the scraper's ``FreshnessChecker``: a hit means the fetch can be skipped.
        """
        found = self.session.scalar(
            select(CrawledDocument.id).where(
                CrawledDocument.normalized_url == normalized_url,
                CrawledDocument.content_hash == content_hash,
            )
        )
        return found is not None

    def last_fetched_at(self, normalized_url: str) -> datetime | None:
        """Most recent fetch time for a URL, or None if never crawled.

        Uses the leading column of uq_crawled_documents_normalized_url_content_hash,
        so this needs no extra index.
        """
        return self.session.scalar(
            select(CrawledDocument.fetched_at)
            .where(CrawledDocument.normalized_url == normalized_url)
            .order_by(CrawledDocument.fetched_at.desc())
            .limit(1)
        )
