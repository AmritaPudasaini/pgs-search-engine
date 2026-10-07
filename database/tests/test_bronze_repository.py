"""Repository tests covering the scraper's full crawl lifecycle.

Fixtures build payloads in the exact shape the Go scraper marshals, including its
quirks: `omitempty` blanks, crawl_run_id 0, uint64 simhash, nested contact_info.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository
from pgs_db.enums import CrawlRunStatus, ProcessingStatus
from pgs_db.models import CrawledDocument, CrawlRun, Domain, StoredFile
from pgs_db.repositories import signed_simhash, unsigned_simhash

NOW = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)
HOST = "mofaga.gov.np"


@pytest.fixture()
def repo(session: Session) -> BronzeRepository:
    return BronzeRepository(session)


def scraper_document(**overrides: Any) -> dict[str, Any]:
    """A Document exactly as the Go crawler marshals it."""
    doc: dict[str, Any] = {
        "url": f"https://{HOST}/notice/1?utm_source=fb",
        "normalized_url": f"https://{HOST}/notice/1",
        "host": HOST,
        "title": "सूचना",
        "text": "सूचना विवरण",
        "content_hash": "a" * 64,
        "content_type": "text/html; charset=utf-8",
        "fetched_at": "2026-09-23T06:00:00Z",
        "status_code": 200,
        "depth": 2,
        "fetch_duration_ms": 431,
        "links": [f"https://{HOST}/a", f"https://{HOST}/b"],
        "anchor_texts": ["A", "B"],
        "meta_keywords": ["notice", "सूचना"],
        "headings": [{"level": 1, "text": "सूचना"}],
        "open_graph": {"og:title": "Notice"},
        "contact_info": {"emails": ["info@mofaga.gov.np"], "phones": ["+977-1-4200000"]},
        "geo": {"lat": 27.7172, "lng": 85.3240},
        "country": "NP",
    }
    doc.update(overrides)
    return doc


def scraper_stored_document(**overrides: Any) -> dict[str, Any]:
    stored: dict[str, Any] = {
        "source_page_url": f"https://{HOST}/notice/1",
        "document_url": f"https://{HOST}/files/notice.pdf",
        "storage_path": "raw/documents/mofaga.gov.np/notice.pdf",
        "content_type": "application/pdf",
        "sha256": "b" * 64,
        "size": 20481,
        "stored_at": "2026-09-23T06:00:05Z",
    }
    stored.update(overrides)
    return stored


class TestConnection:
    def test_database_is_reachable(self, session: Session) -> None:
        assert session.scalar(text("select 1")) == 1

    def test_bronze_tables_exist(self, session: Session) -> None:
        for table in ("crawl_runs", "crawled_documents", "stored_files", "domains"):
            assert session.scalar(text(f"select to_regclass('public.{table}')")) == table


class TestCrawlLifecycle:
    def test_start_crawl_run_opens_a_running_row(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run(category="government", temporal_workflow_id="wf-1")
        run = repo.session.get(CrawlRun, run_id)
        assert run is not None
        assert run.status == CrawlRunStatus.RUNNING
        assert run.finished_at is None
        assert run.fetched_count == 0  # NOT NULL with no server default

    def test_stats_update_then_finish(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run(started_at=NOW)
        repo.update_crawl_run_stats(
            run_id, {"fetched": 10, "succeeded": 8, "failed": 1, "skipped": 1, "unique_urls": 9}
        )
        repo.session.flush()
        run = repo.session.get(CrawlRun, run_id)
        assert run is not None and run.fetched_count == 10 and run.succeeded_count == 8

        repo.finish_crawl_run(
            run_id,
            stats={"fetched": 12, "succeeded": 10, "failed": 1, "skipped": 1, "unique_urls": 11},
            finished_at=NOW,
        )
        repo.session.flush()
        repo.session.refresh(run)
        assert run.status == CrawlRunStatus.COMPLETED
        assert run.finished_at == NOW
        assert run.fetched_count == 12

    def test_failed_crawl_is_recorded_not_lost(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run()
        repo.finish_crawl_run(run_id, status=CrawlRunStatus.FAILED)
        repo.session.flush()
        run = repo.session.get(CrawlRun, run_id)
        assert run is not None
        assert run.status == CrawlRunStatus.FAILED
        assert run.finished_at is not None

    def test_unknown_run_id_raises(self, repo: BronzeRepository) -> None:
        with pytest.raises(LookupError):
            repo.finish_crawl_run(9_999_999)


class TestDocumentInsertion:
    def test_document_round_trips_every_field_group(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run()
        result = repo.save_document(scraper_document(), crawl_run_id=run_id)
        assert result.inserted

        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.crawl_run_id == run_id
        assert doc.title == "सूचना"
        assert doc.meta_keywords == ["notice", "सूचना"]
        assert doc.headings == [{"level": 1, "text": "सूचना"}]
        assert doc.open_graph == {"og:title": "Notice"}
        assert doc.emails == ["info@mofaga.gov.np"]  # flattened from contact_info
        assert doc.phones == ["+977-1-4200000"]
        assert doc.geo_lat == pytest.approx(27.7172)  # flattened from geo pointer
        assert doc.depth == 2
        assert doc.fetched_at == NOW
        assert doc.processing_status == ProcessingStatus.UNPROCESSED

    def test_omitempty_blanks_become_null(self, repo: BronzeRepository) -> None:
        # Go emits "" for an absent optional string; "" would be a bogus column value.
        result = repo.save_document(
            scraper_document(final_url="", canonical_url="", error="", country="")
        )
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.final_url is None
        assert doc.canonical_url is None
        assert doc.error is None
        assert doc.country is None

    def test_crawl_run_id_zero_becomes_null(self, repo: BronzeRepository) -> None:
        # 0 means "no run-tracking backend"; inserting it would violate the FK.
        result = repo.save_document(scraper_document(crawl_run_id=0))
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.crawl_run_id is None

    def test_uint64_simhash_round_trips(self, repo: BronzeRepository) -> None:
        simhash = 0xFEDC_BA98_7654_3210  # above int64 max
        result = repo.save_document(scraper_document(sim_hash=simhash))
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.sim_hash is not None
        assert doc.sim_hash < 0  # wrapped to two's-complement, as Go's int64(v) does
        assert doc.sim_hash == signed_simhash(simhash)
        assert unsigned_simhash(doc.sim_hash) == simhash

    def test_missing_required_field_is_rejected_before_sql(
        self, repo: BronzeRepository
    ) -> None:
        doc = scraper_document()
        del doc["content_hash"]
        with pytest.raises(ValueError, match="content_hash"):
            repo.save_document(doc)

    def test_stored_file_links_to_its_document(self, repo: BronzeRepository) -> None:
        doc = repo.save_document(scraper_document())
        stored = repo.save_stored_file(scraper_stored_document(), crawled_document_id=doc.id)
        assert stored.inserted

        row = repo.session.get(StoredFile, stored.id)
        assert row is not None
        assert row.crawled_document_id == doc.id
        assert row.size_bytes == 20481  # `size` in Go -> size_bytes in the column
        assert row.processing_status == ProcessingStatus.UNPROCESSED


class TestDuplicateHandling:
    def test_same_url_and_content_updates_instead_of_failing(
        self, repo: BronzeRepository
    ) -> None:
        first = repo.save_document(scraper_document(title="old"))
        second = repo.save_document(scraper_document(title="new"))
        assert first.inserted
        assert second.duplicate
        assert second.id == first.id

        doc = repo.session.get(CrawledDocument, first.id)
        assert doc is not None
        repo.session.refresh(doc)
        assert doc.title == "new"
        assert len(repo.session.scalars(select(CrawledDocument)).all()) == 1

    def test_tracking_params_collapse_to_one_row(self, repo: BronzeRepository) -> None:
        # Two fetched URLs, same normalized_url and content -> one row.
        repo.save_document(scraper_document(url=f"https://{HOST}/notice/1?utm_source=fb"))
        second = repo.save_document(scraper_document(url=f"https://{HOST}/notice/1?ref=x"))
        assert second.duplicate
        assert len(repo.session.scalars(select(CrawledDocument)).all()) == 1

    def test_changed_content_creates_a_new_version(self, repo: BronzeRepository) -> None:
        first = repo.save_document(scraper_document(content_hash="a" * 64))
        second = repo.save_document(scraper_document(content_hash="c" * 64))
        assert first.inserted and second.inserted
        assert first.id != second.id
        assert len(repo.session.scalars(select(CrawledDocument)).all()) == 2

    def test_duplicate_stored_file_is_idempotent(self, repo: BronzeRepository) -> None:
        first = repo.save_stored_file(scraper_stored_document())
        second = repo.save_stored_file(scraper_stored_document(storage_path="raw/moved.pdf"))
        assert first.inserted and second.duplicate and first.id == second.id
        row = repo.session.get(StoredFile, first.id)
        assert row is not None
        repo.session.refresh(row)
        assert row.storage_path == "raw/moved.pdf"


class TestDomainLookup:
    def test_known_host_resolves_to_domain_id(self, repo: BronzeRepository) -> None:
        domain = Domain(domain=HOST)
        repo.session.add(domain)
        repo.session.flush()

        result = repo.save_document(scraper_document())
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.domain_id == domain.id

    def test_unknown_host_stores_with_null_domain(self, repo: BronzeRepository) -> None:
        # Following a link off-site must not lose the page.
        result = repo.save_document(scraper_document(host="unseeded.example.np"))
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.domain_id is None

    def test_register_unknown_domains_creates_the_row(self, repo: BronzeRepository) -> None:
        result = repo.save_document(
            scraper_document(host="new.gov.np"), register_unknown_domains=True
        )
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.domain_id is not None
        assert repo.domain_id_for_host("new.gov.np") == doc.domain_id

    def test_ensure_domain_is_idempotent_and_case_insensitive(
        self, repo: BronzeRepository
    ) -> None:
        first = repo.ensure_domain(HOST)
        assert repo.ensure_domain(HOST.upper()) == first

    def test_touch_domain_records_last_crawl(self, repo: BronzeRepository) -> None:
        domain_id = repo.ensure_domain(HOST)
        repo.touch_domain_crawled(domain_id, when=NOW)
        repo.session.flush()
        domain = repo.session.get(Domain, domain_id)
        assert domain is not None
        assert domain.last_crawled_at == NOW


class TestFreshness:
    def test_is_known_detects_unchanged_content(self, repo: BronzeRepository) -> None:
        url = f"https://{HOST}/notice/1"
        assert not repo.is_known(url, "a" * 64)
        repo.save_document(scraper_document())
        assert repo.is_known(url, "a" * 64)
        assert not repo.is_known(url, "c" * 64)  # content changed -> refetch

    def test_last_fetched_at_returns_newest(self, repo: BronzeRepository) -> None:
        url = f"https://{HOST}/notice/1"
        assert repo.last_fetched_at(url) is None
        repo.save_document(scraper_document(fetched_at="2026-09-20T00:00:00Z"))
        repo.save_document(
            scraper_document(content_hash="c" * 64, fetched_at="2026-09-23T06:00:00Z")
        )
        assert repo.last_fetched_at(url) == NOW


class TestFailureHandling:
    def test_failed_fetch_is_stored_with_its_error(self, repo: BronzeRepository) -> None:
        run_id = repo.start_crawl_run()
        result = repo.save_document(
            scraper_document(
                status_code=503,
                error="fetch: 503 Service Unavailable",
                content_hash="d" * 64,
                text="",
                title="",
            ),
            crawl_run_id=run_id,
        )
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.status_code == 503
        assert doc.error == "fetch: 503 Service Unavailable"
        assert doc.title is None

    def test_invalid_timestamp_is_rejected(self, repo: BronzeRepository) -> None:
        with pytest.raises(ValueError, match="fetched_at"):
            repo.save_document(scraper_document(fetched_at=""))

    def test_naive_timestamp_is_treated_as_utc(self, repo: BronzeRepository) -> None:
        result = repo.save_document(scraper_document(fetched_at="2026-09-23T06:00:00"))
        doc = repo.session.get(CrawledDocument, result.id)
        assert doc is not None
        assert doc.fetched_at == NOW
