"""search_documents / page_geo_codes views and SearchRepository (index queue, vector search)."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository, SearchRepository, SilverRepository
from pgs_db.enums import Language, ProcessingStatus
from pgs_db.models import Page, page_geo_codes, search_documents
from pgs_db.schemas import SearchDocumentOut, VectorHit

HOST = "searchsite.gov.np"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # MODEL's size
_ANCIENT = datetime(1975, 1, 1, tzinfo=UTC)

# Seeded gazetteer: Kaski is D38 in Gandaki (P4); Pokhara is MUN414 inside it.
KASKI, GANDAKI, POKHARA = "D38", "P4", "MUN414"


@pytest.fixture()
def bronze(session: Session) -> BronzeRepository:
    return BronzeRepository(session)


@pytest.fixture()
def silver(session: Session) -> SilverRepository:
    return SilverRepository(session)


@pytest.fixture()
def search(session: Session) -> SearchRepository:
    return SearchRepository(session)


def unit(i: int) -> list[float]:
    """A unit vector along axis i: cosine similarity 1 with itself, 0 with other axes."""
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


def blend(i: int, j: int, weight_i: float) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i], v[j] = weight_i, math.sqrt(1 - weight_i**2)
    return v


def make_page(
    bronze: BronzeRepository,
    silver: SilverRepository,
    n: int,
    *,
    geo: list[dict[str, Any]] | None = None,
    **payload: Any,
) -> int:
    url = f"https://www.{HOST}/p/{n}"
    doc_id = bronze.save_document(
        {
            "url": url,
            "normalized_url": url,
            "host": f"www.{HOST}",
            "content_hash": f"{n:064x}",
            "fetched_at": (_ANCIENT + timedelta(days=n)).isoformat(),
        }
    ).id
    body: dict[str, Any] = {
        "searchable_text": f"body {n}",
        "content_hash": f"{n:064x}",
        "extracted_metadata": {"title": f"Page {n}"},
        "language_detected": "ne",
    }
    body.update(payload)
    if geo is not None:
        body["geo_location"] = geo
    page_id = silver.save_page(body, crawled_document_id=doc_id).id
    return page_id


def embed(silver: SilverRepository, page_id: int, *vectors: list[float]) -> None:
    silver.replace_embeddings(
        page_id, MODEL, [{"text": f"chunk {i}", "vector": v} for i, v in enumerate(vectors)]
    )


class TestViews:
    def test_a_tag_on_a_municipality_gets_its_district_and_province(
        self, bronze: BronzeRepository, silver: SilverRepository
    ) -> None:
        page_id = make_page(
            bronze, silver, 1, geo=[{"municipality_id": POKHARA, "method": "GAZETTEER",
                                     "confidence": 0.9}]
        )
        row = silver.session.execute(
            select(page_geo_codes).where(page_geo_codes.c.page_id == page_id)
        ).one()
        assert (row.province_code, row.district_code, row.local_body_code) == (
            GANDAKI,
            KASKI,
            POKHARA,
        )

    def test_one_flat_row_per_canonical_page_with_its_primary_location(
        self, bronze: BronzeRepository, silver: SilverRepository
    ) -> None:
        page_id = make_page(
            bronze,
            silver,
            2,
            geo=[
                {"district_code": KASKI, "method": "GAZETTEER", "confidence": 0.9},
                # Same confidence, more specific: this one is primary.
                {"municipality_id": POKHARA, "ward_number": 8, "method": "GAZETTEER",
                 "confidence": 0.9},
                {"province_code": "P3", "method": "NER", "confidence": 0.4},
            ],
        )
        rows = silver.session.execute(
            select(search_documents).where(search_documents.c.page_id == page_id)
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.local_body_code, row.district_code, row.province_code, row.ward_number) == (
            POKHARA,
            KASKI,
            GANDAKI,
            8,
        )
        assert row.domain == HOST  # "www." stripped, no domains row needed
        assert (row.title, row.index_status) == ("Page 2", ProcessingStatus.UNPROCESSED.value)
        assert row.file_extension is None

    def test_duplicates_are_left_out(
        self, bronze: BronzeRepository, silver: SilverRepository
    ) -> None:
        canonical = make_page(bronze, silver, 3)
        duplicate = make_page(bronze, silver, 4)
        silver.mark_duplicate_of(duplicate, canonical)
        # A Core select on a view does not autoflush pending ORM changes.
        silver.session.flush()
        ids = set(
            silver.session.scalars(
                select(search_documents.c.page_id).where(
                    search_documents.c.page_id.in_([canonical, duplicate])
                )
            )
        )
        assert ids == {canonical}

    def test_stored_files_carry_file_details(
        self, bronze: BronzeRepository, silver: SilverRepository
    ) -> None:
        file_id = bronze.save_stored_file(
            {
                "source_page_url": f"https://{HOST}/notices",
                "document_url": f"https://{HOST}/uploads/Budget_2080.PDF?v=2",
                "storage_path": "raw/budget.pdf",
                "content_type": "application/pdf",
                "sha256": "5" * 64,
                "size": 3_250_585,
                "stored_at": _ANCIENT.isoformat(),
            }
        ).id
        page_id = silver.save_page(
            {"searchable_text": "budget", "content_hash": "b" * 64, "content_type": "document"},
            stored_file_id=file_id,
        ).id
        row = silver.session.execute(
            select(search_documents).where(search_documents.c.page_id == page_id)
        ).one()
        assert (row.file_extension, row.file_mime_type, row.file_size_bytes) == (
            "pdf",
            "application/pdf",
            3_250_585,
        )


class TestDocuments:
    def test_documents_match_the_search_teams_shape(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        page_id = make_page(
            bronze,
            silver,
            10,
            geo=[
                {"municipality_id": POKHARA, "method": "DOMAIN", "confidence": 1.0},
                {"district_code": "D01", "method": "NER", "confidence": 0.3},
            ],
            extracted_metadata={"title": "Page 10", "keywords": ["budget"]},
        )
        [doc] = search.documents([page_id])
        out = SearchDocumentOut.model_validate(doc)

        assert out.document_id == str(page_id)
        assert (out.searchable_text, out.language, out.domain) == ("body 10", "ne", HOST)
        assert out.keywords == ["budget"]
        assert out.geo.municipality_id == POKHARA
        assert out.geo.district_name_en == "Kaski"
        assert [g.district_code for g in out.geo_tags] == [KASKI, "D01"]
        assert out.file_info is None

    def test_unknown_and_duplicate_ids_are_skipped_and_order_is_kept(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        a = make_page(bronze, silver, 11)
        b = make_page(bronze, silver, 12)
        assert [d["document_id"] for d in search.documents([b, 9_999_999, a])] == [str(b), str(a)]
        assert search.documents([]) == []

    def test_untagged_page_gets_an_empty_geo_block(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        [doc] = search.documents([make_page(bronze, silver, 13)])
        assert doc["geo"]["province_code"] is None and doc["geo_tags"] == []


class TestIndexQueue:
    def test_claim_marks_pages_processing_and_mark_processed_finishes_them(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        # Park everything already queued in the dev database so only ours is claimable.
        silver.session.execute(
            update(Page)
            .where(Page.processing_status == ProcessingStatus.UNPROCESSED)
            .values(processing_status=ProcessingStatus.PROCESSED)
        )
        first = make_page(bronze, silver, 20)
        second = make_page(bronze, silver, 21)

        claimed = search.claim_for_indexing(limit=10)
        assert [d["document_id"] for d in claimed] == [str(first), str(second)]
        assert search.claim_for_indexing(limit=10) == []

        silver.mark_processed(first)
        silver.mark_processed(second, error="mapping rejected")
        statuses = dict(
            silver.session.execute(
                select(Page.id, Page.processing_status).where(Page.id.in_([first, second]))
            ).all()
        )
        assert statuses == {first: ProcessingStatus.PROCESSED, second: ProcessingStatus.FAILED}

    def test_stale_claims_are_released(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        page_id = make_page(bronze, silver, 22)
        silver.session.execute(
            update(Page)
            .where(Page.id == page_id)
            .values(processing_status=ProcessingStatus.PROCESSING, updated_at=_ANCIENT)
        )
        assert search.release_stale_indexing(timedelta(hours=1)) >= 1
        status = silver.session.scalar(select(Page.processing_status).where(Page.id == page_id))
        assert status == ProcessingStatus.UNPROCESSED


class TestVectorSearch:
    def test_best_chunk_per_page_ranks_the_results(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        near = make_page(bronze, silver, 30)
        far = make_page(bronze, silver, 31)
        embed(silver, near, unit(5), blend(0, 5, 0.99))  # second chunk is the close one
        embed(silver, far, blend(0, 6, 0.5))

        hits = search.vector_search(unit(0), MODEL, limit=5)
        ours = [h for h in hits if h["page_id"] in (near, far)]
        assert [h["page_id"] for h in ours] == [near, far]
        assert ours[0]["score"] == pytest.approx(0.99, abs=1e-4)
        VectorHit.model_validate(ours[0])

    def test_geo_filter_matches_any_tag_inside_the_region(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        in_pokhara = make_page(
            bronze, silver, 32,
            geo=[{"municipality_id": POKHARA, "method": "GAZETTEER", "confidence": 0.9}],
        )
        elsewhere = make_page(
            bronze, silver, 33,
            geo=[{"district_code": "D01", "method": "GAZETTEER", "confidence": 0.9}],
        )
        # Primary location is elsewhere, but a weaker tag puts it in Kaski too.
        also_kaski = make_page(
            bronze, silver, 34,
            geo=[
                {"district_code": "D01", "method": "GAZETTEER", "confidence": 0.9},
                {"district_code": KASKI, "method": "NER", "confidence": 0.2},
            ],
        )
        for page_id in (in_pokhara, elsewhere, also_kaski):
            embed(silver, page_id, unit(1))

        kaski = {h["page_id"] for h in search.vector_search(unit(1), MODEL, district_code=KASKI,
                                                            limit=50)}
        assert {in_pokhara, also_kaski} <= kaski and elsewhere not in kaski

        gandaki = {h["page_id"] for h in search.vector_search(unit(1), MODEL,
                                                              province_code=GANDAKI, limit=50)}
        assert in_pokhara in gandaki and elsewhere not in gandaki

        pokhara = {h["page_id"] for h in search.vector_search(unit(1), MODEL,
                                                              local_body_code=POKHARA, limit=50)}
        assert pokhara >= {in_pokhara} and also_kaski not in pokhara

    def test_language_content_type_and_stale_embeddings(
        self, bronze: BronzeRepository, silver: SilverRepository, search: SearchRepository
    ) -> None:
        nepali = make_page(bronze, silver, 35)
        english = make_page(bronze, silver, 36, language_detected="en")
        embed(silver, nepali, unit(2))
        embed(silver, english, unit(2))

        hits = {h["page_id"] for h in search.vector_search(unit(2), MODEL, language=Language.EN,
                                                           limit=50)}
        assert english in hits and nepali not in hits
        assert not search.vector_search(unit(2), MODEL, content_type="no-such-type")

        # New content without a fresh embedding: the old vector no longer counts.
        silver.session.execute(
            update(Page).where(Page.id == english).values(content_hash="f" * 64)
        )
        hits = {h["page_id"] for h in search.vector_search(unit(2), MODEL, limit=50)}
        assert english not in hits and nepali in hits

    def test_wrong_dimension_is_rejected(self, search: SearchRepository) -> None:
        with pytest.raises(ValueError, match="dimensions"):
            search.vector_search([1.0, 0.0], MODEL)
