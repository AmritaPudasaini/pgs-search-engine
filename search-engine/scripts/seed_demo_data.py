import json
import sys
from pathlib import Path

from pgs_search.client.opensearch import get_opensearch_client
from pgs_search.config import settings

sys.stdout.reconfigure(encoding="utf-8")

DATA_FILE = Path(__file__).parents[1] / "seed" / "documents.json"


def load_documents() -> list[dict]:
    with DATA_FILE.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    client = get_opensearch_client()
    documents = load_documents()

    for document in documents:
        response = client.index(
            index=settings.opensearch_index,
            id=document["document_id"],
            body=document,
            refresh=True,
        )

        print(
            f"Indexed {document['document_id']}: "
            f"{document['title']} -> {response['result']}"
        )

    print(f"\nIndexed {len(documents)} demo documents.")


if __name__ == "__main__":
    main()