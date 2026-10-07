"""Adapter boundary between gRPC and the final search pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from pgs_search.pipeline import FinalSearchPipeline


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
    """Thin integration boundary from gRPC dataclasses to the final pipeline."""

    def __init__(self, pipeline: FinalSearchPipeline | None = None) -> None:
        self._pipeline = pipeline or FinalSearchPipeline()

    def search(self, search_input: SearchInput) -> SearchOutput:
        """Run the final search pipeline and adapt its output to gRPC dataclasses."""
        output = self._pipeline.search(search_input)
        return SearchOutput(
            total_hits=output.total_hits,
            results=[
                SearchHit(
                    id=hit.id,
                    result_type=hit.result_type,
                    title=hit.title,
                    url=hit.url,
                    domain=hit.domain,
                    snippet=hit.snippet,
                    download_url=hit.download_url,
                    file_size_bytes=hit.file_size_bytes,
                    relevance_score=hit.relevance_score,
                )
                for hit in output.results
            ],
        )
