"""What the ETL needs beyond the page loop in test_silver.py: pages built from stored
files (PDFs, images), the stored-file work queue, stage-3 dedup lookups and stage-4
geo helpers. Runs against a real PostgreSQL, like the rest of the suite."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository, ReferenceRepository, SilverRepository
from pgs_db.enums import ProcessingStatus
from pgs_db.models import Domain, Page, StoredFile
from pgs_db.repositories import signed_simhash
from pgs_db.repositories.reference import site_host

HOST = "pokharamun.gov.np"
PAGE_URL = f"https://{HOST}/notice/detail/456"
PDF_URL = f"https://{HOST}/uploads/budget_2080.pdf"
_ANCIENT = datetime(1985, 1, 1, tzinfo=UTC)


@pytest.fixture()
def bronze(session: Session) -> BronzeRepository:
    return BronzeRepository(session)


@pytest.fixture()
def silver(session: Session) -> SilverRepository:
    return SilverRepository(session)


@pytest.fixture()
def reference(session: Session) -> ReferenceRepository:
    return ReferenceRepository(session)


def stored_doc(**overrides: Any) -> dict[str, Any]:
    stored: dict[str, Any] = {
        "source_page_url": PAGE_URL,
        "document_url": PDF_URL,
        "storage_path": f"raw/documents/{HOST}/budget_2080.pdf",
        "content_type": "application/pdf",
        "sha256": "c" * 64,
        "size": 3250585,
        "stored_at": "2026-09-23T06:00:05Z",
    }
    stored.update(overrides)
    return stored


def bronze_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "url": PAGE_URL,
        "normalized_url": PAGE_URL,
        "host": HOST,
        "title": "Notice",
        "text": "text",
        "content_hash": "e" * 64,
        "content_type": "text/html",
        "fetched_at": "2026-09-23T05:05:00Z",
        "status_code": 200,
        "depth": 1,
    }
    doc.update(overrides)
    return doc


def payload(**overrides: Any) -> dict[str, Any]:
    """A §5.2 payload without source_url: the URL comes from the Bronze source."""
    body: dict[str, Any] = {
        "searchable_text": "Pokhara Metropolitan City annual budget 2080/81",
        "language_detected": "en",
        "extracted_metadata": {"title": "Annual Budget 2080/81"},
        "content_hash": "d" * 64,
    }
    body.update(overrides)
    return body


def queued_file(bronze: BronzeRepository, n: int) -> int:
    return bronze.save_stored_file(
        stored_doc(
            document_url=f"https://{HOST}/queue/{n}.pdf",
            sha256=f"{n:064x}",
            stored_at=(_ANCIENT + timedelta(days=n)).isoformat(),
        )
    ).id


def file_status(session: Session, file_id: int) -> tuple[ProcessingStatus, str | None]:
    row = session.execute(
        select(StoredFile.processing_status, StoredFile.processing_error).where(
            StoredFile.id == file_id
        )
    ).one()
    return row[0], row[1]


class TestPagesFromStoredFiles:
    def test_a_stored_file_becomes_a_page_keyed_on_its_document_url(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        file_id = bronze.save_stored_file(stored_doc()).id
        result = silver.save_page(payload(), stored_file_id=file_id)

        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.canonical_url == PDF_URL
        assert page.stored_file_id == file_id
        assert page.crawled_document_id is None
        assert silver.page_for_stored_file(file_id) == page

    @pytest.mark.parametrize("both", [True, False])
    def test_exactly_one_source_is_required(
        self, silver: SilverRepository, bronze: BronzeRepository, both: bool
    ) -> None:
        file_id = bronze.save_stored_file(stored_doc()).id
        doc_id = bronze.save_document(bronze_doc()).id
        kwargs = {"crawled_document_id": doc_id, "stored_file_id": file_id} if both else {}
        with pytest.raises(ValueError, match="exactly one"):
            silver.save_page(payload(), **kwargs)

    def test_database_rejects_a_page_with_two_sources(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        file_id = bronze.save_stored_file(stored_doc()).id
        doc_id = bronze.save_document(bronze_doc()).id
        result = silver.save_page(payload(), stored_file_id=file_id)
        with pytest.raises(IntegrityError, match="ck_pages_one_source"):
            silver.session.execute(
                update(Page).where(Page.id == result.id).values(crawled_document_id=doc_id)
            )

    def test_missing_file_and_url_is_rejected(self, silver: SilverRepository) -> None:
        with pytest.raises(ValueError, match="stored_file 9999999"):
            silver.save_page(payload(), stored_file_id=9_999_999)

    def test_a_newer_file_updates_and_an_older_one_does_not(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        old_id = bronze.save_stored_file(stored_doc()).id
        new_id = bronze.save_stored_file(stored_doc(sha256="f" * 64)).id
        silver.save_page(payload(), stored_file_id=new_id)
        silver.save_page(payload(searchable_text="stale text"), stored_file_id=old_id)

        page = silver.page_for_stored_file(new_id)
        assert page is not None
        silver.session.refresh(page)
        assert page.body_text != "stale text"

    def test_switching_source_clears_the_other_link(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        """The same PDF URL crawled as a page, then stored as a file: last one wins."""
        doc_id = bronze.save_document(bronze_doc(url=PDF_URL, normalized_url=PDF_URL)).id
        file_id = bronze.save_stored_file(stored_doc()).id
        first = silver.save_page(payload(), crawled_document_id=doc_id)
        second = silver.save_page(payload(), stored_file_id=file_id)

        assert first.id == second.id
        page = silver.session.get(Page, first.id)
        assert page is not None
        silver.session.refresh(page)
        assert (page.crawled_document_id, page.stored_file_id) == (None, file_id)


class TestStoredFileQueue:
    def test_claim_moves_oldest_first_and_does_not_reclaim(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        second, first = queued_file(bronze, 2), queued_file(bronze, 1)
        claimed = silver.claim_stored_files(limit=2)

        assert [f.id for f in claimed] == [first, second]
        assert all(f.processing_status == ProcessingStatus.PROCESSING for f in claimed)
        assert {f.id for f in silver.claim_stored_files(limit=1000)}.isdisjoint(
            {first, second}
        )

    def test_claim_to_page_to_processed(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        file_id = queued_file(bronze, 1)
        (claimed,) = [f for f in silver.claim_stored_files(limit=1000) if f.id == file_id]
        silver.save_page(payload(), stored_file_id=claimed.id)
        assert silver.mark_stored_files_processed([claimed.id]) == 1
        assert file_status(silver.session, file_id) == (ProcessingStatus.PROCESSED, None)

    def test_failed_records_the_reason_and_reclaim_clears_it(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        file_id = queued_file(bronze, 1)
        silver.mark_stored_file_failed(file_id, "encrypted PDF")
        assert file_status(silver.session, file_id) == (
            ProcessingStatus.FAILED,
            "encrypted PDF",
        )

        silver.session.execute(
            update(StoredFile)
            .where(StoredFile.id == file_id)
            .values(processing_status=ProcessingStatus.UNPROCESSED)
        )
        silver.claim_stored_files(limit=1000)
        assert file_status(silver.session, file_id) == (ProcessingStatus.PROCESSING, None)

    def test_mark_failed_on_missing_file_raises(self, silver: SilverRepository) -> None:
        with pytest.raises(LookupError, match="stored file"):
            silver.mark_stored_file_failed(9_999_999, "x")

    def test_release_stale_covers_stored_files(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        stale, fresh = queued_file(bronze, 1), queued_file(bronze, 2)
        silver.claim_stored_files(limit=1000)
        silver.session.execute(
            update(StoredFile)
            .where(StoredFile.id == stale)
            .values(updated_at=func.now() - timedelta(hours=1))
        )

        assert silver.release_stale(timedelta(minutes=30)) >= 1
        assert file_status(silver.session, stale)[0] == ProcessingStatus.UNPROCESSED
        assert file_status(silver.session, fresh)[0] == ProcessingStatus.PROCESSING


class TestDeduplication:
    def _page(
        self, silver: SilverRepository, bronze: BronzeRepository, n: int, **kw: Any
    ) -> int:
        url = f"https://{HOST}/dedup/{n}"
        doc_id = bronze.save_document(
            bronze_doc(url=url, normalized_url=url, content_hash=f"{n:064x}")
        ).id
        return silver.save_page(payload(**kw), crawled_document_id=doc_id).id

    def test_exact_duplicate_is_the_oldest_canonical_page(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        shared = "a1" * 32
        first = self._page(silver, bronze, 1, content_hash=shared)
        second = self._page(silver, bronze, 2, content_hash=shared)
        silver.mark_duplicate_of(second, first)
        third = self._page(silver, bronze, 3, content_hash=shared)

        found = silver.find_exact_duplicate(shared, exclude_page_id=third)
        assert found is not None and found.id == first
        # Excluding the oldest, the next canonical page is the answer; `second` is
        # folded, so it is never returned.
        found = silver.find_exact_duplicate(shared, exclude_page_id=first)
        assert found is not None and found.id == third
        assert silver.find_exact_duplicate("0f" * 32) is None

    def test_near_duplicates_within_three_bits(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        # A uint64 with the top bit set, so the stored int64 is negative.
        base = signed_simhash(0xF0F0_F0F0_1234_5678)
        same = self._page(silver, bronze, 1, sim_hash=base)
        three_off = self._page(silver, bronze, 2, sim_hash=base ^ 0b111)
        four_off = self._page(silver, bronze, 3, sim_hash=base ^ 0b1111)

        found = silver.find_near_duplicates(base)
        ids = [page.id for page, _ in found]
        assert (same, 0) in [(p.id, d) for p, d in found]
        assert (three_off, 3) in [(p.id, d) for p, d in found]
        assert four_off not in ids
        assert ids.index(same) < ids.index(three_off)

    def test_near_duplicates_exclude_self_and_folded_pages(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        base = 0x0123_4567_89AB_CDEF
        canonical = self._page(silver, bronze, 1, sim_hash=base)
        folded = self._page(silver, bronze, 2, sim_hash=base ^ 1)
        silver.mark_duplicate_of(folded, canonical)

        ids = [p.id for p, _ in silver.find_near_duplicates(base, exclude_page_id=canonical)]
        assert canonical not in ids and folded not in ids


class TestGeoHelpers:
    @pytest.mark.parametrize(
        "raw",
        ["http://www.pokharamun.gov.np/", "WWW.Pokharamun.gov.np", "pokharamun.gov.np"],
    )
    def test_site_host(self, raw: str) -> None:
        assert site_host(raw) == "pokharamun.gov.np"

    def test_gazetteer_has_every_place_with_parent_codes(
        self, reference: ReferenceRepository
    ) -> None:
        entries = reference.gazetteer()
        assert len(entries) == 7 + 77 + 753
        pokhara = next(e for e in entries if e["code"] == "MUN414")
        assert (pokhara["province_code"], pokhara["district_code"]) == ("P4", "D38")
        assert pokhara["municipality_id"] == "MUN414"
        kaski = next(e for e in entries if e["code"] == "D38")
        assert kaski["name_en"] == "Kaski"

    def test_domains_link_to_their_local_body_and_tag_pages(
        self,
        reference: ReferenceRepository,
        bronze: BronzeRepository,
        silver: SilverRepository,
    ) -> None:
        domain_id = bronze.ensure_domain(f"www.{HOST}")
        assert reference.geo_for_domain(domain_id) is None

        assert reference.link_domains_to_local_bodies() >= 1
        geo = reference.geo_for_domain(domain_id)
        assert geo == {
            "province_code": "P4",
            "district_code": "D38",
            "municipality_id": "MUN414",
            "method": "DOMAIN",
            "confidence": 1.0,
        }

        # The block drops straight into save_page.
        doc_id = bronze.save_document(bronze_doc()).id
        result = silver.save_page(
            payload(geo_location=geo), crawled_document_id=doc_id, domain_id=domain_id
        )
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert [t.local_body_code for t in page.geo_tags] == ["MUN414"]

    def test_a_manual_link_is_not_overwritten(
        self, reference: ReferenceRepository, bronze: BronzeRepository
    ) -> None:
        domain_id = bronze.ensure_domain(HOST)
        # An admin links pokharamun.gov.np to local body id 1 by hand.
        reference.session.execute(
            update(Domain).where(Domain.id == domain_id).values(local_body_id=1)
        )
        reference.link_domains_to_local_bodies()
        assert (
            reference.session.scalar(select(Domain.local_body_id).where(Domain.id == domain_id))
            == 1
        )

    def test_unknown_or_unlinked_domain_has_no_geo(self, reference: ReferenceRepository) -> None:
        assert reference.geo_for_domain(None) is None
        assert reference.geo_for_domain(9_999_999) is None
