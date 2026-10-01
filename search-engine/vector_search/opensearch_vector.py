"""OpenSearch k-NN index and search helpers."""
from functools import lru_cache
from importlib import import_module
from typing import Protocol, cast

from .config import EMBEDDING_DIM, OPENSEARCH_HOST, OPENSEARCH_INDEX, OPENSEARCH_PORT
from .embeddings import generate_embedding


class _IndicesClient(Protocol):
    def exists(self, *, index: str) -> bool: ...

    def create(self, *, index: str, body: dict[str, object]) -> dict[str, object]: ...


class _OpenSearchClient(Protocol):
    indices: _IndicesClient

    def index(
        self,
        *,
        index: str,
        id: int | str,
        body: dict[str, object],
        refresh: bool | str = False,
    ) -> dict[str, object]: ...

    def search(self, *, index: str, body: dict[str, object]) -> dict[str, object]: ...


@lru_cache(maxsize=1)
def get_client() -> _OpenSearchClient:
    opensearch = import_module("opensearchpy")
    client_type = getattr(opensearch, "OpenSearch")
    return cast(
        _OpenSearchClient,
        client_type(hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}]),
    )


def ensure_index() -> None:
    client = get_client()
    if client.indices.exists(index=OPENSEARCH_INDEX):
        return

    body: dict[str, object] = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "embedding": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIM,
                    "method": {
                        "name": "hnsw",
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                    },
                }
            }
        },
    }
    client.indices.create(index=OPENSEARCH_INDEX, body=body)


def vector_search_opensearch(query: str, top_k: int = 10) -> list[dict[str, int | float | str]]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")

    ensure_index()
    embedding = generate_embedding(query)
    response = get_client().search(
        index=OPENSEARCH_INDEX,
        body={
            "size": top_k,
            "query": {"knn": {"embedding": {"vector": embedding, "k": top_k}}},
        },
    )

    hits_value = response.get("hits")
    if not isinstance(hits_value, dict):
        return []
    hits = cast(dict[str, object], hits_value).get("hits")
    if not isinstance(hits, list):
        return []
    hits = cast(list[object], hits)

    results: list[dict[str, int | float | str]] = []
    for rank, hit_value in enumerate(hits, start=1):
        if not isinstance(hit_value, dict):
            continue
        hit = cast(dict[str, object], hit_value)
        document_id = hit.get("_id")
        score = hit.get("_score")
        if not isinstance(document_id, str) or not isinstance(score, (int, float)):
            continue
        results.append(
            {
                "document_id": document_id,
                "vector_score": float(score),
                "rank": rank,
                "source": "opensearch",
            }
        )
    return results
