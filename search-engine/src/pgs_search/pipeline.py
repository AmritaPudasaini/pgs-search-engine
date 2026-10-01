"""Final search orchestration for retrieval, fusion, reranking, and pagination."""

from __future__ import annotations

import logging
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from opensearchpy.exceptions import OpenSearchException
from psycopg2 import Error as PsycopgError

from pgs_search.client.opensearch import get_opensearch_client
from pgs_search.config import settings
from pgs_search.ranking.lightgbm_reranker import rerank_results
from pgs_search.retrieval.lexical import search_bm25

logger = logging.getLogger(__name__)

BACKEND_ERRORS = (
    ConnectionError,
    OpenSearchException,
    OSError,
    PsycopgError,
    RuntimeError,
    TimeoutError,
    ValueError,
)

TEXT_FIELDS = ("title", "description", "searchable_text")
GEO_FIELDS = ("province_code", "district_code", "municipality_id", "ward_number")
GEO_FIELD_MAP = {
    "province_code": "geo.province_code",
    "district_code": "geo.district_code",
    "municipality_id": "geo.municipality_id",
    "ward_number": "geo.ward_number",
}
ACTIVE_CONTENT_TYPE_SENTINELS = {"", "all"}
ACTIVE_LANGUAGE_SENTINELS = {"", "auto"}
SNIPPET_LENGTH = 240

Candidate = dict[str, Any]


class SearchInputLike(Protocol):
    query: str
    province_code: str
    district_code: str
    municipality_id: str
    ward_number: int
    content_type: str
    language: str
    page: int
    limit: int


@dataclass(frozen=True, slots=True)
class PipelineHit:
    id: str
    result_type: str
    title: str
    url: str
    domain: str
    snippet: str
    download_url: str
    file_size_bytes: int
    relevance_score: float


@dataclass(frozen=True, slots=True)
class PipelineOutput:
    total_hits: int
    results: list[PipelineHit]
    opensearch_vector_status: str
    pgvector_hydrated_ids: set[str]


Bm25Search = Callable[[Any, str, int, Sequence[dict[str, Any]] | None], list[dict[str, Any]]]
VectorSearch = Callable[[str, int], list[dict[str, Any]]]
Reranker = Callable[[list[dict[str, Any]], int], list[dict[str, Any]]]


