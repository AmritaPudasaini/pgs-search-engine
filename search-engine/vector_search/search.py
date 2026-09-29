from postgres_vector import (
    vector_search_postgres
)

from opensearch_vector import (
    vector_search_opensearch
)


def vector_search(
    query: str,
    top_k: int = 10
):

    pg_results = vector_search_postgres(
        query,
        top_k
    )

    os_results = vector_search_opensearch(
        query,
        top_k
    )

    return {
        "query": query,
        "postgresql": pg_results,
        "opensearch": os_results
    }