from opensearchpy import OpenSearch

from pgs_search.config import settings
from pgs_search.query.normalizer import expand_query_terms, normalize_query

_SEARCH_FIELDS = [
    "title^3",
    "description^2",
    "searchable_text",
]


def search_bm25(
    client: OpenSearch,
    query: str,
    limit: int = 10,
) -> list[dict]:
    normalized = normalize_query(query)
    if not normalized:
        return []

    variants = expand_query_terms(normalized)

    body = {
        "size": limit * max(1, len(variants)),
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": variant,
                            "fields": _SEARCH_FIELDS,
                            "type": "best_fields",
                            "fuzziness": "AUTO",
                        }
                    }
                    for variant in variants
                ]
            }
        },
    }

    response = client.search(
        index=settings.opensearch_index,
        body=body,
    )

    seen: set[str] = set()
    results: list[dict] = []
    for hit in response["hits"]["hits"]:
        doc_id = hit["_id"]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        results.append(hit)
        if len(results) == limit:
            break
    return results
