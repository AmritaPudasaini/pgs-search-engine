from opensearchpy import OpenSearch

from pgs_search.config import settings
from pgs_search.indexing.mappings import INDEX_MAPPING


def create_index(client: OpenSearch) -> None:
    index_name = settings.opensearch_index

    if client.indices.exists(index=index_name):
        print(f"Index '{index_name}' already exists.")
        return

    client.indices.create(
        index=index_name,
        body=INDEX_MAPPING,
    )

    print(f"Created index '{index_name}'.")