from pgs_search.client.opensearch import get_opensearch_client
from pgs_search.indexing.index_manager import create_index


def main() -> None:
    client = get_opensearch_client()
    create_index(client)


if __name__ == "__main__":
    main()