class FinalSearchPipeline:
    """Coordinates the current retrieval, fusion, and ranking components."""

    def __init__(
        self,
        *,
        opensearch_client: Any | None = None,
        bm25_search: Bm25Search | None = None,
        pgvector_search: VectorSearch | None = None,
        opensearch_vector_search: VectorSearch | None = None,
        reranker: Reranker | None = None,
        hybrid_searcher: Any | None = None,
    ) -> None:
        self._opensearch_client = opensearch_client
        self._bm25_search = bm25_search or search_bm25
        self._pgvector_search = pgvector_search or _default_pgvector_search
        self._opensearch_vector_search = opensearch_vector_search or _default_opensearch_vector_search
        self._reranker = reranker or rerank_results
        self._hybrid_searcher = hybrid_searcher

    def search(self, search_input: SearchInputLike) -> PipelineOutput:
        """Execute the full search pipeline and return page-sliced hits."""
        client = self._get_opensearch_client()
        requested = _requested_count(search_input)
        filters = build_filter_clauses(search_input)

        bm25_raw = self._bm25_search(client, search_input.query, requested, filters)
        bm25_candidates = [normalize_bm25_hit(hit) for hit in bm25_raw]

        pgvector_candidates = self._fetch_pgvector_candidates(search_input.query, requested)
        opensearch_vector_candidates, vector_status = self._fetch_opensearch_vector_candidates(
            client,
            search_input.query,
            requested,
        )

        vector_candidates = [*pgvector_candidates, *opensearch_vector_candidates]
        known_candidates = merge_candidates([*bm25_candidates, *opensearch_vector_candidates])
        hydrated_ids = self._hydrate_vector_candidates(client, vector_candidates, known_candidates)

        pgvector_candidates = [
            candidate
            for candidate in pgvector_candidates
            if candidate_has_returnable_metadata(candidate)
            and candidate_matches_filters(candidate, search_input)
        ]
        opensearch_vector_candidates = [
            candidate
            for candidate in opensearch_vector_candidates
            if candidate_has_returnable_metadata(candidate)
            and candidate_matches_filters(candidate, search_input)
        ]

        all_candidates = merge_candidates(
            [*bm25_candidates, *pgvector_candidates, *opensearch_vector_candidates]
        )
        fused = self._fuse(
            list(all_candidates.values()),
            bm25_candidates,
            pgvector_candidates,
            opensearch_vector_candidates,
            requested,
        )
        feature_ready = [with_lightgbm_features(candidate, search_input) for candidate in fused]
        ranked = self._rerank_or_fallback(feature_ready)

        total_hits = len(ranked)
        start = (max(search_input.page, 1) - 1) * max(search_input.limit, 1)
        end = start + max(search_input.limit, 1)
        return PipelineOutput(
            total_hits=total_hits,
            results=[candidate_to_hit(candidate) for candidate in ranked[start:end]],
            opensearch_vector_status=vector_status,
            pgvector_hydrated_ids=hydrated_ids,
        )

    def _get_opensearch_client(self) -> Any:
        if self._opensearch_client is None:
            self._opensearch_client = get_opensearch_client()
        return self._opensearch_client

    def _fetch_pgvector_candidates(self, query: str, top_k: int) -> list[Candidate]:
        try:
            results = self._pgvector_search(query, top_k)
        except BACKEND_ERRORS as exc:  # pragma: no cover - exercised in live integration paths.
            logger.warning("Skipping PGVector retrieval after backend error: %s", exc)
            return []
        return [normalize_vector_result(result, "pgvector") for result in results]

    def _fetch_opensearch_vector_candidates(
        self,
        client: Any,
        query: str,
        top_k: int,
    ) -> tuple[list[Candidate], str]:
        has_mapping, reason = has_compatible_opensearch_vector_mapping(client)
        if not has_mapping:
            logger.info("Skipping OpenSearch vector retrieval: %s", reason)
            return [], f"skipped: {reason}"

        try:
            results = self._opensearch_vector_search(query, top_k)
        except BACKEND_ERRORS as exc:  # pragma: no cover - backend-specific path.
            logger.warning("Skipping OpenSearch vector retrieval after backend error: %s", exc)
            return [], f"skipped: {exc}"

        return [normalize_vector_result(result, "opensearch") for result in results], "active"

    def _hydrate_vector_candidates(
        self,
        client: Any,
        vector_candidates: list[Candidate],
        known_candidates: dict[str, Candidate],
    ) -> set[str]:
        ids_to_hydrate = [
            str(candidate["document_id"])
            for candidate in vector_candidates
            if str(candidate["document_id"]) not in known_candidates
        ]
        hydrated = hydrate_candidates(client, ids_to_hydrate)
        hydrated_ids = set(hydrated)

        for candidate in vector_candidates:
            document_id = str(candidate["document_id"])
            metadata = known_candidates.get(document_id) or hydrated.get(document_id)
            if metadata:
                merge_candidate_data(candidate, metadata)
            elif not candidate_has_returnable_metadata(candidate):
                logger.info("Skipping vector candidate %s because metadata hydration missed.", document_id)

        return hydrated_ids

    def _fuse(
        self,
        merged_candidates: list[Candidate],
        bm25_candidates: list[Candidate],
        pgvector_candidates: list[Candidate],
        opensearch_vector_candidates: list[Candidate],
        top_k: int,
    ) -> list[Candidate]:
        if not merged_candidates:
            return []

        merged_by_id = {str(candidate["document_id"]): candidate for candidate in merged_candidates}
        fused = self._get_hybrid_searcher().fuse(
            bm25_candidates,
            pgvector_candidates,
            opensearch_vector_candidates,
            top_k=top_k,
        )

        output = []
        for result in fused:
            document_id = str(result["document_id"])
            candidate = merged_by_id.get(document_id, result).copy()
            merge_candidate_data(candidate, result)
            output.append(candidate)
        return output

    def _get_hybrid_searcher(self) -> Any:
        if self._hybrid_searcher is None:
            self._hybrid_searcher = _default_hybrid_searcher()
        return self._hybrid_searcher

    def _rerank_or_fallback(self, candidates: list[Candidate]) -> list[Candidate]:
        if not candidates:
            return []

        try:
            return self._reranker(candidates, top_k=len(candidates))
        except FileNotFoundError as exc:
            logger.warning("LightGBM model unavailable; returning RRF order: %s", exc)
            return candidates


