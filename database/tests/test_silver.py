"""Phase 2 tests: Bronze document -> Silver page -> geo tags + contacts.

Payloads are shaped exactly as `ETL/spark/README.md` §5.2 specifies, so if Spark
ever changes its output these tests are where it shows up first.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository, SilverRepository, make_engine
from pgs_db.enums import ContactType, GeoTagMethod, Language, LocalBodyType, ProcessingStatus
from pgs_db.models import CrawledDocument, LocalBody, Page, PageContact, PageGeoTag
from pgs_db.repositories.silver import to_language
from pgs_db.schemas import GeoLocationOut, PageGeoTagCreate, PageRead, PageWithRelations

HOST = "pokharamun.gov.np"
SOURCE_URL = f"https://{HOST}/notice/detail/456"
CONTENT_HASH = "e" * 64
BODY_TEXT = "पोखरा महानगरपालिका Local Governance Update Notice for ward 5"
FETCHED = datetime(2026, 9, 23, 5, 5, tzinfo=UTC)


@pytest.fixture()
def bronze(session: Session) -> BronzeRepository:
    return BronzeRepository(session)


@pytest.fixture()
def silver(session: Session) -> SilverRepository:
    return SilverRepository(session)


def bronze_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "url": f"{SOURCE_URL}?utm_source=fb",
        "normalized_url": SOURCE_URL,
        "host": HOST,
        "title": "Local Governance Update Notice",
        "text": "Full extracted PDF text",
        "content_hash": CONTENT_HASH,
        "content_type": "application/pdf",
        "fetched_at": "2026-09-23T05:05:00Z",
        "status_code": 200,
        "depth": 3,
    }
    doc.update(overrides)
    return doc


@pytest.fixture()
def bronze_document(bronze: BronzeRepository) -> int:
    """A Bronze row for the page the ETL spec uses as its worked example."""
    return bronze.save_document(bronze_doc(), register_unknown_domains=True).id


def geo_block(**overrides: Any) -> dict[str, Any]:
    block: dict[str, Any] = {
        "province_code": "P4",
        "district_code": "D38",
        "municipality_id": "MUN414",
        "ward_number": None,
        "method": "GAZETTEER",
        "confidence": 0.92,
        "mention_text": "पोखरा महानगरपालिका",
    }
    block.update(overrides)
    return block


def etl_payload(**overrides: Any) -> dict[str, Any]:
    """The Spark ETL output payload, per ETL/spark/README.md §5.2."""
    payload: dict[str, Any] = {
        "source_url": SOURCE_URL,
        "searchable_text": BODY_TEXT,
        "language_detected": "mixed",
        "extracted_metadata": {
            "title": "Local Governance Update Notice",
            "description": "Official notice regarding municipal administration.",
            "keywords": ["nepal", "local government", "gandaki", "pokhara"],
            "contact_info": {
                "emails": ["info@pokharamun.gov.np"],
                "phones": ["+977-61-521105"],
            },
        },
        "geo_location": geo_block(),
        "content_hash": CONTENT_HASH,
    }
    payload.update(overrides)
    return payload


def count(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


class TestBronzeToSilverFlow:
    def test_full_flow_document_to_page_to_tags_and_contacts(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        session = silver.session
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        assert result.inserted
        session.flush()

        page = session.get(Page, result.id)
        assert page is not None
        assert page.crawled_document_id == bronze_document
        assert page.canonical_url == SOURCE_URL  # §5.2 source_url
        assert page.body_text == BODY_TEXT  # §5.2 searchable_text
        assert page.word_count == len(BODY_TEXT.split())
        assert page.language == Language.MIXED  # §5.2 language_detected
        assert page.content_type == "web_page"
        assert page.keywords == ["nepal", "local government", "gandaki", "pokhara"]
        assert page.duplicate_of_id is None
        assert page.processing_status == ProcessingStatus.UNPROCESSED

        assert len(page.geo_tags) == 1
        tag = page.geo_tags[0]
        assert tag.province_code == "P4"
        assert tag.district_code == "D38"
        assert tag.local_body_code == "MUN414"  # §5.2 municipality_id
        assert tag.local_body.name_en == "Pokhara"
        assert tag.method == GeoTagMethod.GAZETTEER
        assert tag.confidence == pytest.approx(0.92)
        assert tag.mention_text == "पोखरा महानगरपालिका"

        contacts = {(c.type, c.value) for c in page.contacts}
        assert contacts == {
            (ContactType.EMAIL, "info@pokharamun.gov.np"),
            (ContactType.PHONE, "+977-61-521105"),
        }

    def test_etl_word_count_wins_over_computed(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(
            etl_payload(word_count=999), crawled_document_id=bronze_document
        )
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.word_count == 999

    def test_geo_names_come_from_the_gazetteer_not_the_page(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        """§5.2's denormalized geo_location block is rebuilt by joining."""
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None

        block = GeoLocationOut.from_tag(page.geo_tags[0])
        assert block.province_code == "P4"
        assert block.province_name_en == "Gandaki"
        assert block.district_name_en == "Kaski"
        assert block.district_name_ne == "कास्की"
        assert block.municipality_id == "MUN414"
        assert block.municipality_name_ne == "पोखरा"
        assert block.municipality_type == LocalBodyType.METROPOLITAN_CITY

    def test_page_validates_against_the_schema(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        read = PageWithRelations.model_validate(page)
        assert read.canonical_url == SOURCE_URL
        assert read.body_text == BODY_TEXT
        assert read.language == Language.MIXED
        assert read.content_hash == CONTENT_HASH
        assert read.geo_tags[0].local_body_code == "MUN414"
        assert read.geo_tags[0].method == GeoTagMethod.GAZETTEER

    def test_timestamps_are_utc(self, silver: SilverRepository, bronze_document: int) -> None:
        result = silver.save_page(
            etl_payload(published_at="2026-09-20T10:30:00Z"),
            crawled_document_id=bronze_document,
        )
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.published_at == datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
        assert page.created_at.utcoffset() == UTC.utcoffset(None)


class TestLanguageMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ne", Language.NE),
            ("en", Language.EN),
            ("mixed", Language.MIXED),
            ("EN", Language.EN),
            ("en-US", Language.EN),
            ("ne_NP", Language.NE),
            ("hi", Language.OTHER),
            ("unknown", Language.OTHER),
            ("", Language.OTHER),
            (None, Language.OTHER),
        ],
    )
    def test_to_language(self, raw: Any, expected: Language) -> None:
        assert to_language(raw) == expected

    def test_missing_language_is_stored_as_other(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        payload = etl_payload()
        del payload["language_detected"]
        result = silver.save_page(payload, crawled_document_id=bronze_document)
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.language == Language.OTHER


class TestInvalidEnumsAreRejected:
    """Unknown language codes from Spark map to OTHER (see TestLanguageMapping), but
    storing a value outside the enum is rejected -- by the ORM, the schema and the
    database CHECK, so a raw-SQL writer cannot slip one in either."""

    def test_db_rejects_an_invalid_language(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        # Lowercase 'ne' is Spark's code, not a stored value.
        with pytest.raises(IntegrityError, match="ck_pages_language"):
            silver.session.execute(
                text("UPDATE pages SET language = 'ne' WHERE id = :id"), {"id": result.id}
            )

    def test_db_rejects_an_invalid_geo_tag_method(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        with pytest.raises(IntegrityError, match="ck_page_geo_tags_geo_tag_method"):
            silver.session.execute(
                text("UPDATE page_geo_tags SET method = 'GUESS' WHERE page_id = :id"),
                {"id": result.id},
            )

    def test_orm_rejects_an_invalid_language_before_sql(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        page.language = "klingon"  # type: ignore[assignment]
        with pytest.raises(StatementError, match="klingon"):
            silver.session.flush()

    def test_schema_rejects_an_invalid_language(self) -> None:
        with pytest.raises(ValidationError, match="language"):
            PageRead.model_validate(
                {
                    "id": 1,
                    "created_at": FETCHED,
                    "updated_at": FETCHED,
                    "canonical_url": SOURCE_URL,
                    "content_hash": CONTENT_HASH,
                    "crawled_document_id": 1,
                    "body_text": BODY_TEXT,
                    "word_count": 3,
                    "language": "klingon",
                }
            )

    @pytest.mark.parametrize(
        ("field", "value"), [("method", "GUESS"), ("confidence", 1.5), ("confidence", -0.1)]
    )
    def test_schema_rejects_an_invalid_geo_tag(self, field: str, value: Any) -> None:
        tag: dict[str, Any] = {"district_code": "D38", "method": "NER", "confidence": 0.5}
        tag[field] = value
        with pytest.raises(ValidationError, match=field):
            PageGeoTagCreate.model_validate(tag)


class TestCanonicalUrlIdentity:
    def test_a_recrawl_with_new_content_updates_the_same_page(
        self, silver: SilverRepository, bronze: BronzeRepository, bronze_document: int
    ) -> None:
        first = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()

        # Changed content -> a new Bronze row for the same URL.
        newer_bronze = bronze.save_document(
            bronze_doc(content_hash="f" * 64, fetched_at="2026-09-24T05:05:00Z")
        ).id
        assert newer_bronze > bronze_document
        second = silver.save_page(
            etl_payload(content_hash="f" * 64, searchable_text="updated notice text"),
            crawled_document_id=newer_bronze,
        )
        silver.session.flush()

        assert second.duplicate and second.id == first.id
        assert count(silver.session, Page) == 1
        page = silver.session.get(Page, first.id)
        assert page is not None
        silver.session.refresh(page)
        assert page.crawled_document_id == newer_bronze  # points at the latest row
        assert page.body_text == "updated notice text"
        assert page.content_hash == "f" * 64

    def test_an_older_bronze_row_does_not_roll_the_page_back(
        self, silver: SilverRepository, bronze: BronzeRepository, bronze_document: int
    ) -> None:
        newer_bronze = bronze.save_document(
            bronze_doc(content_hash="f" * 64, fetched_at="2026-09-24T05:05:00Z")
        ).id
        silver.save_page(
            etl_payload(content_hash="f" * 64, searchable_text="new text"),
            crawled_document_id=newer_bronze,
        )
        silver.session.flush()

        # A retry of the older Bronze row arrives late.
        stale = silver.save_page(
            etl_payload(geo_location=geo_block(province_code="P3", district_code="D27",
                                               municipality_id=None)),
            crawled_document_id=bronze_document,
        )
        silver.session.flush()

        assert stale.duplicate
        page = silver.session.get(Page, stale.id)
        assert page is not None
        silver.session.refresh(page)
        assert page.crawled_document_id == newer_bronze
        assert page.body_text == "new text"
        assert page.content_hash == "f" * 64
        assert [t.province_code for t in page.geo_tags] == ["P4"]  # children untouched too

    def test_different_urls_are_different_pages(
        self, silver: SilverRepository, bronze: BronzeRepository, bronze_document: int
    ) -> None:
        other_url = f"https://{HOST}/other"
        other_bronze = bronze.save_document(
            bronze_doc(url=other_url, normalized_url=other_url, content_hash="f" * 64)
        ).id
        a = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        b = silver.save_page(
            etl_payload(source_url=other_url, content_hash="f" * 64),
            crawled_document_id=other_bronze,
        )
        assert a.id != b.id
        assert count(silver.session, Page) == 2

    def test_reprocessing_requeues_the_page_for_indexing(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        silver.mark_processed(result.id, error="opensearch timeout")
        silver.session.flush()

        silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        silver.session.refresh(page)
        assert page.processing_status == ProcessingStatus.UNPROCESSED
        assert page.processing_error is None

    def test_mark_duplicate_of_links_to_canonical(
        self, silver: SilverRepository, bronze: BronzeRepository, bronze_document: int
    ) -> None:
        canonical = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        mirror_url = f"https://{HOST}/mirror"
        mirror_bronze = bronze.save_document(
            bronze_doc(url=mirror_url, normalized_url=mirror_url, content_hash="f" * 64)
        ).id
        mirror = silver.save_page(
            etl_payload(source_url=mirror_url, content_hash="f" * 64),
            crawled_document_id=mirror_bronze,
        )
        silver.mark_duplicate_of(mirror.id, canonical.id)
        silver.session.flush()

        page = silver.session.get(Page, mirror.id)
        assert page is not None
        assert page.duplicate_of.id == canonical.id

    def test_page_cannot_be_its_own_duplicate(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        with pytest.raises(ValueError, match="duplicate of itself"):
            silver.mark_duplicate_of(result.id, result.id)


class TestReprocessing:
    def test_reprocessing_updates_instead_of_duplicating(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        first = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        second = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()

        assert first.inserted and second.duplicate and first.id == second.id
        assert count(silver.session, Page) == 1
        assert count(silver.session, PageGeoTag) == 1
        assert count(silver.session, PageContact) == 2

    def test_running_the_etl_five_times_is_stable(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        for _ in range(5):
            silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        assert count(silver.session, Page) == 1
        assert count(silver.session, PageContact) == 2

    def test_reprocessing_corrects_a_wrong_geo_tag(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()

        corrected = etl_payload(
            geo_location=geo_block(
                province_code="P3", district_code="D27", municipality_id=None, ward_number=5
            )
        )
        result = silver.save_page(corrected, crawled_document_id=bronze_document)
        silver.session.flush()

        page = silver.session.get(Page, result.id)
        assert page is not None
        assert len(page.geo_tags) == 1  # the wrong tag is gone, not kept alongside
        assert page.geo_tags[0].province_code == "P3"
        assert page.geo_tags[0].ward_number == 5

    def test_reprocessing_updates_changed_metadata(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        updated = etl_payload()
        updated["extracted_metadata"]["title"] = "Corrected Title"
        result = silver.save_page(updated, crawled_document_id=bronze_document)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        silver.session.refresh(page)
        assert page.title == "Corrected Title"

    def test_multiple_locations_are_supported(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        """A national news article can be about several districts."""
        tag = {"method": "NER", "confidence": 0.7}
        result = silver.save_page(
            etl_payload(
                geo_location=[
                    {"district_code": "D38", **tag},
                    {"district_code": "D39", **tag},
                    {"province_code": "P4", **tag},
                ]
            ),
            crawled_document_id=bronze_document,
        )
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert len(page.geo_tags) == 3
        assert {t.method for t in page.geo_tags} == {GeoTagMethod.NER}

    def test_duplicate_contacts_on_one_page_collapse(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        payload = etl_payload()
        payload["extracted_metadata"]["contact_info"]["emails"] = [
            "info@pokharamun.gov.np",
            "info@pokharamun.gov.np",
        ]
        silver.save_page(payload, crawled_document_id=bronze_document)
        silver.session.flush()
        assert count(silver.session, PageContact) == 2


class TestGeographyAndValidation:
    def test_untagged_page_is_stored_without_geo(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        """Most of the web is not about a place; that is not an error."""
        result = silver.save_page(
            etl_payload(geo_location=None), crawled_document_id=bronze_document
        )
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.geo_tags == []

    def test_empty_geo_block_is_skipped_not_rejected(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        """No resolved level means no tag -- method/confidence are not demanded."""
        result = silver.save_page(
            etl_payload(geo_location={"ward_number": None}),
            crawled_document_id=bronze_document,
        )
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.geo_tags == []

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"method": None}, "'method'"),
            ({"confidence": None}, "'confidence'"),
            ({"method": "GUESS"}, "unknown geo tag method"),
            ({"confidence": 1.5}, "within 0..1"),
            ({"confidence": -0.1}, "within 0..1"),
        ],
    )
    def test_bad_geo_tag_is_rejected_before_any_write(
        self,
        silver: SilverRepository,
        bronze_document: int,
        overrides: dict[str, Any],
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            silver.save_page(
                etl_payload(geo_location=geo_block(**overrides)),
                crawled_document_id=bronze_document,
            )
        assert count(silver.session, Page) == 0  # no half-written page

    def test_method_is_case_insensitive(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(
            etl_payload(geo_location=geo_block(method="geo_meta")),
            crawled_document_id=bronze_document,
        )
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.geo_tags[0].method == GeoTagMethod.GEO_META

    def test_unknown_municipality_code_violates_the_foreign_key(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        with pytest.raises(IntegrityError):
            silver.save_page(
                etl_payload(geo_location=geo_block(municipality_id="MUN999999")),
                crawled_document_id=bronze_document,
            )
            silver.session.flush()

    def test_geo_tag_needs_at_least_one_level(self, session: Session) -> None:
        with pytest.raises(ValueError, match="at least one"):
            PageGeoTagCreate(ward_number=3, method=GeoTagMethod.NER, confidence=0.5)

    def test_check_constraint_rejects_empty_geo_tag(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        silver.session.add(
            PageGeoTag(
                page_id=result.id, ward_number=2, method=GeoTagMethod.NER, confidence=0.5
            )
        )
        with pytest.raises(IntegrityError):
            silver.session.flush()

    def test_ward_number_must_be_positive(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        silver.session.add(
            PageGeoTag(
                page_id=result.id,
                district_code="D38",
                ward_number=0,
                method=GeoTagMethod.NER,
                confidence=0.5,
            )
        )
        with pytest.raises(IntegrityError):
            silver.session.flush()

    def test_check_constraint_rejects_confidence_out_of_range(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        """The DB enforces 0..1 even for writers that bypass the repository."""
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        silver.session.add(
            PageGeoTag(
                page_id=result.id,
                district_code="D39",
                method=GeoTagMethod.NER,
                confidence=1.01,
            )
        )
        with pytest.raises(IntegrityError):
            silver.session.flush()

    @pytest.mark.parametrize("field", ["searchable_text", "content_hash"])
    def test_missing_required_field_is_rejected_before_sql(
        self, silver: SilverRepository, bronze_document: int, field: str
    ) -> None:
        payload = etl_payload()
        del payload[field]
        with pytest.raises(ValueError, match=field):
            silver.save_page(payload, crawled_document_id=bronze_document)

    def test_missing_source_url_falls_back_to_bronze_normalized_url(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        """The ETL need not send the URL: Bronze already holds the page's identity."""
        doc_id = bronze.save_document(
            bronze_doc(url=f"{SOURCE_URL}/amp", normalized_url=f"{SOURCE_URL}/canonical"),
            register_unknown_domains=True,
        ).id
        payload = etl_payload()
        del payload["source_url"]
        result = silver.save_page(payload, crawled_document_id=doc_id)
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.canonical_url == f"{SOURCE_URL}/canonical"

    def test_payload_source_url_wins_over_bronze(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        other = f"https://{HOST}/notice/detail/999"
        result = silver.save_page(
            etl_payload(source_url=other), crawled_document_id=bronze_document
        )
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.canonical_url == other

    def test_missing_source_url_and_bronze_row_is_rejected(
        self, silver: SilverRepository
    ) -> None:
        payload = etl_payload()
        del payload["source_url"]
        with pytest.raises(ValueError, match="source_url"):
            silver.save_page(payload, crawled_document_id=9_999_999)


class TestForeignKeys:
    def test_page_needs_a_real_bronze_document(self, silver: SilverRepository) -> None:
        with pytest.raises(IntegrityError):
            silver.save_page(etl_payload(), crawled_document_id=9_999_999)
            silver.session.flush()

    def test_bronze_row_behind_a_page_cannot_be_deleted(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        """RESTRICT: Bronze retention must not silently take a live page with it."""
        silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        with pytest.raises(IntegrityError):
            silver.session.execute(
                delete(CrawledDocument).where(CrawledDocument.id == bronze_document)
            )

    def test_geo_tag_needs_a_real_province(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        silver.session.add(
            PageGeoTag(
                page_id=result.id, province_code="P9", method=GeoTagMethod.NER, confidence=0.5
            )
        )
        with pytest.raises(IntegrityError):
            silver.session.flush()

    def test_deleting_a_page_cascades_to_children(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        silver.session.delete(page)
        silver.session.flush()

        assert count(silver.session, PageGeoTag) == 0
        assert count(silver.session, PageContact) == 0


class TestPageIndexingState:
    def test_mark_processed_and_failed(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()

        silver.mark_processed(result.id)
        silver.session.flush()
        page = silver.session.get(Page, result.id)
        assert page is not None
        assert page.processing_status == ProcessingStatus.PROCESSED

        silver.mark_processed(result.id, error="opensearch timeout")
        silver.session.flush()
        silver.session.refresh(page)
        assert page.processing_status == ProcessingStatus.FAILED
        assert page.processing_error == "opensearch timeout"

    def test_mark_processed_on_missing_page_raises(self, silver: SilverRepository) -> None:
        with pytest.raises(LookupError):
            silver.mark_processed(9_999_999)

    def test_page_for_bronze_document_lookup(
        self, silver: SilverRepository, bronze_document: int
    ) -> None:
        assert silver.page_for_bronze_document(bronze_document) is None
        result = silver.save_page(etl_payload(), crawled_document_id=bronze_document)
        silver.session.flush()
        found = silver.page_for_bronze_document(bronze_document)
        assert found is not None and found.id == result.id


# Far in the past so these rows sort ahead of anything else in the queue.
_ANCIENT = datetime(1990, 1, 1, tzinfo=UTC)


def _queued_doc(bronze: BronzeRepository, n: int) -> int:
    url = f"https://{HOST}/queue/{n}"
    return bronze.save_document(
        bronze_doc(
            url=url,
            normalized_url=url,
            content_hash=f"{n:064x}",
            fetched_at=(_ANCIENT + timedelta(days=n)).isoformat(),
        ),
        resolve_domain=False,
    ).id


def _status(session: Session, doc_id: int) -> tuple[ProcessingStatus, str | None]:
    row = session.execute(
        select(CrawledDocument.processing_status, CrawledDocument.processing_error).where(
            CrawledDocument.id == doc_id
        )
    ).one()
    return row[0], row[1]


class TestBronzeWorkQueue:
    def test_claim_moves_rows_to_processing_oldest_first(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        ids = [_queued_doc(bronze, n) for n in (3, 1, 2)]  # inserted out of order
        silver.session.flush()

        claimed = silver.claim_bronze(limit=2)
        assert [doc.id for doc in claimed] == [ids[1], ids[2]]  # fetched day 1, day 2
        assert all(doc.processing_status == ProcessingStatus.PROCESSING for doc in claimed)
        assert _status(silver.session, ids[1])[0] == ProcessingStatus.PROCESSING
        assert _status(silver.session, ids[0])[0] == ProcessingStatus.UNPROCESSED

    def test_claimed_rows_are_not_claimed_again(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        doc_id = _queued_doc(bronze, 1)
        assert doc_id in {d.id for d in silver.claim_bronze(limit=1000)}
        assert doc_id not in {d.id for d in silver.claim_bronze(limit=1000)}

    def test_claim_to_page_to_processed(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        """The ETL loop end to end: claim, build the page, mark the Bronze row done."""
        doc_id = _queued_doc(bronze, 1)
        (doc,) = [d for d in silver.claim_bronze(limit=1000) if d.id == doc_id]

        silver.save_page(
            etl_payload(source_url=doc.normalized_url, geo_location=None),
            crawled_document_id=doc.id,
        )
        assert silver.mark_bronze_processed([doc.id]) == 1
        assert _status(silver.session, doc.id) == (ProcessingStatus.PROCESSED, None)

    def test_mark_bronze_processed_with_no_ids_is_a_noop(
        self, silver: SilverRepository
    ) -> None:
        assert silver.mark_bronze_processed([]) == 0

    def test_mark_bronze_failed_records_the_reason(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        doc_id = _queued_doc(bronze, 1)
        silver.claim_bronze(limit=1000)
        silver.mark_bronze_failed(doc_id, "geo tag is missing required field 'method'")
        assert _status(silver.session, doc_id) == (
            ProcessingStatus.FAILED,
            "geo tag is missing required field 'method'",
        )
        # Failed rows stay parked; they are not re-claimed.
        assert doc_id not in {d.id for d in silver.claim_bronze(limit=1000)}

    def test_reclaiming_clears_a_previous_error(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        doc_id = _queued_doc(bronze, 1)
        silver.mark_bronze_failed(doc_id, "boom")
        # An operator requeues it by hand.
        silver.session.execute(
            update(CrawledDocument)
            .where(CrawledDocument.id == doc_id)
            .values(processing_status=ProcessingStatus.UNPROCESSED)
        )
        silver.claim_bronze(limit=1000)
        assert _status(silver.session, doc_id) == (ProcessingStatus.PROCESSING, None)

    def test_mark_bronze_failed_on_missing_row_raises(self, silver: SilverRepository) -> None:
        with pytest.raises(LookupError):
            silver.mark_bronze_failed(9_999_999, "boom")

    def test_release_stale_requeues_only_old_claims(
        self, silver: SilverRepository, bronze: BronzeRepository
    ) -> None:
        stale_id, fresh_id = _queued_doc(bronze, 1), _queued_doc(bronze, 2)
        silver.claim_bronze(limit=1000)
        # The worker holding stale_id died an hour ago.
        silver.session.execute(
            update(CrawledDocument)
            .where(CrawledDocument.id == stale_id)
            .values(updated_at=func.now() - timedelta(hours=1))
        )

        assert silver.release_stale(timedelta(minutes=30)) >= 1
        assert _status(silver.session, stale_id)[0] == ProcessingStatus.UNPROCESSED
        assert _status(silver.session, fresh_id)[0] == ProcessingStatus.PROCESSING


@pytest.fixture()
def committed_bronze_rows() -> Iterator[list[int]]:
    """Four Bronze rows committed for real, so a second connection can see them.

    The usual `session` fixture never commits, which makes its rows invisible to
    other connections -- useless for testing row locks. Dated 1980 so they sort
    ahead of anything else in the queue.
    """
    engine = make_engine()
    run = uuid.uuid4()
    ids: list[int] = []
    with Session(engine) as s:
        repo = BronzeRepository(s)
        for n in range(4):
            url = f"https://{HOST}/lock-test/{run}/{n}"
            doc = bronze_doc(url=url, normalized_url=url, fetched_at=f"1980-01-0{n + 1}T00:00:00Z")
            ids.append(repo.save_document(doc, resolve_domain=False).id)
        s.commit()
    try:
        yield ids
    finally:
        with Session(engine) as s:
            s.execute(delete(CrawledDocument).where(CrawledDocument.id.in_(ids)))
            s.commit()
        engine.dispose()


class TestConcurrentClaims:
    def test_two_open_workers_claim_disjoint_rows(
        self, committed_bronze_rows: list[int]
    ) -> None:
        ours = set(committed_bronze_rows)
        engine = make_engine()
        try:
            with Session(engine) as worker_a, Session(engine) as worker_b:
                a = {d.id for d in SilverRepository(worker_a).claim_bronze(limit=2)}
                assert a == set(committed_bronze_rows[:2])  # the two oldest

                # Worker A has not committed. B must skip A's locked rows rather
                # than wait on them (lock_timeout turns a wait into a failure).
                worker_b.execute(select(func.set_config("lock_timeout", "2s", True)))
                b = {d.id for d in SilverRepository(worker_b).claim_bronze(limit=1000)} & ours

                assert a.isdisjoint(b)
                assert a | b == ours  # and nothing was left behind

                worker_b.rollback()
                worker_a.rollback()
        finally:
            engine.dispose()

    def test_a_committed_claim_is_not_reclaimed(self, committed_bronze_rows: list[int]) -> None:
        ours = set(committed_bronze_rows)
        engine = make_engine()
        try:
            with Session(engine) as worker_a:
                a = {d.id for d in SilverRepository(worker_a).claim_bronze(limit=2)}
                worker_a.commit()  # the claim is durable and A's locks are released
            with Session(engine) as worker_b:
                b = {d.id for d in SilverRepository(worker_b).claim_bronze(limit=1000)} & ours
                worker_b.rollback()
            assert a.isdisjoint(b)
            assert a | b == ours
        finally:
            engine.dispose()


class TestRollback:
    def test_failed_child_write_rolls_back_the_page(self, session: Session) -> None:
        bronze_repo = BronzeRepository(session)
        silver_repo = SilverRepository(session)
        doc_id = bronze_repo.save_document(bronze_doc(), resolve_domain=False).id
        session.flush()

        savepoint = session.begin_nested()
        result = silver_repo.save_page(etl_payload(), crawled_document_id=doc_id)
        session.flush()
        savepoint.rollback()

        assert session.get(Page, result.id) is None
        assert count(session, Page) == 0
        assert count(session, PageGeoTag) == 0
        assert count(session, PageContact) == 0
        # Bronze is untouched by the Silver rollback.
        assert session.get(CrawledDocument, doc_id) is not None

    def test_session_recovers_after_an_integrity_error(self, session: Session) -> None:
        bronze_repo = BronzeRepository(session)
        silver_repo = SilverRepository(session)
        doc_id = bronze_repo.save_document(bronze_doc(), resolve_domain=False).id
        session.flush()

        savepoint = session.begin_nested()
        with pytest.raises(IntegrityError):
            silver_repo.save_page(etl_payload(), crawled_document_id=9_999_999)
            session.flush()
        savepoint.rollback()

        result = silver_repo.save_page(etl_payload(), crawled_document_id=doc_id)
        session.flush()
        assert result.inserted
        assert count(session, Page) == 1


class TestGazetteerIsSeeded:
    """Silver geo tags reference the Phase 1 gazetteer by code."""

    def test_pokhara_is_seeded(self, session: Session) -> None:
        if not count(session, LocalBody):
            pytest.skip("geography not seeded; run scripts/seed_geography.py")
        assert session.scalar(select(LocalBody.id).where(LocalBody.code == "MUN414"))
