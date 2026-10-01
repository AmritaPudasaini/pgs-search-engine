from __future__ import annotations

import logging
import time
from typing import Protocol

import grpc

from pgs_search.grpc.generated import search_pb2, search_pb2_grpc
from pgs_search.grpc.pipeline_adapter import SearchInput, SearchOutput, SearchPipelineAdapter

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
MAX_LIMIT = 100


class SearchPipeline(Protocol):
    def search(self, search_input: SearchInput) -> SearchOutput: ...


class SearchService(search_pb2_grpc.SearchServiceServicer):
    def __init__(self, adapter: SearchPipeline | None = None) -> None:
        self._adapter = adapter or SearchPipelineAdapter()

    def ExecuteSearch(
        self,
        request: search_pb2.SearchRequest,
        context: grpc.ServicerContext,
    ) -> search_pb2.SearchResponse:
        query = request.query.strip()
        if not query:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Query must not be empty.")
            return search_pb2.SearchResponse()

        search_input = SearchInput(
            query=query,
            province_code=request.province_code,
            district_code=request.district_code,
            municipality_id=request.municipality_id,
            ward_number=request.ward_number,
            content_type=request.content_type,
            language=request.language,
            page=max(request.page, 1),
            limit=_normalize_limit(request.limit),
        )

        start_time = time.perf_counter()
        try:
            search_output = self._adapter.search(search_input)
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            return search_pb2.SearchResponse(
                status_code=200,
                total_hits=search_output.total_hits,
                execution_time_ms=execution_time_ms,
                results=[
                    search_pb2.SearchResultItem(
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
                    for hit in search_output.results
                ],
            )
        except Exception:
            logger.exception("Unexpected error while executing search.")
            context.abort(grpc.StatusCode.INTERNAL, "Search service failed.")
            return search_pb2.SearchResponse()


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)
