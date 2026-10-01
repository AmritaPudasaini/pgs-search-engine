from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pgs_search.grpc.pipeline_adapter import SearchPipelineAdapter
from pgs_search.pipeline import (
    FinalSearchPipeline,
    PipelineHit,
    PipelineOutput,
    build_filter_clauses,
    candidate_to_hit,
    normalize_bm25_hit,
)


@dataclass(frozen=True)
class Input:
    query: str = "Pokhara budget"
    province_code: str = ""
    district_code: str = ""
    municipality_id: str = ""
    ward_number: int = 0
    content_type: str = ""
    language: str = ""
    page: int = 1
    limit: int = 10


class FakeIndices:
    def __init__(self, mapping: dict[str, Any] | None = None) -> None:
        self.mapping = mapping or {"np_web_pages": {"mappings": {"properties": {}}}}

    def get_mapping(self, *, index: str) -> dict[str, Any]:
        return self.mapping


class FakeClient:
    def __init__(self, mapping: dict[str, Any] | None = None) -> None:
        self.indices = FakeIndices(mapping)
        self.mget_calls: list[dict[str, Any]] = []

    def mget(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.mget_calls.append({"index": index, "body": body})
        docs = []
        for document_id in body["ids"]:
            docs.append(
                {
                    "_id": document_id,
                    "found": True,
                    "_source": {
                        "document_id": document_id,
                        "title": f"Hydrated {document_id}",
                        "description": f"Description {document_id}",
                        "searchable_text": f"Pokhara budget text {document_id}",
                        "source_url": f"https://example.com/{document_id}",
                        "domain": "example.com",
                        "content_type": "web_page",
                        "language": "en",
                        "geo": {"district_code": "D39"},
                    },
                }
            )
        return {"docs": docs}


class MissingHydrationClient(FakeClient):
    def mget(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.mget_calls.append({"index": index, "body": body})
        return {"docs": [{"_id": document_id, "found": False} for document_id in body["ids"]]}


def identity_reranker(candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    return candidates[:top_k]


def bm25_hit(document_id: str, score: float = 5.0) -> dict[str, Any]:
    return {
        "_id": document_id,
        "_score": score,
        "_source": {
            "document_id": document_id,
            "title": "Pokhara budget notice",
            "description": "Budget notice from Pokhara",
            "searchable_text": "Pokhara budget searchable body",
            "source_url": "https://example.com/pokhara-budget",
            "domain": "example.com",
            "content_type": "web_page",
            "language": "en",
            "geo": {"district_code": "D39", "ward_number": 4},
            "published_at": "2026-09-20T10:00:00Z",
        },
    }


def test_bm25_raw_opensearch_hit_normalizes_to_candidate() -> None:
    candidate = normalize_bm25_hit(bm25_hit("doc-1", score=7.25))

    assert candidate["document_id"] == "doc-1"
    assert candidate["title"] == "Pokhara budget notice"
    assert candidate["bm25_score"] == 7.25
    assert candidate["geo"]["district_code"] == "D39"


def test_pipeline_merges_vector_ids_with_bm25_and_fuses_duplicates_once() -> None:
    client = FakeClient()
    pipeline = FinalSearchPipeline(
        opensearch_client=client,
        bm25_search=lambda client, query, limit, filters: [bm25_hit("doc-1")],
        pgvector_search=lambda query, top_k: [
            {"document_id": "doc-1", "vector_score": 0.7, "rank": 1},
            {"document_id": "doc-2", "vector_score": 0.6, "rank": 2},
        ],
        opensearch_vector_search=lambda query, top_k: [],
        reranker=identity_reranker,
    )

    output = pipeline.search(Input(limit=10))

    assert output.total_hits == 2
    assert {hit.id for hit in output.results} == {"doc-1", "doc-2"}
    assert client.mget_calls == [{"index": "np_web_pages", "body": {"ids": ["doc-2"]}}]


def test_unhydrated_pgvector_candidate_is_skipped_without_fabricated_metadata() -> None:
    client = MissingHydrationClient()
    pipeline = FinalSearchPipeline(
        opensearch_client=client,
        bm25_search=lambda client, query, limit, filters: [],
        pgvector_search=lambda query, top_k: [{"document_id": 123, "vector_score": 0.9, "rank": 1}],
        opensearch_vector_search=lambda query, top_k: [],
        reranker=identity_reranker,
    )

    output = pipeline.search(Input())

    assert output.total_hits == 0
    assert output.results == []
    assert client.mget_calls == [{"index": "np_web_pages", "body": {"ids": ["123"]}}]


def test_filter_clauses_use_real_geo_fields_and_ignore_ward_zero() -> None:
    filters = build_filter_clauses(Input(district_code="D39", ward_number=0))

    assert filters == [{"term": {"geo.district_code": "D39"}}]
    assert "geo_location" not in str(filters)


def test_content_type_and_language_filters_apply_only_when_active() -> None:
    assert build_filter_clauses(Input(content_type="", language="")) == []
    assert build_filter_clauses(Input(content_type="all", language="auto")) == []

    filters = build_filter_clauses(Input(content_type="web_page", language="ne"))

    assert {"term": {"content_type": "web_page"}} in filters
    assert {"term": {"language": "ne"}} in filters


def test_pagination_slices_after_fusion_and_reports_total_hits() -> None:
    pipeline = FinalSearchPipeline(
        opensearch_client=FakeClient(),
        bm25_search=lambda client, query, limit, filters: [
            bm25_hit("doc-1", 5),
            bm25_hit("doc-2", 4),
            bm25_hit("doc-3", 3),
        ],
        pgvector_search=lambda query, top_k: [],
        opensearch_vector_search=lambda query, top_k: [],
        reranker=identity_reranker,
    )

    output = pipeline.search(Input(page=2, limit=1))

    assert output.total_hits == 2
    assert len(output.results) == 1
    assert output.results[0].id == "doc-2"


def test_search_hit_metadata_mapping_prefers_real_fields() -> None:
    hit = candidate_to_hit(
        {
            "document_id": "doc-7",
            "content_type": "web_page",
            "title": "Title",
            "source_url": "https://example.com/doc-7",
            "domain": "example.com",
            "description": "Description",
            "rerank_score": 0.82,
        }
    )

    assert hit.id == "doc-7"
    assert hit.result_type == "web_page"
    assert hit.url == "https://example.com/doc-7"
    assert hit.snippet == "Description"
    assert hit.relevance_score == 0.82


def test_missing_opensearch_vector_mapping_skips_backend_without_failure() -> None:
    def fail_if_called(query: str, top_k: int) -> list[dict[str, Any]]:
        raise AssertionError("OpenSearch vector search should be skipped")

    pipeline = FinalSearchPipeline(
        opensearch_client=FakeClient(),
        bm25_search=lambda client, query, limit, filters: [bm25_hit("doc-1")],
        pgvector_search=lambda query, top_k: [],
        opensearch_vector_search=fail_if_called,
        reranker=identity_reranker,
    )

    output = pipeline.search(Input())

    assert output.total_hits == 1
    assert output.opensearch_vector_status.startswith("skipped:")


def test_lightgbm_unavailable_falls_back_to_rrf_order() -> None:
    def missing_model(candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        raise FileNotFoundError("missing model")

    pipeline = FinalSearchPipeline(
        opensearch_client=FakeClient(),
        bm25_search=lambda client, query, limit, filters: [bm25_hit("doc-1")],
        pgvector_search=lambda query, top_k: [],
        opensearch_vector_search=lambda query, top_k: [],
        reranker=missing_model,
    )

    output = pipeline.search(Input())

    assert [hit.id for hit in output.results] == ["doc-1"]


def test_adapter_uses_pipeline_output_instead_of_mock_result() -> None:
    class FakePipeline:
        def search(self, search_input: Input) -> PipelineOutput:
            return PipelineOutput(
                total_hits=1,
                results=[
                    PipelineHit(
                        id="real-1",
                        result_type="web_page",
                        title=f"Real result for {search_input.query}",
                        url="https://example.com/real",
                        domain="example.com",
                        snippet="Real pipeline result",
                        download_url="",
                        file_size_bytes=0,
                        relevance_score=0.9,
                    )
                ],
                opensearch_vector_status="skipped: test",
                pgvector_hydrated_ids=set(),
            )

    output = SearchPipelineAdapter(pipeline=FakePipeline()).search(Input())

    assert output.results[0].id == "real-1"
    assert output.results[0].id != "mock-1"
