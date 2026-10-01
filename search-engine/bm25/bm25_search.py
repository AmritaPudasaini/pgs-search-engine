from typing import Any

from opensearchpy import OpenSearch


class BM25Searcher:
    """BM25 lexical search using OpenSearch."""

    def __init__(self, client: OpenSearch, index: str):
        self.client = client
        self.index = index

    def search(
        self,
        query: str,
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the top-k documents ranked by OpenSearch BM25."""

        must_query = {
            "multi_match": {
                "query": query,
                "fields": [
                    "title^3",
                    "text",
                    "description",
                ],
                "type": "best_fields",
            }
        }

        search_query: dict[str, Any] = {
            "size": k,
            "query": {
                "bool": {
                    "must": must_query,
                }
            },
        }

        # Optional filters such as province/district/municipality.
        if filters:
            search_query["query"]["bool"]["filter"] = [
                {"term": {field: value}}
                for field, value in filters.items()
            ]

        response = self.client.search(
            index=self.index,
            body=search_query,
        )

        results = []

        for hit in response["hits"]["hits"]:
            results.append(
                {
                    "document_id": hit["_id"],
                    "score": hit["_score"],
                    "source": hit.get("_source", {}),
                }
            )

        return results