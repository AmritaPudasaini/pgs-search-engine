"""End-to-end Phase 1 integration tests.

Walks the real path a crawl takes -- domain -> crawl_run -> crawled_document ->
stored_file -> crawl completion -- then covers retries, failures, constraint
enforcement and rollback.

These use the same rolled-back-transaction fixture as the rest of the suite, so
they leave no rows behind.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository
from pgs_db.enums import CrawlRunStatus, DomainCategory, ProcessingStatus
from pgs_db.models import CrawledDocument, CrawlRun, Domain, StoredFile
from pgs_db.schemas import CrawledDocumentRead, CrawlRunRead, DomainRead, StoredFileRead

HOST = "pokharamun.gov.np"
STARTED = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
FETCHED = datetime(2026, 9, 23, 5, 5, tzinfo=UTC)
FINISHED = datetime(2026, 9, 23, 5, 30, tzinfo=UTC)


@pytest.fixture()
def repo(session: Session) -> BronzeRepository:
    return BronzeRepository(session)


def page(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "url": f"https://{HOST}/notice/456?utm_source=fb",
        "normalized_url": f"https://{HOST}/notice/456",
        "host": HOST,
        "title": "स्थानीय शासन सूचना",
        "text": "सूचना विवरण",
        "content_hash": "a" * 64,
        "content_type": "text/html",
        "fetched_at": "2026-09-23T05:05:00Z",
        "status_code": 200,
        "depth": 3,
        "links": [f"https://{HOST}/a"],
        "anchor_texts": ["A"],
        "contact_info": {"emails": ["info@pokharamun.gov.np"], "phones": ["+977-61-521105"]},
        "geo": {"lat": 28.2096, "lng": 83.9856},
        "country": "NP",
    }
    doc.update(overrides)
    return doc


def pdf(**overrides: Any) -> dict[str, Any]:
    stored: dict[str, Any] = {
        "source_page_url": f"https://{HOST}/notice/456",
        "document_url": f"https://{HOST}/files/notice-456.pdf",
        "storage_path": "raw/documents/pokharamun.gov.np/notice-456.pdf",
        "content_type": "application/pdf",
        "sha256": "b" * 64,
        "size": 51200,
        "stored_at": "2026-09-23T05:05:10Z",
    }
    stored.update(overrides)
    return stored


class TestFullCrawlLifecycle:
    def test_domain_to_crawl_completion(self, repo: BronzeRepository) -> None:
        session = repo.session

        # 1. domain -------------------------------------------------------------
        domain_id = repo.ensure_domain(
            HOST, category=DomainCategory.GOVERNMENT, website_name="Pokhara Metropolitan City"
        )
        assert repo.ensure_domain(HOST) == domain_id  # idempotent

        # 2. crawl run ----------------------------------------------------------
        run_id = repo.start_crawl_run(
            category="government", temporal_workflow_id="crawl-gov-001", started_at=STARTED
        )
        run = session.get(CrawlRun, run_id)
        assert run is not None and run.status == CrawlRunStatus.RUNNING

        # 3. crawled document ---------------------------------------------------
        doc_result = repo.save_document(page(), crawl_run_id=run_id)
        assert doc_result.inserted
        document = session.get(CrawledDocument, doc_result.id)
        assert document is not None
        assert document.crawl_run_id == run_id
        assert document.domain_id == domain_id
        assert document.fetched_at == FETCHED
        assert document.processing_status == ProcessingStatus.UNPROCESSED

        # 4. stored file --------------------------------------------------------
        file_result = repo.save_stored_file(pdf(), crawled_document_id=doc_result.id)
        assert file_result.inserted
        stored = session.get(StoredFile, file_result.id)
        assert stored is not None and stored.crawled_document_id == doc_result.id

        # 5. counters + completion ---------------------------------------------
        repo.update_crawl_run_stats(
            run_id, {"fetched": 1, "succeeded": 1, "failed": 0, "skipped": 0, "unique_urls": 1}
        )
        repo.touch_domain_crawled(domain_id, when=FINISHED)
        repo.finish_crawl_run(
            run_id,
            stats={"fetched": 1, "succeeded": 1, "failed": 0, "skipped": 0, "unique_urls": 1},
            finished_at=FINISHED,
        )
        session.flush()
        session.refresh(run)

        assert run.status == CrawlRunStatus.COMPLETED
        assert run.finished_at == FINISHED
        assert run.succeeded_count == 1

        # the whole chain is navigable in both directions
        assert stored.crawled_document.crawl_run.id == run_id
        domain = session.get(Domain, domain_id)
        assert domain is not None and domain.last_crawled_at == FINISHED

    def test_all_timestamps_are_utc(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run(started_at=STARTED)
        doc = repo.save_document(page(), crawl_run_id=run_id)
        repo.finish_crawl_run(run_id, finished_at=FINISHED)
        repo.session.flush()

        run = repo.session.get(CrawlRun, run_id)
        document = repo.session.get(CrawledDocument, doc.id)
        assert run is not None and document is not None
        for value in (run.started_at, run.finished_at, document.fetched_at, document.created_at):
            assert value is not None
            assert value.utcoffset() == UTC.utcoffset(None)

    def test_rows_validate_against_the_phase1_schemas(self, repo: BronzeRepository) -> None:
        domain_id = repo.ensure_domain(HOST)
        run_id = repo.start_crawl_run(started_at=STARTED)
        doc = repo.save_document(page(), crawl_run_id=run_id)
        stored = repo.save_stored_file(pdf(), crawled_document_id=doc.id)
        repo.finish_crawl_run(run_id, finished_at=FINISHED)
        repo.session.flush()

        # from_attributes=True, so ORM rows validate directly.
        assert DomainRead.model_validate(repo.session.get(Domain, domain_id)).domain == HOST
        assert CrawlRunRead.model_validate(repo.session.get(CrawlRun, run_id)).status == (
            CrawlRunStatus.COMPLETED
        )
        page_read = CrawledDocumentRead.model_validate(repo.session.get(CrawledDocument, doc.id))
        assert page_read.country == "NP"
        assert StoredFileRead.model_validate(
            repo.session.get(StoredFile, stored.id)
        ).size_bytes == 51200


class TestRetriesAndIdempotency:
    def test_replaying_a_whole_crawl_creates_no_duplicates(self, repo: BronzeRepository) -> None:
        """A Temporal activity that retries must not double-write."""
        run_id = repo.start_crawl_run(started_at=STARTED)
        for _ in range(3):
            doc = repo.save_document(page(), crawl_run_id=run_id)
            repo.save_stored_file(pdf(), crawled_document_id=doc.id)
        repo.session.flush()

        assert repo.session.scalar(select(func.count()).select_from(CrawledDocument)) == 1
        assert repo.session.scalar(select(func.count()).select_from(StoredFile)) == 1

    def test_retry_reports_duplicate_not_insert(self, repo: BronzeRepository) -> None:
        first = repo.save_document(page())
        retry = repo.save_document(page())
        assert first.inserted
        assert retry.duplicate and retry.id == first.id

    def test_recrawl_with_changed_content_is_a_new_version(self, repo: BronzeRepository) -> None:
        old = repo.save_document(page(content_hash="a" * 64))
        new = repo.save_document(page(content_hash="c" * 64))
        assert old.id != new.id
        assert repo.session.scalar(select(func.count()).select_from(CrawledDocument)) == 2

    def test_concurrent_domain_registration_is_safe(self, repo: BronzeRepository) -> None:
        # Two workers meeting the same host must not create two rows.
        assert repo.ensure_domain(HOST) == repo.ensure_domain(HOST.upper())
        assert repo.session.scalar(select(func.count()).select_from(Domain)) == 1


class TestConstraintsAndFailures:
    def test_document_with_unknown_crawl_run_violates_fk(self, repo: BronzeRepository) -> None:
        with pytest.raises(IntegrityError):
            repo.save_document(page(), crawl_run_id=9_999_999)
            repo.session.flush()

    def test_duplicate_domain_is_rejected_by_the_unique_constraint(
        self, repo: BronzeRepository
    ) -> None:
        repo.session.add_all([Domain(domain=HOST), Domain(domain=HOST)])
        with pytest.raises(IntegrityError):
            repo.session.flush()

    def test_invalid_status_is_rejected_by_sqlalchemy(self, repo: BronzeRepository) -> None:
        """The ORM layer rejects a bad status before it ever reaches Postgres."""
        run_id = repo.start_crawl_run()
        repo.session.flush()
        run = repo.session.get(CrawlRun, run_id)
        assert run is not None
        run.status = "NOT_A_STATUS"  # type: ignore[assignment]
        with pytest.raises(StatementError, match="not among the defined enum values"):
            repo.session.flush()

    def test_invalid_status_is_rejected_by_the_check_constraint(
        self, repo: BronzeRepository
    ) -> None:
        """Raw SQL bypasses the ORM, so the CHECK constraint is what protects
        the Go scraper and Spark. This is the guarantee they rely on."""
        with pytest.raises(IntegrityError):
            repo.session.execute(
                text(
                    "INSERT INTO crawl_runs (status, started_at, fetched_count, succeeded_count,"
                    " failed_count, skipped_count, unique_url_count)"
                    " VALUES ('NOT_A_STATUS', now(), 0, 0, 0, 0, 0)"
                )
            )

    def test_rate_limit_must_be_positive(self, repo: BronzeRepository) -> None:
        repo.session.add(Domain(domain="bad.gov.np", rate_limit_per_sec=0))
        with pytest.raises(IntegrityError):
            repo.session.flush()

    def test_errors_are_raised_not_swallowed(self, repo: BronzeRepository) -> None:
        """A malformed document must surface, not vanish."""
        with pytest.raises(ValueError, match="normalized_url"):
            repo.save_document(page(normalized_url=""))

    def test_failed_crawl_is_closed_as_failed(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run(started_at=STARTED)
        repo.save_document(page(status_code=503, error="503 Service Unavailable"))
        repo.finish_crawl_run(
            run_id,
            status=CrawlRunStatus.FAILED,
            stats={"fetched": 1, "succeeded": 0, "failed": 1, "skipped": 0, "unique_urls": 1},
            finished_at=FINISHED,
        )
        repo.session.flush()
        run = repo.session.get(CrawlRun, run_id)
        assert run is not None
        assert run.status == CrawlRunStatus.FAILED
        assert run.failed_count == 1
        assert run.finished_at is not None  # never left dangling in RUNNING


class TestRollback:
    def test_failed_write_rolls_back_the_whole_unit_of_work(self, session: Session) -> None:
        """A page and its files are one unit: a bad file must undo the page too."""
        repo = BronzeRepository(session)
        savepoint = session.begin_nested()
        doc = repo.save_document(page())
        with pytest.raises(ValueError):
            repo.save_stored_file(pdf(sha256=""))  # invalid: rejected before SQL
        savepoint.rollback()

        assert session.get(CrawledDocument, doc.id) is None
        assert session.scalar(select(func.count()).select_from(CrawledDocument)) == 0

    def test_integrity_error_rolls_back_cleanly_and_session_recovers(
        self, session: Session
    ) -> None:
        repo = BronzeRepository(session)
        savepoint = session.begin_nested()
        with pytest.raises(IntegrityError):
            repo.save_document(page(), crawl_run_id=9_999_999)
            session.flush()
        savepoint.rollback()

        # The session is usable again after the rollback.
        run_id = repo.start_crawl_run(started_at=STARTED)
        result = repo.save_document(page(), crawl_run_id=run_id)
        session.flush()
        assert result.inserted
        assert session.scalar(select(func.count()).select_from(CrawledDocument)) == 1

    def test_partial_crawl_leaves_no_orphan_file(self, session: Session) -> None:
        repo = BronzeRepository(session)
        savepoint = session.begin_nested()
        doc = repo.save_document(page())
        repo.save_stored_file(pdf(), crawled_document_id=doc.id)
        savepoint.rollback()

        assert session.scalar(select(func.count()).select_from(StoredFile)) == 0
        assert session.scalar(select(func.count()).select_from(CrawledDocument)) == 0
