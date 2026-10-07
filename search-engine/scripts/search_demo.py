import sys

from pgs_search.client.opensearch import get_opensearch_client
from pgs_search.retrieval.lexical import search_bm25


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python scripts/search_demo.py "search query"')
        return

    query = " ".join(sys.argv[1:])

    client = get_opensearch_client()
    results = search_bm25(client, query)

    print(f"\nSearch query: {query}")
    print(f"Results found: {len(results)}\n")

    for position, result in enumerate(results, start=1):
        source = result["_source"]

        print(f"{position}. {source['title']}")
        print(f"   Score: {result['_score']}")
        print(f"   Domain: {source['domain']}")
        print(f"   URL: {source['source_url']}")
        print()


if __name__ == "__main__":
    main()