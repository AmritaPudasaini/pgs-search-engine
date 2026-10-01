from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Self

import pytest

from vector_search import backfill_embedding, incremental_index, postgres_vector


class FakeCursor:
    def __init__(self, rows: list[tuple[int, float | str]] | None = None, rowcount: int = 0) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[int, float | str]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


@contextmanager
def fake_connection(cursor: FakeCursor) -> Iterator[FakeConnection]:
    yield FakeConnection(cursor)


def test_vector_search_postgres_rejects_invalid_top_k() -> None:
    with pytest.raises(ValueError):
        postgres_vector.vector_search_postgres("kathmandu", top_k=0)


def test_vector_search_postgres_maps_crawled_document_id_to_document_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rows=[(42, 0.875)])
    monkeypatch.setattr(postgres_vector, "get_connection", lambda: fake_connection(cursor))
    monkeypatch.setattr(postgres_vector, "generate_embedding", lambda query: [0.1, 0.2])
    monkeypatch.setattr(postgres_vector, "to_pgvector", lambda embedding: "[0.1,0.2]")

    results = postgres_vector.vector_search_postgres("kathmandu", top_k=3)

    assert results == [
        {
            "document_id": 42,
            "vector_score": 0.875,
            "rank": 1,
            "source": "pgvector",
        }
    ]
    _, (sql, params) = cursor.executed
    assert "SELECT id" in sql
    assert "FROM crawled_documents" in sql
    assert "embedding IS NOT NULL" in sql
    assert "document_id" not in sql
    assert params == ("[0.1,0.2]", 3)


def test_update_embedding_postgres_targets_crawled_documents_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rowcount=1)
    monkeypatch.setattr(postgres_vector, "get_connection", lambda: fake_connection(cursor))
    monkeypatch.setattr(postgres_vector, "to_pgvector", lambda embedding: "[0.4,0.5]")

    updated = postgres_vector.update_embedding_postgres(99, [0.4, 0.5])

    assert updated is True
    sql, params = cursor.executed[0]
    assert sql == "UPDATE crawled_documents SET embedding = %s::vector WHERE id = %s"
    assert params == ("[0.4,0.5]", 99)


def test_bulk_update_embeddings_joins_on_crawled_documents_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor()
    captured: dict[str, object] = {}
    monkeypatch.setattr(postgres_vector, "get_connection", lambda: fake_connection(cursor))
    monkeypatch.setattr(postgres_vector, "to_pgvector", lambda embedding: "[0.7,0.8]")

    def fake_execute_values(cur: FakeCursor, sql: str, values: list[tuple[int, str]]) -> None:
        captured["cursor"] = cur
        captured["sql"] = sql
        captured["values"] = values

    monkeypatch.setattr(postgres_vector, "_execute_values", fake_execute_values)

    postgres_vector.bulk_update_embeddings([(7, [0.7, 0.8])])

    assert captured["cursor"] is cursor
    assert "UPDATE crawled_documents AS d" in str(captured["sql"])
    assert "WHERE d.id = v.id" in str(captured["sql"])
    assert captured["values"] == [(7, "[0.7,0.8]")]


def test_incremental_index_rejects_non_int_document_id() -> None:
    with pytest.raises(TypeError):
        incremental_index.index_new_document({"document_id": "99", "title": "Bad id"})


def test_backfill_query_uses_crawled_documents_id_and_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rows=[])
    monkeypatch.setattr(backfill_embedding, "get_connection", lambda: fake_connection(cursor))
    monkeypatch.setattr(backfill_embedding, "close_pool", lambda: None)

    backfill_embedding.main(batch_size=50)

    sql, params = cursor.executed[0]
    assert "SELECT id" in sql
    assert "FROM crawled_documents" in sql
    assert "COALESCE(text, '')" in sql
    assert "ORDER BY id" in sql
    assert "document_id" not in sql
    assert "content" not in sql
    assert params == (50,)
