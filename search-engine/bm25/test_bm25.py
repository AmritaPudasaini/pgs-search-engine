from opensearchpy import OpenSearch

from bm25_search import BM25Searcher


INDEX_NAME = "nepal_test_documents"


# Connect to local OpenSearch
client = OpenSearch(
    hosts=[{"host": "localhost", "port": 9200}],
    use_ssl=False,
    verify_certs=False,
)


# Sample Nepal-related documents
documents = [
    {
        "title": "Tourism in Kathmandu",
        "description": "Kathmandu is the capital city of Nepal and a major tourism destination.",
        "text": "Kathmandu Valley contains historical temples, cultural heritage sites, museums and popular tourist attractions.",
        "category": "tourism",
    },
    {
        "title": "Pokhara Travel Guide",
        "description": "Pokhara is a popular tourist destination in Nepal.",
        "text": "Pokhara is famous for Phewa Lake, mountain views, trekking routes and adventure tourism.",
        "category": "tourism",
    },
    {
        "title": "Everest Trekking in Nepal",
        "description": "Mount Everest trekking is one of Nepal's most famous adventure activities.",
        "text": "The Everest region offers trekking routes, mountain scenery, Sherpa culture and access to Everest Base Camp.",
        "category": "trekking",
    },
    {
        "title": "Nepal Government Services",
        "description": "Online government services available to citizens of Nepal.",
        "text": "Citizens can access information about government offices, public services, documents and administrative procedures.",
        "category": "government",
    },
    {
        "title": "Nepali Agriculture",
        "description": "Agriculture is an important sector of the Nepalese economy.",
        "text": "Farmers in Nepal grow rice, maize, wheat, vegetables and other agricultural products across different regions.",
        "category": "agriculture",
    },
    {
        "title": "Kathmandu Restaurants",
        "description": "Popular food and restaurants in Kathmandu.",
        "text": "Kathmandu has restaurants serving traditional Nepali food including dal bhat, momo, Newari cuisine and other dishes.",
        "category": "food",
    },
    {
        "title": "Lumbini Tourism",
        "description": "Lumbini is a major cultural and religious tourism destination in Nepal.",
        "text": "Lumbini is known as the birthplace of Buddha and attracts visitors interested in Buddhist heritage and culture.",
        "category": "tourism",
    },
    {
        "title": "Nepal Trekking Routes",
        "description": "Popular trekking routes across Nepal.",
        "text": "Nepal has many trekking destinations including Everest, Annapurna, Langtang and Manaslu.",
        "category": "trekking",
    },
]


def create_index():
    # Remove old test index if it exists
    if client.indices.exists(index=INDEX_NAME):
        client.indices.delete(index=INDEX_NAME)

    index_body = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "title": {"type": "text"},
                "description": {"type": "text"},
                "text": {"type": "text"},
                "category": {"type": "keyword"},
            }
        },
    }

    client.indices.create(
        index=INDEX_NAME,
        body=index_body,
    )


def insert_documents():
    for document_id, document in enumerate(documents, start=1):
        client.index(
            index=INDEX_NAME,
            id=document_id,
            body=document,
            refresh=True,
        )


def run_search(query: str):
    searcher = BM25Searcher(
        client=client,
        index=INDEX_NAME,
    )

    results = searcher.search(
        query=query,
        k=5,
    )

    print(f"\nQuery: {query}")
    print("-" * 60)

    for rank, result in enumerate(results, start=1):
        source = result["source"]

        print(f"{rank}. {source['title']}")
        print(f"   Category: {source['category']}")
        print(f"   BM25 score: {result['score']:.4f}")
        print(f"   ID: {result['document_id']}")
        print()


def main():
    print("Creating Nepal test index...")
    create_index()

    print("Adding sample documents...")
    insert_documents()

    print("Running BM25 searches...")

    run_search("Nepal tourism")
    run_search("Everest trekking")
    run_search("Kathmandu food")


if __name__ == "__main__":
    main()