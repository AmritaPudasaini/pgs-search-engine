import psycopg2

from config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD
)

from embeddings import generate_embedding


def get_connection():

    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )


def vector_search_postgres(
    query: str,
    top_k: int = 10
):

    query_embedding = generate_embedding(
        query
    )

    connection = get_connection()

    cursor = connection.cursor()

    sql = """
        SELECT
            document_id,
            1 - (
                embedding <=> %s::vector
            ) AS vector_score
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY
            embedding <=> %s::vector
        LIMIT %s;
    """

    cursor.execute(
        sql,
        (
            query_embedding,
            query_embedding,
            top_k
        )
    )

    rows = cursor.fetchall()

    results = []

    for rank, row in enumerate(
        rows,
        start=1
    ):

        results.append(
            {
                "document_id": row[0],
                "vector_score": float(
                    row[1]
                ),
                "rank": rank,
                "source": "pgvector"
            }
        )

    cursor.close()
    connection.close()

    return results