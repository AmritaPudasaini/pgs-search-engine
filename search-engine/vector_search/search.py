from collections.abc import Sequence
from typing import Literal

from .opensearch_vector import vector_search_opensearch
from .postgres_vector import vector_search_postgres

Backend = Literal["postgresql", "opensearch"]
VectorSearchResult = dict[str, int | float | str]
SearchResponse = dict[str, str | list[VectorSearchResult]]


def vector_search(
    query: str,
    top_k: int = 10,
    backends: Sequence[Backend] = ("postgresql", "opensearch"),
) -> SearchResponse:
    out: SearchResponse = {"query": query}
    if "postgresql" in backends:
        out["postgresql"] = vector_search_postgres(query, top_k)
    if "opensearch" in backends:
        out["opensearch"] = vector_search_opensearch(query, top_k)
    return out


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "hello world"
    print(json.dumps(vector_search(q, 5, backends=("postgresql",)), indent=2))