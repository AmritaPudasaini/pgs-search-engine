"""Index a single new/changed document into Postgres (pgvector) and OpenSearch."""

from collections.abc import Mapping

from .config import OPENSEARCH_INDEX
from .embeddings import generate_embedding
from .opensearch_vector import ensure_index, get_client
from .postgres_vector import update_embedding_postgres


def index_new_document(document: Mapping[str, object]) -> dict[str, int | bool | str]:
    """Index an existing Postgres document into pgvector and OpenSearch.

    The document must already exist in the Postgres `crawled_documents` table.
    ETL is responsible for inserting the row; this function adds the
    embedding and mirrors the document into OpenSearch.
    """
    document_id = document.get("document_id")
    if not isinstance(document_id, int):
        raise TypeError("document_id must be an integer")

    title_value = document.get("title")
    text_value = document.get("text")
    content_value = document.get("content")

    title = title_value if isinstance(title_value, str) else ""
    content = ""
    for value in (text_value, content_value):
        if isinstance(value, str):
            content = value
            break

    text = f"{title}\n{content}".strip()
    if not text:
        raise ValueError("Document has no text.")

    embedding = generate_embedding(text)

    pg_updated = update_embedding_postgres(document_id, embedding)

    ensure_index()

    os_resp = get_client().index(
        index=OPENSEARCH_INDEX,
        id=document_id,
        body={
            **document,
            "embedding": embedding,
        },
        refresh=True,
    )

    index_name = os_resp.get("_index")
    if not isinstance(index_name, str):
        raise RuntimeError("OpenSearch returned no index name")  # noqa: TRY004

    return {
        "document_id": document_id,
        "postgres_updated": pg_updated,
        "opensearch_index": index_name,
    }
