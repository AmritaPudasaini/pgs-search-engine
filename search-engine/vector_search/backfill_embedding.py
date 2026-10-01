"""One-off: embed every crawled_documents row that has no embedding yet.

Usage: python backfill_embeddings.py [batch_size]
Uses crawled_documents(id, title, text).
"""
import sys
from typing import cast

from .db import close_pool, get_connection
from .embeddings import generate_embeddings
from .postgres_vector import bulk_update_embeddings


def main(batch_size: int = 200) -> None:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    total = 0
    while True:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, COALESCE(title, '') || E'\n' || COALESCE(text, '')
                FROM crawled_documents
                WHERE embedding IS NULL
                  AND length(trim(COALESCE(title, '') || COALESCE(text, ''))) > 0
                ORDER BY id
                LIMIT %s
                """,
                (batch_size,),
            )
            rows = cast(list[tuple[int, str]], cur.fetchall())
        if not rows:
            break
        # Cap text length; most sentence-transformer models truncate anyway.
        vecs = generate_embeddings([text[:8000] for _, text in rows])
        bulk_update_embeddings(list(zip((row[0] for row in rows), vecs, strict=True)))
        total += len(rows)
        print(f"embedded {total} documents")
    close_pool()
    print("done")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
