"""pgvector search and write path."""
from collections.abc import Callable, Sequence
from importlib import import_module
from typing import cast

from .config import HNSW_EF_SEARCH
from .db import get_connection
from .embeddings import generate_embedding, to_pgvector

VectorSearchResult = dict[str, int | float | str]
_execute_values = cast(
    Callable[..., object],
    getattr(import_module("psycopg2.extras"), "execute_values"),
)


def vector_search_postgres(query: str, top_k: int = 10) -> list[VectorSearchResult]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")

    vec = to_pgvector(generate_embedding(query))

    sql = """
        SELECT document_id, 1 - (embedding <=> q.v) AS vector_score
        FROM documents, (SELECT %s::vector AS v) AS q
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> q.v
        LIMIT %s;
    """

    with get_connection() as conn, conn.cursor() as cur:
        # SET LOCAL lasts for this transaction only; it can't take bind params.
        cur.execute(f"SET LOCAL hnsw.ef_search = {int(max(HNSW_EF_SEARCH, top_k))}")
        cur.execute(sql, (vec, top_k))
        rows = cast(list[tuple[int, float]], cur.fetchall())

    return [
        {
            "document_id": doc_id,
            "vector_score": float(score),
            "rank": rank,
            "source": "pgvector",
        }
        for rank, (doc_id, score) in enumerate(rows, start=1)
    ]


def update_embedding_postgres(document_id: int, embedding: list[float]) -> bool:
    """Store an embedding on an existing documents row. Returns True if a row matched."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET embedding = %s::vector WHERE document_id = %s",
            (to_pgvector(embedding), document_id),
        )
        return cur.rowcount > 0


def bulk_update_embeddings(pairs: Sequence[tuple[int, Sequence[float]]]) -> None:
    """pairs = [(document_id, embedding), ...]"""
    if not pairs:
        return
    values = [(doc_id, to_pgvector(vec)) for doc_id, vec in pairs]
    with get_connection() as conn, conn.cursor() as cur:
        _execute_values(
            cur,
            """
            UPDATE documents AS d SET embedding = v.emb::vector
            FROM (VALUES %s) AS v(id, emb)
            WHERE d.document_id = v.id
            """,
            values,
        )