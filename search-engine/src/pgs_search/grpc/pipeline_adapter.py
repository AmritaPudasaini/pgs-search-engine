"""Temporary adapter boundary between gRPC and the search pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchInput:
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
class SearchHit:
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
class SearchOutput:
    total_hits: int
    results: list[SearchHit]


class SearchPipelineAdapter:
    """Temporary integration stub for the future BM25/vector/reranking pipeline."""

    def search(self, search_input: SearchInput) -> SearchOutput:
        """Return one deterministic mock result until the real pipeline is merged."""
        hit = SearchHit(
            id="mock-1",
            result_type="web_page",
            title=f"Mock result for: {search_input.query}",
            url="https://example.com/mock-result",
            domain="example.com",
            snippet="Temporary search result from the gRPC integration stub.",
            download_url="",
            file_size_bytes=0,
            relevance_score=1.0,
        )
        return SearchOutput(total_hits=1, results=[hit])
