"""domain_stats (Gold) and the admin dashboard reads built on Bronze, Silver and ops."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository, OpsRepository, SilverRepository, StatsRepository
from pgs_db.enums import DomainPriority, DomainStatus, LogSeverity, ServiceName
from pgs_db.models import Domain, DomainStats
from pgs_db.schemas import DashboardSummary, DomainOverview, DomainStatsRead

HOST = "statsite.gov.np"
_ANCIENT = datetime(1975, 1, 1, tzinfo=UTC)


@pytest.fixture()
def bronze(session: Session) -> BronzeRepository:
    return BronzeRepository(session)


@pytest.fixture()
def stats(session: Session) -> StatsRepository:
    return StatsRepository(session)


def fetch(
    bronze: BronzeRepository,
    path: str,
    n: int,
    *,
    host: str = HOST,
    links: list[str] | None = None,
    **overrides: Any,
) -> int:
    """Save one fetch of https://host/path as content version n."""
    url = f"https://{host}/{path}"
    doc: dict[str, Any] = {
        "url": url,
        "normalized_url": url,
        "host": host,
        "content_hash": f"{n:064x}",
        "fetched_at": (_ANCIENT + timedelta(days=n)).isoformat(),
        "status_code": 200,
        "internal_links": links or [],
    }
    doc.update(overrides)
    return bronze.save_document(doc, register_unknown_domains=True).id


def row_for(stats: StatsRepository, domain_id: int) -> DomainStats:
    row = stats.session.scalar(select(DomainStats).where(DomainStats.domain_id == domain_id))
    assert row is not None
    return row


