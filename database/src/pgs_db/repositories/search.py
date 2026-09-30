"""What the search team reads: the indexing queue and filtered vector search.

Built on the `search_documents` and `page_geo_codes` views, so there is nothing to
refresh: a page is searchable as soon as Silver saves it.

- The **indexer** (Postgres -> OpenSearch) calls `claim_for_indexing`, indexes the
  returned documents, then `SilverRepository.mark_processed(page_id)` for each (or
  with `error=` on failure). Every Silver save re-queues the page, so edits reach
  the index without a separate change feed.
- **Vector search** (`pgvector_search.py`) calls `vector_search` instead of
  `SELECT ... FROM documents`: same idea, our tables, geo filters on every tag.

Documents come back in the search team's `SearchDocument` shape
(`pgs_search.models.document`), plus the extra blocks the API's result card needs.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, cast, exists, func, select, update
from sqlalchemy.orm import Session, joinedload

from ..enums import Language, ProcessingStatus, QuarantineStatus
from ..models import (
    Page,
    PageEmbedding,
    PageGeoTag,
    QuarantinedFile,
    StoredFile,
    page_geo_codes,
    search_documents,
)
from ..schemas.silver import GeoLocationOut
from .silver import SilverRepository

# pgs_search's SearchDocument.language values.
_LANGUAGE = {
    Language.NE: "ne",
    Language.EN: "en",
    Language.MIXED: "mixed",
    Language.OTHER: "unknown",
}

_DOC = search_documents.c


def search_language(value: str | None) -> str:
    """`NE` -> `ne`, and so on; anything unknown is `unknown`, as pgs_search expects."""
    try:
        return _LANGUAGE[Language(value)]
    except ValueError:
        return "unknown"


class SearchRepository:
    """Indexing queue and vector search for one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- documents

    def documents(self, page_ids: Sequence[int]) -> list[dict[str, Any]]:
        """`SearchDocument`-shaped dicts for these pages, in the order given.

        Duplicates and unknown ids are skipped. Each document carries:

        - the `SearchDocument` fields (`document_id`, `title`, `searchable_text`,
          `source_url`, `domain`, `language`, `content_type`, `published_at`,
          `keywords`, and `geo` = the primary location with gazetteer names);
        - `geo_tags`: every location, so OpenSearch can filter on any of them;
        - `file_info`: extension, MIME type and size for PDFs and other files, else None.
        """
        if not page_ids:
            return []
        rows = {
            row.page_id: row
            for row in self.session.execute(
                select(search_documents, Page.body_text)
                .join(Page, Page.id == _DOC.page_id)
                .where(_DOC.page_id.in_(page_ids))
            ).all()
        }
        tags: dict[int, list[PageGeoTag]] = {}
        for tag in self.session.scalars(
            select(PageGeoTag)
            .where(PageGeoTag.page_id.in_(rows))
            .options(
                joinedload(PageGeoTag.province),
                joinedload(PageGeoTag.district),
                joinedload(PageGeoTag.local_body),
            )
            .order_by(PageGeoTag.confidence.desc(), PageGeoTag.id)
        ):
            tags.setdefault(tag.page_id, []).append(tag)
        return [self._document(rows[pid], tags.get(pid, [])) for pid in page_ids if pid in rows]

    @staticmethod
    def _document(row: Any, tags: list[PageGeoTag]) -> dict[str, Any]:
        geo_tags = [GeoLocationOut.from_tag(tag).model_dump() for tag in tags]
        primary = next(
            (
                geo
                for geo in geo_tags
                if (geo["municipality_id"], geo["district_code"], geo["province_code"])
                == (row.local_body_code, row.district_code, row.province_code)
                and geo["ward_number"] == row.ward_number
            ),
            GeoLocationOut().model_dump(),
        )
        file_info = None
        if row.file_mime_type is not None or row.file_size_bytes is not None:
            file_info = {
                "extension": row.file_extension,
                "mime_type": row.file_mime_type,
                "size_bytes": row.file_size_bytes,
            }
        return {
            "document_id": str(row.page_id),
            "title": row.title or row.url,
            "description": row.description,
            "searchable_text": row.body_text,
            "source_url": row.url,
            "domain": row.domain or "",
            "language": search_language(row.language),
            "content_type": row.content_type,
            "category": row.category,
            "published_at": row.published_at,
            "keywords": list(row.keywords or []),
            "geo": primary,
            "geo_tags": geo_tags,
            "file_info": file_info,
        }

    # ------------------------------------------------------------ index queue

    def claim_for_indexing(self, limit: int = 100) -> list[dict[str, Any]]:
        """Claim up to `limit` canonical pages waiting for the search index, oldest change first.

        Moves them UNPROCESSED -> PROCESSING with SKIP LOCKED, so parallel indexers
        never take the same page. Commit the claim before the slow indexing work.
        Finish each page with `SilverRepository.mark_processed`.
        """
        # MATERIALIZED so the LIMIT ... SKIP LOCKED pick runs once (see SilverRepository._claim).
        claimed = (
            select(Page.id)
            .where(
                Page.processing_status == ProcessingStatus.UNPROCESSED,
                Page.duplicate_of_id.is_(None),
            )
            .order_by(Page.updated_at, Page.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("candidates")
            .prefix_with("MATERIALIZED")
        )
        ids = list(
            self.session.scalars(
                update(Page)
                .where(Page.id == claimed.c.id)
                .values(processing_status=ProcessingStatus.PROCESSING, updated_at=func.now())
                .returning(Page.id),
                execution_options={"synchronize_session": False},
            )
        )
        return self.documents(sorted(ids))

    def release_stale_indexing(self, older_than: timedelta) -> int:
        """Return pages stuck in PROCESSING longer than `older_than` to the index queue.

        For an indexer that died after committing its claim. Returns pages released.
        """
        result = self.session.execute(
            update(Page)
            .where(
                Page.processing_status == ProcessingStatus.PROCESSING,
                Page.updated_at < func.now() - older_than,
            )
            .values(processing_status=ProcessingStatus.UNPROCESSED),
            execution_options={"synchronize_session": False},
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # --------------------------------------------------------------- downloads

    def file_location(self, page_id: int) -> dict[str, Any] | None:
        """Where a document result's file lives, for `GET /user/documents/download/{id}`.

        None when the page is not a stored file, is a duplicate, or its file was
        quarantined -- the API must answer 404, never stream it. The API streams the
        object from MinIO at `storage_path`; `filename` is for Content-Disposition.
        """
        row = self.session.execute(
            select(StoredFile)
            .join(Page, Page.stored_file_id == StoredFile.id)
            .where(Page.id == page_id, Page.duplicate_of_id.is_(None))
        ).scalar_one_or_none()
        if row is None:
            return None
        quarantined = self.session.scalar(
            select(QuarantinedFile.id).where(
                QuarantinedFile.sha256 == row.sha256,
                QuarantinedFile.status == QuarantineStatus.QUARANTINED,
            ).limit(1)
        )
        if quarantined is not None:
            return None
        filename = row.document_url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "download"
        return {
            "page_id": page_id,
            "storage_path": row.storage_path,
            "mime_type": row.content_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "filename": filename,
        }

    # ------------------------------------------------------------ vector search

    def vector_search(
        self,
        vector: Sequence[float],
        model_name: str | None = None,
        *,
        province_code: str | None = None,
        district_code: str | None = None,
        local_body_code: str | None = None,
        municipality_id: str | None = None,
        ward_number: int | None = None,
        content_type: str | None = None,
        language: Language | str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Canonical pages closest to `vector`, best chunk per page, with the filters applied.

        `model_name` defaults to the registered default model (LaBSE); the query vector
        must come from the same model. A geo filter matches a page tagged anywhere
        inside that region: `district_code` finds pages tagged with any of its
        municipalities too. Only embeddings of the page's current content count.
        `score` is cosine similarity (1 = identical).

        Takes the search proto's `SearchRequest` values as they arrive:
        `municipality_id` is `local_body_code`; "" and ward 0 mean "no filter";
        `content_type="all"` and `language="auto"` mean no filter.

        Exact search: every matching chunk is scored, which is right for filtered
        queries at the current corpus size. Past a few million chunks, switch the
        unfiltered case to the HNSW index (`SilverRepository.nearest_chunks`).
        """
        model = SilverRepository(self.session).embedding_model(model_name)
        if len(vector) != model.dimensions:
            raise ValueError(
                f"vector must have {model.dimensions} dimensions for {model.name}, "
                f"got {len(vector)}"
            )
        local_body_code = local_body_code or municipality_id or None
        province_code, district_code = province_code or None, district_code or None
        ward_number = ward_number or None
        if content_type in ("", "all"):
            content_type = None
        if isinstance(language, str) and language.lower() in ("", "auto", "all"):
            language = None
        distance = cast(PageEmbedding.embedding, Vector(model.dimensions)).cosine_distance(
            list(vector)
        )
        conditions = [
            PageEmbedding.model_name == model.name,
            PageEmbedding.content_hash == _DOC.content_hash,
        ]
        if content_type is not None:
            conditions.append(_DOC.content_type == content_type)
        if language is not None:
            conditions.append(_DOC.language == Language(str(language).upper()).value)
        geo = page_geo_codes.c
        geo_filters = [
            column == value
            for column, value in (
                (geo.province_code, province_code),
                (geo.district_code, district_code),
                (geo.local_body_code, local_body_code),
                (geo.ward_number, ward_number),
            )
            if value is not None
        ]
        if geo_filters:
            conditions.append(
                exists().where(and_(geo.page_id == PageEmbedding.page_id, *geo_filters))
            )
        best = (
            select(PageEmbedding.page_id, func.min(distance).label("distance"))
            .join(search_documents, _DOC.page_id == PageEmbedding.page_id)
            .where(*conditions)
            .group_by(PageEmbedding.page_id)
            .order_by(func.min(distance), PageEmbedding.page_id)
            .limit(limit)
            .subquery()
        )
        rows = self.session.execute(
            select(
                _DOC.page_id,
                _DOC.title,
                _DOC.url,
                _DOC.domain,
                _DOC.content_type,
                _DOC.province_code,
                _DOC.district_code,
                _DOC.local_body_code,
                _DOC.ward_number,
                best.c.distance,
            )
            .join(best, best.c.page_id == _DOC.page_id)
            .order_by(best.c.distance, _DOC.page_id)
        ).all()
        return [
            {
                "page_id": row.page_id,
                "title": row.title,
                "url": row.url,
                "domain": row.domain,
                "content_type": row.content_type,
                "province_code": row.province_code,
                "district_code": row.district_code,
                "local_body_code": row.local_body_code,
                "ward_number": row.ward_number,
                "score": 1.0 - float(row.distance),
            }
            for row in rows
        ]
