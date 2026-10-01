from opensearchpy import OpenSearch

from opensearch_vector_search import OpenSearchVectorSearcher


INDEX_NAME = "pgs-vector-test"

client = OpenSearch(
    hosts=[{"host": "localhost", "port": 9200}],
    use_ssl=False,
    verify_certs=False,
)


documents = [
    {
        "search_document_id": 1,
        "title": "Kathmandu Tourism",
        "body_text": "Kathmandu is the capital city of Nepal and a popular tourism destination.",
        "embedding": [
            0.95, 0.05, 0.02, 0.01,
            0.90, 0.10, 0.03, 0.02,
        ],
    },
    {
        "search_document_id": 2,
        "title": "Pokhara Travel",
        "body_text": "Pokhara is famous for Phewa Lake, mountains and adventure tourism.",
        "embedding": [
            0.80, 0.20, 0.05, 0.02,
            0.75, 0.25, 0.04, 0.03,
        ],
    },
    {
        "search_document_id": 3,
        "title": "Nepal Agriculture",
        "body_text": "Agriculture is an important sector of the Nepalese economy.",
        "embedding": [
            0.05, 0.90, 0.10, 0.04,
            0.03, 0.85, 0.12, 0.05,
        ],
    },
]


def create_index():
    if client.indices.exists(index=INDEX_NAME):
        client.indices.delete(index=INDEX_NAME)

    index_body = {
        "settings": {
            "index.knn": True,
        },
        "mappings": {
            "properties": {
                "search_document_id": {"type": "long"},
                "title": {"type": "text"},
                "body_text": {"type": "text"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 8,
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "space_type": "cosinesimil",
                    },
                },
            }
        },
    }

    client.indices.create(
        index=INDEX_NAME,
        body=index_body,
    )


def insert_documents():
    for document in documents:
        client.index(
            index=INDEX_NAME,
            id=document["search_document_id"],
            body=document,
            refresh=True,
        )


def run_search():
    searcher = OpenSearchVectorSearcher(
        client=client,
        index=INDEX_NAME,
        vector_field="embedding",
    )

    # Synthetic test vector.
    # This is intentionally 8-dimensional only for local testing.
    query_embedding = [
        0.94, 0.06, 0.02, 0.01,
        0.88, 0.12, 0.03, 0.02,
    ]

    results = searcher.search(
        query_embedding=query_embedding,
        k=3,
    )

    print("\nVector Search Results")
    print("=" * 60)

    for rank, result in enumerate(results, start=1):
        source = result["source"]

        print(f"{rank}. {source['title']}")
        print(f"   Document ID: {result['document_id']}")
        print(f"   Vector score: {result['score']:.4f}")
        print()


def main():
    print("Creating OpenSearch vector test index...")
    create_index()

    print("Adding test documents...")
    insert_documents()

    print("Running vector search...")
    run_search()

    print("OpenSearch vector search test completed successfully.")


if __name__ == "__main__":
    main()