def build_filter_clauses(search_input: SearchInputLike) -> list[dict[str, Any]]:
    """Build exact OpenSearch filters for real np_web_pages fields."""
    filters: list[dict[str, Any]] = []
    for field, value in _geo_constraints(search_input).items():
        filters.append({"term": {GEO_FIELD_MAP[field]: value}})

    content_type = _active_content_type(search_input.content_type)
    if content_type:
        filters.append({"term": {"content_type": content_type}})

    language = _active_language(search_input.language)
    if language:
        filters.append({"term": {"language": language}})

    return filters


def normalize_bm25_hit(hit: Mapping[str, Any]) -> Candidate:
    """Normalize a raw OpenSearch hit into the internal candidate schema."""
    source = _mapping(hit.get("_source"))
    document_id = source.get("document_id", hit.get("_id"))
    candidate = _candidate_from_source(str(document_id), source)
    candidate["bm25_score"] = _safe_float(hit.get("_score"))
    candidate["retrieval_sources"] = {"bm25"}
    return candidate


def normalize_vector_result(result: Mapping[str, Any], backend: str) -> Candidate:
    """Normalize PGVector/OpenSearch-vector output into the internal schema."""
    document_id = str(result.get("document_id", ""))
    return {
        "document_id": document_id,
        "vector_score": _safe_float(result.get("vector_score")),
        "rank": result.get("rank", 0),
        "retrieval_sources": {backend},
    }


def merge_candidates(candidates: Sequence[Candidate]) -> dict[str, Candidate]:
    """Merge duplicate candidate records while preserving metadata and best scores."""
    merged: dict[str, Candidate] = {}
    for candidate in candidates:
        document_id = str(candidate.get("document_id", ""))
        if not document_id:
            continue
        existing = merged.setdefault(document_id, {"document_id": document_id})
        merge_candidate_data(existing, candidate)
    return merged


def merge_candidate_data(target: Candidate, incoming: Mapping[str, Any]) -> Candidate:
    """Merge scores and metadata from incoming into target."""
    for key, value in incoming.items():
        if key == "retrieval_sources":
            sources = target.setdefault("retrieval_sources", set())
            if isinstance(sources, set):
                sources.update(cast(set[str], value))
            continue

        if key in {"bm25_score", "vector_score", "fusion_score", "rerank_score"}:
            current = _safe_float(target.get(key))
            target[key] = max(current, _safe_float(value))
            continue

        if key == "geo":
            if not target.get("geo") and isinstance(value, dict):
                target[key] = value
            continue

        if value not in (None, "", [], {}) and target.get(key) in (None, "", [], {}):
            target[key] = value

    return target


def hydrate_candidates(client: Any, document_ids: Sequence[str]) -> dict[str, Candidate]:
    """Fetch OpenSearch metadata for vector-only IDs in one mget request."""
    unique_ids = list(dict.fromkeys(str(document_id) for document_id in document_ids if document_id))
    if not unique_ids or not hasattr(client, "mget"):
        return {}

    response = client.mget(index=settings.opensearch_index, body={"ids": unique_ids})
    docs = response.get("docs", []) if isinstance(response, dict) else []
    hydrated: dict[str, Candidate] = {}
    for doc in docs:
        if not isinstance(doc, dict) or not doc.get("found", False):
            continue
        source = _mapping(doc.get("_source"))
        document_id = str(source.get("document_id", doc.get("_id", "")))
        if document_id:
            hydrated[document_id] = _candidate_from_source(document_id, source)
    return hydrated


