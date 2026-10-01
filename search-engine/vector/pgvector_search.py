from typing import Any

import psycopg
from pgvector.psycopg import register_vector


class PGVectorSearcher:
    """Vector similarity search using PostgreSQL and pgvector."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    def search(
        self,
        query_embedding: list[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search documents using pgvector cosine similarity.

        The query embedding is expected to be generated externally
        using the same embedding pipeline as the indexed documents.

        Supported filters:
            - province
            - district
            - municipality
        """

        filters = filters or {}

        conditions = []
        parameters = []

        # Apply only confirmed database filters.
        for field in ("province", "district", "municipality"):
            if field in filters and filters[field] is not None:
                conditions.append(f"{field} = %s")
                parameters.append(filters[field])

        where_clause = ""

        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT
                id,
                title,
                url,
                province,
                district,
                municipality,
                1 - (embedding <=> %s) AS score
            FROM documents
            {where_clause}
            ORDER BY embedding <=> %s
            LIMIT %s
        """

        # The query vector is used twice:
        # 1. To calculate the similarity score
        # 2. To order results by cosine distance
        parameters = [
            query_embedding,
            *parameters,
            query_embedding,
            k,
        ]

        with psycopg.connect(self.database_url) as connection:
            register_vector(connection)

            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                rows = cursor.fetchall()

        results = []

        for row in rows:
            results.append(
                {
                    "document_id": row[0],
                    "title": row[1],
                    "url": row[2],
                    "province": row[3],
                    "district": row[4],
                    "municipality": row[5],
                    "score": float(row[6]),
                }
            )

        return results