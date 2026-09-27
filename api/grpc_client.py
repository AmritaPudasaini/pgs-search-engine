from __future__ import annotations

import os

import grpc

from pgs_search.grpc.generated import search_pb2, search_pb2_grpc

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 50051


class SearchGrpcClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = os.getenv("SEARCH_GRPC_HOST", host)
        self.port = int(os.getenv("SEARCH_GRPC_PORT", str(port)))
        self._channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        self._stub = search_pb2_grpc.SearchServiceStub(self._channel)

    def search(
        self,
        query: str,
        province_code: str = "",
        district_code: str = "",
        municipality_id: str = "",
        ward_number: int = 0,
        content_type: str = "all",
        language: str = "auto",
        page: int = 1,
        limit: int = 10,
    ) -> search_pb2.SearchResponse:
        request = search_pb2.SearchRequest(
            query=query,
            province_code=province_code,
            district_code=district_code,
            municipality_id=municipality_id,
            ward_number=ward_number,
            content_type=content_type,
            language=language,
            page=page,
            limit=limit,
        )
        return self._stub.ExecuteSearch(request)

    def close(self) -> None:
        self._channel.close()

    def __enter__(self) -> SearchGrpcClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