def has_compatible_opensearch_vector_mapping(client: Any) -> tuple[bool, str]:
    """Return whether the configured index has a usable embedding knn_vector field."""
    indices = getattr(client, "indices", None)
    if indices is None or not hasattr(indices, "get_mapping"):
        return False, "OpenSearch client cannot inspect mappings"

    try:
        mapping_response = indices.get_mapping(index=settings.opensearch_index)
    except BACKEND_ERRORS as exc:  # pragma: no cover - backend-specific path.
        return False, f"mapping unavailable: {exc}"

    index_mapping = _mapping(mapping_response).get(settings.opensearch_index, {})
    properties = _mapping(_mapping(index_mapping).get("mappings")).get("properties", {})
    embedding = _mapping(properties).get("embedding")
    if not isinstance(embedding, dict):
        return False, "embedding field is absent"

    if embedding.get("type") != "knn_vector":
        return False, "embedding field is not a knn_vector"

    return True, "embedding knn_vector mapping is available"


def candidate_matches_filters(candidate: Mapping[str, Any], search_input: SearchInputLike) -> bool:
    """Apply metadata filters for candidates that were not filtered during retrieval."""
    geo = _mapping(candidate.get("geo"))
    for field, value in _geo_constraints(search_input).items():
        if str(geo.get(field, "")) != str(value):
            return False

    content_type = _active_content_type(search_input.content_type)
    if content_type and candidate.get("content_type") != content_type:
        return False

    language = _active_language(search_input.language)
    return not (language and candidate.get("language") != language)


def candidate_has_returnable_metadata(candidate: Mapping[str, Any]) -> bool:
    """Return whether a candidate has enough real metadata to expose as a hit."""
    return any(
        candidate.get(field)
        for field in ("title", "description", "searchable_text", "source_url")
    )


def with_lightgbm_features(candidate: Candidate, search_input: SearchInputLike) -> Candidate:
    """Attach deterministic LightGBM features derived from normalized metadata."""
    enriched = candidate.copy()
    title = str(enriched.get("title", ""))
    description = str(enriched.get("description", ""))
    searchable_text = str(enriched.get("searchable_text", ""))

    enriched["bm25_score"] = _safe_float(enriched.get("bm25_score"))
    enriched["vector_score"] = _safe_float(enriched.get("vector_score"))
    enriched["title_match"] = 1 if _overlap_terms(search_input.query, title) else 0
    enriched["geo_match"] = 1 if _geo_constraints_match(enriched, search_input) else 0
    enriched["freshness"] = _freshness_score(enriched.get("published_at"))
    enriched["source_authority"] = 0
    enriched["language_match"] = _language_match_score(enriched, search_input)
    enriched["query_term_ratio"] = _query_term_ratio(
        search_input.query,
        f"{title} {description} {searchable_text}",
    )
    enriched["content_length"] = len(searchable_text or description)
    return enriched


def candidate_to_hit(candidate: Mapping[str, Any]) -> PipelineHit:
    """Map a final normalized candidate to the API-facing search hit shape."""
    snippet = str(candidate.get("description") or _shorten(str(candidate.get("searchable_text", ""))))
    return PipelineHit(
        id=str(candidate.get("document_id", "")),
        result_type=str(candidate.get("content_type") or "web_page"),
        title=str(candidate.get("title") or ""),
        url=str(candidate.get("source_url") or ""),
        domain=str(candidate.get("domain") or ""),
        snippet=snippet,
        download_url=str(candidate.get("download_url") or ""),
        file_size_bytes=int(_safe_float(candidate.get("file_size_bytes"))),
        relevance_score=_candidate_relevance(candidate),
    )


