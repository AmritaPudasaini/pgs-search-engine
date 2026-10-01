from __future__ import annotations

import grpc
import pytest

from pgs_search.grpc.generated import search_pb2
from pgs_search.grpc.pipeline_adapter import SearchHit, SearchInput, SearchOutput
from pgs_search.grpc.service import SearchService


class GrpcAbortError(Exception):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.code = code
        self.details = details


class FakeContext:
    def abort(self, code: grpc.StatusCode, details: str) -> None:
        raise GrpcAbortError(code, details)


class CapturingAdapter:
    def __init__(self) -> None:
        self.last_input: SearchInput | None = None

    def search(self, search_input: SearchInput) -> SearchOutput:
        self.last_input = search_input
        return SearchOutput(
            total_hits=1,
            results=[
                SearchHit(
                    id="test-1",
                    result_type="web_page",
                    title=f"Mock result for: {search_input.query}",
                    url="https://example.com/test-result",
                    domain="example.com",
                    snippet="Test result.",
                    download_url="",
                    file_size_bytes=0,
                    relevance_score=1.0,
                )
            ],
        )


def test_valid_search_request_returns_success() -> None:
    service = SearchService(adapter=CapturingAdapter())

    response = service.ExecuteSearch(
        search_pb2.SearchRequest(query="budget", page=1, limit=10),
        FakeContext(),
    )

    assert response.status_code == 200
    assert response.total_hits >= 1


def test_empty_query_returns_invalid_argument() -> None:
    service = SearchService(adapter=CapturingAdapter())

    with pytest.raises(GrpcAbortError) as exc_info:
        service.ExecuteSearch(search_pb2.SearchRequest(query="   "), FakeContext())

    assert exc_info.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert exc_info.value.details == "Query must not be empty."


def test_limit_above_maximum_is_clamped_to_100() -> None:
    adapter = CapturingAdapter()
    service = SearchService(adapter=adapter)

    service.ExecuteSearch(search_pb2.SearchRequest(query="budget", limit=500), FakeContext())

    assert adapter.last_input is not None
    assert adapter.last_input.limit == 100


def test_page_less_than_one_becomes_page_one() -> None:
    adapter = CapturingAdapter()
    service = SearchService(adapter=adapter)

    service.ExecuteSearch(search_pb2.SearchRequest(query="budget", page=0), FakeContext())

    assert adapter.last_input is not None
    assert adapter.last_input.page == 1


def test_unicode_nepali_query_works() -> None:
    service = SearchService(adapter=CapturingAdapter())

    response = service.ExecuteSearch(
        search_pb2.SearchRequest(query="पोखरा बजेट", language="ne", page=1, limit=10),
        FakeContext(),
    )

    assert response.status_code == 200
    assert response.results[0].title == "Mock result for: पोखरा बजेट"