class TestRefresh:
    def test_counts_follow_each_urls_latest_fetch(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        a = f"https://{HOST}/a"
        b = f"https://{HOST}/b"
        c = f"https://{HOST}/c"
        fetch(bronze, "a", 1, links=[b, c])
        fetch(bronze, "a", 2, links=[b])  # recrawl: still one URL
        fetch(bronze, "b", 3, status_code=404, links=[a, c])
        fetch(bronze, "c", 4, status_code=None, error="timeout")
        fetch(bronze, "d", 5, status_code=500)
        fetch(bronze, "d", 6)  # recovered: the latest fetch wins
        domain_id = bronze.domain_id_for_host(HOST)
        assert domain_id is not None

        written = stats.refresh_domain_stats([domain_id], when=_ANCIENT)
        row = row_for(stats, domain_id)

        assert written == 1
        assert (row.scraped_pages, row.failed_pages) == (2, 2)  # a, d | b, c
        assert row.discovered_links == 3  # a, b, c, each once
        assert row.last_fetched_at == _ANCIENT + timedelta(days=6)
        assert row.computed_at == _ANCIENT
        DomainStatsRead.model_validate(row)

    def test_silver_pages_and_quarantine_are_counted(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        silver = SilverRepository(stats.session)
        doc_id = fetch(bronze, "page", 1)
        domain_id = bronze.domain_id_for_host(HOST)
        silver.save_page(
            {"searchable_text": "x", "content_hash": "a" * 64},
            crawled_document_id=doc_id,
            domain_id=domain_id,
        )
        file_id = bronze.save_stored_file(
            {
                "source_page_url": f"https://{HOST}/page",
                "document_url": f"https://{HOST}/bad.exe",
                "storage_path": "raw/bad.exe",
                "sha256": "9" * 64,
                "size": 10,
                "stored_at": _ANCIENT.isoformat(),
            },
            crawled_document_id=doc_id,
        ).id
        silver.quarantine(
            stored_file_id=file_id, threat_signature="Eicar", quarantine_path="s3://q/bad.exe"
        )
        assert domain_id is not None

        stats.refresh_domain_stats([domain_id])
        row = row_for(stats, domain_id)
        assert (row.page_count, row.quarantined_count) == (1, 1)

    def test_a_domain_with_nothing_crawled_gets_zeros_and_refresh_is_idempotent(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        domain_id = bronze.ensure_domain("quiet.gov.np")
        stats.refresh_domain_stats([domain_id])
        first = row_for(stats, domain_id)
        first_id = first.id
        assert (first.scraped_pages, first.discovered_links, first.last_fetched_at) == (0, 0, None)

        fetch(bronze, "x", 1, host="quiet.gov.np")
        stats.refresh_domain_stats([domain_id])
        again = row_for(stats, domain_id)
        assert again.id == first_id and again.scraped_pages == 1

    def test_refreshing_all_domains_and_empty_scope(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        domain_id = bronze.ensure_domain("everyone.gov.np")
        assert stats.refresh_domain_stats([]) == 0
        assert stats.refresh_domain_stats() >= 1
        assert row_for(stats, domain_id).scraped_pages == 0

    def test_deleting_a_domain_removes_its_stats(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        domain_id = bronze.ensure_domain("deleted.gov.np")
        stats.refresh_domain_stats([domain_id])
        stats.session.execute(delete(Domain).where(Domain.id == domain_id))
        assert (
            stats.session.scalar(select(DomainStats).where(DomainStats.domain_id == domain_id))
            is None
        )


class TestDomainList:
    def test_search_filter_order_and_stats(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        low = bronze.ensure_domain("zz-list-low.gov.np", priority=DomainPriority.LOW)
        high = bronze.ensure_domain("zz-list-high.gov.np", priority=DomainPriority.HIGH)
        bronze.ensure_domain("zz-list-paused.gov.np", status=DomainStatus.PAUSED)
        fetch(bronze, "p", 1, host="zz-list-high.gov.np")
        stats.refresh_domain_stats([high])

        rows, total = stats.list_domains(search="ZZ-LIST")
        assert total == 3
        assert [r["domain"] for r in rows] == [
            "zz-list-high.gov.np",
            "zz-list-paused.gov.np",
            "zz-list-low.gov.np",
        ]
        assert rows[0]["scraped_pages"] == 1 and rows[0]["stats_computed_at"] is not None
        assert rows[2]["id"] == low and rows[2]["stats_computed_at"] is None  # never refreshed
        DomainOverview.model_validate(rows[0])

        paused, total = stats.list_domains(search="zz-list", status=DomainStatus.PAUSED)
        assert total == 1 and paused[0]["domain"] == "zz-list-paused.gov.np"

        page, total = stats.list_domains(search="zz-list", limit=1, offset=1)
        assert total == 3 and [r["domain"] for r in page] == ["zz-list-paused.gov.np"]

    def test_like_wildcards_in_search_are_literal(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        bronze.ensure_domain("under_score.gov.np")
        bronze.ensure_domain("underXscore.gov.np")
        rows, _ = stats.list_domains(search="under_score")
        assert [r["domain"] for r in rows] == ["under_score.gov.np"]

    def test_set_domain_status(self, stats: StatsRepository, bronze: BronzeRepository) -> None:
        domain_id = bronze.ensure_domain("pause-me.gov.np")
        assert stats.set_domain_status(domain_id, DomainStatus.PAUSED).status == DomainStatus.PAUSED
        with pytest.raises(LookupError):
            stats.set_domain_status(9_999_999, DomainStatus.PAUSED)


class TestDashboard:
    def test_summary_reflects_new_rows(
        self, stats: StatsRepository, bronze: BronzeRepository
    ) -> None:
        now = datetime.now(UTC)
        before = DashboardSummary.model_validate(stats.dashboard_summary(now=now))

        domain_id = bronze.ensure_domain("dash.gov.np", status=DomainStatus.CRAWLING)
        fetch(bronze, "one", 1, host="dash.gov.np", links=["https://dash.gov.np/two"])
        bronze.save_stored_file(
            {
                "source_page_url": "https://dash.gov.np/one",
                "document_url": "https://dash.gov.np/budget.pdf",
                "storage_path": "raw/budget.pdf",
                "sha256": "7" * 64,
                "size": 2048,
                "stored_at": _ANCIENT.isoformat(),
            }
        )
        stats.refresh_domain_stats([domain_id])
        OpsRepository(stats.session).log_error(
            ServiceName.SCRAPER, LogSeverity.ERROR, "boom", occurred_at=now - timedelta(hours=1)
        )
        after = DashboardSummary.model_validate(stats.dashboard_summary(now=now))

        assert after.domains.total_registered == before.domains.total_registered + 1
        assert after.domains.active_crawling == before.domains.active_crawling + 1
        assert (
            after.links.total_child_links_discovered
            == before.links.total_child_links_discovered + 1
        )
        assert after.storage.unprocessed_files == before.storage.unprocessed_files + 2
        assert after.storage.total_raw_files == before.storage.total_raw_files + 2
        assert (
            after.storage.total_storage_used_bytes
            == before.storage.total_storage_used_bytes + 2048
        )
        assert after.storage.oldest_unprocessed_at is not None
        assert after.storage.oldest_unprocessed_at <= _ANCIENT + timedelta(days=1)
        assert after.errors_last_24h.ERROR == before.errors_last_24h.ERROR + 1
