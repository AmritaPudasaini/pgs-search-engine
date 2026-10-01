from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent import futures
from typing import Any

NATIVE_THREAD_ENV_DEFAULTS = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def configure_native_thread_environment() -> None:
    """Set conservative native thread defaults before ML libraries initialize."""
    for name, value in NATIVE_THREAD_ENV_DEFAULTS.items():
        os.environ.setdefault(name, value)


configure_native_thread_environment()

import grpc

from pgs_search.grpc.generated import search_pb2_grpc

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 50051
MAX_WORKERS = 10


def preload_lightgbm_reranker(loader: Callable[[], Any] | None = None) -> bool:
    """Load LightGBM before Torch to avoid macOS OpenMP runtime conflicts."""
    if loader is None:
        # Import lazily so this module does not initialize LightGBM at import time.
        from pgs_search.ranking.lightgbm_reranker import get_model as loader

    logger.info("Preloading LightGBM reranker...")
    try:
        loader()
    except FileNotFoundError as exc:
        logger.warning("LightGBM reranker unavailable; RRF fallback will be used: %s", exc)
        return False

    logger.info("LightGBM reranker ready")
    return True


def configure_pytorch_threads(torch_module: Any | None = None) -> None:
    """Configure PyTorch to use one thread before models perform work."""
    logger.info("Configuring PyTorch threads...")
    if torch_module is None:
        import torch as torch_module

    torch_module.set_num_threads(1)
    try:
        torch_module.set_num_interop_threads(1)
    except RuntimeError as exc:
        logger.warning("Could not set PyTorch interop threads before model preload: %s", exc)
    logger.info("PyTorch threads configured")


def preload_translation_model(loader: Callable[[], Any] | None = None) -> None:
    """Load the cached NLLB translation model before gRPC workers start."""
    if loader is None:
        from pgs_search.query.translation import get_model_and_tokenizer as loader

    logger.info("Preloading translation model...")
    loader()
    logger.info("Translation model ready")


def preload_embedding_model(loader: Callable[[], Any] | None = None) -> None:
    """Load the cached MiniLM embedding model before gRPC workers start."""
    if loader is None:
        from pgs_search.pipeline import _ensure_legacy_search_engine_path

        _ensure_legacy_search_engine_path()
        from vector_search.embeddings import get_model as loader

    logger.info("Preloading embedding model...")
    loader()
    logger.info("Embedding model ready")


def preload_search_runtime() -> None:
    """Initialize native ML runtimes in a deterministic single-threaded order."""
    configure_native_thread_environment()
    from pgs_search.ranking.lightgbm_reranker import get_model as get_reranker

    preload_lightgbm_reranker(get_reranker)
    configure_pytorch_threads()
    preload_translation_model()
    preload_embedding_model()


def serve(host: str | None = None, port: int | None = None) -> None:
    preload_search_runtime()

    # Import the service only after native ML runtimes/models are initialized.
    from pgs_search.grpc.service import SearchService

    grpc_host = host or os.getenv("SEARCH_GRPC_HOST", DEFAULT_HOST)
    grpc_port = (
        port
        if port is not None
        else int(os.getenv("SEARCH_GRPC_PORT", str(DEFAULT_PORT)))
    )
    address = f"{grpc_host}:{grpc_port}"

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    )

    search_pb2_grpc.add_SearchServiceServicer_to_server(
        SearchService(),
        server,
    )

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
