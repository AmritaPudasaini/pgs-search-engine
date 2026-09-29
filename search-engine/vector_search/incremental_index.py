from opensearchpy import OpenSearch

from config import (
    OPENSEARCH_HOST,
    OPENSEARCH_PORT,
    OPENSEARCH_INDEX
)

from embeddings import generate_embedding


def get_client():

    return OpenSearch(
        hosts=[
            {
                "host": OPENSEARCH_HOST,
                "port": OPENSEARCH_PORT
            }
        ]
    )


def index_new_document(
    document: dict
):

    document_id = document[
        "document_id"
    ]

    title = document.get(
        "title",
        ""
    )

    content = document.get(
        "content",
        ""
    )

    text = (
        f"{title}\n{content}"
    ).strip()

    if not text:

        raise ValueError(
            "Document has no text."
        )

    embedding = generate_embedding(
        text
    )

    client = get_client()

    document_to_index = {
        **document,
        "embedding": embedding
    }

    response = client.index(
        index=OPENSEARCH_INDEX,
        id=document_id,
        body=document_to_index,
        refresh=True
    )

    return {
        "document_id": document_id,
        "indexed": True,
        "index": response["_index"]
    }