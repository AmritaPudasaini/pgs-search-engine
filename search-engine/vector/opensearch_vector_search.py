from typing import Any

from opensearchpy import OpenSearch


class OpenSearchVectorSearcher:
    """Vector similarity search using OpenSearch k-NN."""

    def __init__(
        self,
        client: OpenSearch,
        index: str,
        vector_field: str = "embedding",
    ):
        self.client = client
        self.index = index
        self.vector_field = vector_field

    def search(
        self,
        query_embedding: list[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the top-k documents by vector similarity."""

        knn_query: dict[str, Any] = {
            "knn": {
                self.vector_field: {
                    "vector": query_embedding,
                    "k": k,
                }
            }
        }

        if filters:
            knn_query = {
                "bool": {
                    "must": [knn_query],
                    "filter": [
                        {"term": {field: value}}
                        for field, value in filters.items()
                    ],
                }
            }

        response = self.client.search(
            index=self.index,
            body={
                "size": k,
                "query": knn_query,
            },
        )

        return [
            {
                "document_id": hit["_id"],
                "score": float(hit["_score"]),
                "source": hit.get("_source", {}),
            }
            for hit in response["hits"]["hits"]
        ]