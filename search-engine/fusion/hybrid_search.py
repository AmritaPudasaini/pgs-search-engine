from collections import defaultdict
from typing import Any


class HybridSearcher:
    """Fuse BM25 and vector-search results using Reciprocal Rank Fusion."""

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k

    def fuse(
        self,
        bm25_results: list[dict[str, Any]],
        pgvector_results: list[dict[str, Any]],
        opensearch_vector_results: list[dict[str, Any]],
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        scores = defaultdict(float)
        documents = {}

        result_lists = [
            bm25_results,
            pgvector_results,
            opensearch_vector_results,
        ]

        for results in result_lists:
            for rank, result in enumerate(results, start=1):
                document_id = str(result["document_id"])

                # Reciprocal Rank Fusion
                scores[document_id] += 1 / (self.rrf_k + rank)

                # Keep the available document information
                if document_id not in documents:
                    documents[document_id] = result

        ranked_results = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        final_results = []

        for document_id, fusion_score in ranked_results[:top_k]:
            result = documents[document_id].copy()

            result["document_id"] = document_id
            result["fusion_score"] = fusion_score

            final_results.append(result)

        return final_results