def _candidate_from_source(document_id: str, source: Mapping[str, Any]) -> Candidate:
    return {
        "document_id": str(source.get("document_id", document_id)),
        "title": source.get("title", ""),
        "description": source.get("description", ""),
        "searchable_text": source.get("searchable_text", ""),
        "source_url": source.get("source_url", ""),
        "domain": source.get("domain", ""),
        "language": source.get("language", ""),
        "content_type": source.get("content_type", ""),
        "keywords": source.get("keywords", []),
        "geo": _mapping(source.get("geo")),
        "published_at": source.get("published_at", ""),
    }


def _requested_count(search_input: SearchInputLike) -> int:
    return max(1, max(search_input.page, 1) * max(search_input.limit, 1))


def _geo_constraints(search_input: SearchInputLike) -> dict[str, str | int]:
    constraints: dict[str, str | int] = {}
    for field in ("province_code", "district_code", "municipality_id"):
        value = getattr(search_input, field)
        if value:
            constraints[field] = value
    if search_input.ward_number > 0:
        constraints["ward_number"] = search_input.ward_number
    return constraints


def _active_content_type(content_type: str) -> str:
    value = content_type.strip()
    return "" if value.lower() in ACTIVE_CONTENT_TYPE_SENTINELS else value


def _active_language(language: str) -> str:
    value = language.strip()
    return "" if value.lower() in ACTIVE_LANGUAGE_SENTINELS else value


def _geo_constraints_match(candidate: Mapping[str, Any], search_input: SearchInputLike) -> bool:
    constraints = _geo_constraints(search_input)
    if not constraints:
        return False
    geo = _mapping(candidate.get("geo"))
    return all(str(geo.get(field, "")) == str(value) for field, value in constraints.items())


def _language_match_score(candidate: Mapping[str, Any], search_input: SearchInputLike) -> float:
    requested_language = _active_language(search_input.language)
    if not requested_language:
        return 0.5
    return 1.0 if candidate.get("language") == requested_language else 0.0


def _query_term_ratio(query: str, text: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    return len(query_terms & _terms(text)) / len(query_terms)


def _overlap_terms(query: str, text: str) -> set[str]:
    return _terms(query) & _terms(text)


def _terms(text: str) -> set[str]:
    return {part.lower() for part in text.split() if part.strip()}


def _freshness_score(value: Any) -> float:
    if not value:
        return 0.0
    raw_value = str(value)
    if raw_value.endswith("Z"):
        raw_value = f"{raw_value[:-1]}+00:00"
    try:
        published_at = datetime.fromisoformat(raw_value)
    except ValueError:
        return 0.0

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age_days = max((datetime.now(UTC) - published_at.astimezone(UTC)).days, 0)
    return 1 / (1 + age_days / 365)


def _candidate_relevance(candidate: Mapping[str, Any]) -> float:
    for key in ("rerank_score", "fusion_score", "bm25_score", "vector_score"):
        if key not in candidate:
            continue
        score = _safe_float(candidate.get(key))
        if math.isfinite(score):
            return score
    return 0.0


def _shorten(text: str, limit: int = SNIPPET_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def _safe_float(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return score if math.isfinite(score) else 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _default_pgvector_search(query: str, top_k: int) -> list[dict[str, Any]]:
    _ensure_legacy_search_engine_path()
    from vector_search.postgres_vector import vector_search_postgres

    return vector_search_postgres(query, top_k=top_k)


def _default_opensearch_vector_search(query: str, top_k: int) -> list[dict[str, Any]]:
    _ensure_legacy_search_engine_path()
    from vector_search.opensearch_vector import vector_search_opensearch

    return vector_search_opensearch(query, top_k=top_k)


def _default_hybrid_searcher() -> Any:
    _ensure_legacy_search_engine_path()
    from fusion.hybrid_search import HybridSearcher

    return HybridSearcher()


def _ensure_legacy_search_engine_path() -> None:
    search_engine_root = Path(__file__).resolve().parents[2]
    root = str(search_engine_root)
    if root not in sys.path:
        sys.path.append(root)
