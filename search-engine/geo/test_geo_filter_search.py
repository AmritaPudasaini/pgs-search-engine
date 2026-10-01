from opensearchpy import OpenSearch

from geo_filter_search import GeoFilteredSearch


INDEX_NAME = "nepal_test_documents_geo"

# NOTE: "scraped_at" is a placeholder date field name -- confirm the
# real field name with the ETL team once their indexed document schema
# includes a timestamp. See the NOTE in geo_filter_search.py.
DATE_FIELD = "scraped_at"


# Connect to local OpenSearch
client = OpenSearch(
    hosts=[{"host": "localhost", "port": 9200}],
    use_ssl=False,
    verify_certs=False,
)


# Sample documents across different regions and dates, matching the
# ETL team's documented geo_location shape (ETL/README.md, section 5.2)
documents = [
    {
        "title": "Pokhara Metropolitan City Notice",
        "description": "Official notice regarding municipal administration.",
        "text": "Road maintenance work scheduled in Pokhara this month.",
        "geo_location": {
            "province_code": "P4",
            "district_code": "D39",
            "municipality_id": "MUN75340",
        },
        "scraped_at": "2026-09-20T10:00:00Z",
    },
    {
        "title": "Pokhara Tourism Update",
        "description": "New tourism initiatives announced for Pokhara.",
        "text": "Pokhara tourism board launches new trekking routes.",
        "geo_location": {
            "province_code": "P4",
            "district_code": "D39",
            "municipality_id": "MUN75340",
        },
        "scraped_at": "2026-09-23T08:00:00Z",
    },
    {
        "title": "Kathmandu Metropolitan Notice",
        "description": "Traffic advisory for Kathmandu valley.",
        "text": "Kathmandu traffic police announce new routes for the festival season.",
        "geo_location": {
            "province_code": "P3",
            "district_code": "D27",
            "municipality_id": "MUN27001",
        },
        "scraped_at": "2026-09-22T09:00:00Z",
    },
    {
        "title": "Kaski District Agriculture Report",
        "description": "Agricultural output report for Kaski district.",
        "text": "Farmers in Kaski district report increased maize yields this season.",
        "geo_location": {
            "province_code": "P4",
            "district_code": "D39",
            "municipality_id": "MUN75341",
        },
        "scraped_at": "2026-09-18T12:00:00Z",
    },
]


def create_index():
    index_body = {
        "mappings": {
            "properties": {
                "title": {"type": "text"},
                "description": {"type": "text"},
                "text": {"type": "text"},
                "scraped_at": {"type": "date"},
                "geo_location": {
                    "properties": {
                        "province_code": {"type": "keyword"},
                        "district_code": {"type": "keyword"},
                        "municipality_id": {"type": "keyword"},
                        "ward_number": {"type": "keyword"},
                    }
                },
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


def print_results(label: str, results: list[dict]) -> None:
    print(f"\n{label}")
    print("-" * 60)

    for rank, result in enumerate(results, start=1):
        source = result["source"]
        print(f"{rank}. {source['title']}")
        print(f"   Scraped at: {source['scraped_at']}")
        print(f"   Geo: {source['geo_location']}")
        print(f"   Score: {result['score']}")
        print()


def run_geo_browse():
    """Pure geo browse, no text query -- newest first within the region."""
    searcher = GeoFilteredSearch(client=client, index=INDEX_NAME, date_field=DATE_FIELD)

    results = searcher.browse(district_code="D39", k=5)
    print_results("Browse: district_code=D39 (Kaski), newest first", results)


def run_geo_browse_narrower():
    """Narrower geo filter -- down to municipality level."""
    searcher = GeoFilteredSearch(client=client, index=INDEX_NAME, date_field=DATE_FIELD)

    results = searcher.browse(municipality_id="MUN75340", k=5)
    print_results("Browse: municipality_id=MUN75340 (Pokhara Metro), newest first", results)


def run_geo_filtered_text_search():
    """Geo filter combined with a text query -- relevance first, recency
    as the tie-breaker."""
    searcher = GeoFilteredSearch(client=client, index=INDEX_NAME, date_field=DATE_FIELD)

    results = searcher.browse(district_code="D39", query="tourism", k=5)
    print_results("Search 'tourism' within district_code=D39", results)


def main():
    print("Creating geo test index...")
    create_index()

    print("Adding sample geo-tagged documents...")
    insert_documents()

    print("Running geo-filtered searches...")

    run_geo_browse()
    run_geo_browse_narrower()
    run_geo_filtered_text_search()


if __name__ == "__main__":
    main()
