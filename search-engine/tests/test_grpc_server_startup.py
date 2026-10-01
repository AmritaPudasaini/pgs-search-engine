from __future__ import annotations

import logging
from typing import Any

from pgs_search.grpc import server


def test_native_thread_environment_sets_defaults_without_overwriting(
    monkeypatch,
) -> None:
    for name in server.NATIVE_THREAD_ENV_DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OMP_NUM_THREADS", "8")

    server.configure_native_thread_environment()

    assert server.os.environ["OMP_NUM_THREADS"] == "8"
    assert server.os.environ["MKL_NUM_THREADS"] == "1"
    assert server.os.environ["OPENBLAS_NUM_THREADS"] == "1"
    assert server.os.environ["VECLIB_MAXIMUM_THREADS"] == "1"


def test_preload_search_runtime_order(monkeypatch) -> None:
    events: list[str] = []

    def fake_lightgbm(loader=None) -> bool:
        events.append("lightgbm")
        return True

    monkeypatch.setattr(server, "preload_lightgbm_reranker", fake_lightgbm)
    monkeypatch.setattr(server, "configure_pytorch_threads", lambda: events.append("torch"))
    monkeypatch.setattr(server, "preload_translation_model", lambda: events.append("translation"))
    monkeypatch.setattr(server, "preload_embedding_model", lambda: events.append("embedding"))

    server.preload_search_runtime()

    assert events == ["lightgbm", "torch", "translation", "embedding"]


def test_configure_pytorch_threads_logs_interop_warning(caplog) -> None:
    class FakeTorch:
        def __init__(self) -> None:
            self.num_threads: int | None = None

        def set_num_threads(self, value: int) -> None:
            self.num_threads = value

        def set_num_interop_threads(self, value: int) -> None:
            raise RuntimeError("parallel work already started")

    fake_torch = FakeTorch()

    with caplog.at_level(logging.WARNING):
        server.configure_pytorch_threads(fake_torch)

    assert fake_torch.num_threads == 1
    assert "Could not set PyTorch interop threads" in caplog.text


def test_missing_lightgbm_model_keeps_startup_fallback_available(caplog) -> None:
    def missing_loader() -> None:
        raise FileNotFoundError("missing model")

    with caplog.at_level(logging.WARNING):
        ready = server.preload_lightgbm_reranker(missing_loader)

    assert ready is False
    assert "RRF fallback will be used" in caplog.text


def test_serve_preloads_before_grpc_worker_pool(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(server, "preload_search_runtime", lambda: events.append("preload"))

    def fake_executor(*, max_workers: int) -> object:
        assert events == ["preload"]
        events.append(f"executor:{max_workers}")
        return object()

    class FakeGrpcServer:
        def add_insecure_port(self, address: str) -> None:
            events.append(f"port:{address}")

        def start(self) -> None:
            events.append("start")

        def wait_for_termination(self) -> None:
            events.append("wait")

    def fake_grpc_server(executor: object) -> FakeGrpcServer:
        assert events == ["preload", f"executor:{server.MAX_WORKERS}"]
        events.append("grpc.server")
        return FakeGrpcServer()

    def fake_add_servicer(servicer: Any, grpc_server: FakeGrpcServer) -> None:
        events.append("add_servicer")

    monkeypatch.setattr(server.futures, "ThreadPoolExecutor", fake_executor)
    monkeypatch.setattr(server.grpc, "server", fake_grpc_server)
    monkeypatch.setattr(
        server.search_pb2_grpc,
        "add_SearchServiceServicer_to_server",
        fake_add_servicer,
    )

    server.serve(host="127.0.0.1", port=50099)

    assert events == [
        "preload",
        f"executor:{server.MAX_WORKERS}",
        "grpc.server",
        "add_servicer",
        "port:127.0.0.1:50099",
        "start",
        "wait",
    ]
