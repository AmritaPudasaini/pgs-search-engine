from __future__ import annotations

import grpc

from pgs_search.grpc.generated import search_pb2, search_pb2_grpc


def main() -> None:
    channel = grpc.insecure_channel("localhost:50051")
    stub = search_pb2_grpc.SearchServiceStub(channel)

    try:
        response = stub.ExecuteSearch(
            search_pb2.SearchRequest(
                query="पोखरा बजेट",
                province_code="P4",
                district_code="D39",
                language="ne",
                page=1,
                limit=10,
            )
        )
        print(f"Status code: {response.status_code}")
        print(f"Total hits: {response.total_hits}")
        print(f"Execution time: {response.execution_time_ms} ms")

        for result in response.results:
            print(f"Title: {result.title}")
            print(f"URL: {result.url}")
            print(f"Domain: {result.domain}")
            print(f"Relevance score: {result.relevance_score}")
    finally:
        channel.close()


if __name__ == "__main__":
    main()
