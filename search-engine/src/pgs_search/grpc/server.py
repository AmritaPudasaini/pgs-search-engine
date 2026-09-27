from __future__ import annotations

import logging
import os
from concurrent import futures

import grpc

from pgs_search.grpc.generated import search_pb2_grpc
from pgs_search.grpc.service import SearchService

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 50051
MAX_WORKERS = 10


def serve(host: str | None = None, port: int | None = None) -> None:
    grpc_host = host or os.getenv("SEARCH_GRPC_HOST", DEFAULT_HOST)
    grpc_port = port if port is not None else int(os.getenv("SEARCH_GRPC_PORT", str(DEFAULT_PORT)))
    address = f"{grpc_host}:{grpc_port}"

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=MAX_WORKERS))
    search_pb2_grpc.add_SearchServiceServicer_to_server(SearchService(), server)
    server.add_insecure_port(address)
    server.start()
    logger.info("Search gRPC server listening on %s", address)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Stopping Search gRPC server.")
        server.stop(grace=5).wait()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    serve()


if __name__ == "__main__":
    main()
