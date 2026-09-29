"""Bulk-index transformed JSONL records using document_id as the stable _id."""

import json
import os
from pathlib import Path
from typing import Iterator

from opensearchpy import OpenSearch, helpers

from .create_index import INDEX_NAME, ensure_index


DEFAULT_JSONL = Path("/data/transformed_documents.jsonl")

def make_client() -> OpenSearch:
    url = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
    username = os.getenv("OPENSEARCH_USERNAME")
    password = os.getenv("OPENSEARCH_PASSWORD")
    auth = (username, password) if username and password else None
    return OpenSearch(
        hosts=[url],
        http_auth=auth,
        use_ssl=url.startswith("https://"),
        verify_certs=url.startswith("https://"),
        timeout=30,
        max_retries=3,
        retry_on_timeout=True,
    )


def read_actions(path: str | Path, index_name: str = INDEX_NAME) -> Iterator[dict]:
    """Read JSONL and yield OpenSearch index actions, reporting bad line numbers."""
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc
            if not isinstance(document, dict):
                raise ValueError(f"Line {line_number} must contain a JSON object")
            document_id = document.get("document_id")
            if not isinstance(document_id, str) or not document_id.strip():
                raise ValueError(f"Line {line_number} is missing a non-empty document_id")
            yield {"_op_type": "index", "_index": index_name, "_id": document_id, "_source": document}


def index_jsonl(
    path: str | Path,
    client: OpenSearch,
    index_name: str = INDEX_NAME,
    batch_size: int = 500,
) -> tuple[int, int]:
    """Create the mapping if needed and index records idempotently by document_id."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    ensure_index(client, index_name)
    return helpers.bulk(
        client,
        read_actions(path, index_name),
        chunk_size=batch_size,
        stats_only=True,
        raise_on_error=True,
        raise_on_exception=True,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.getenv("JSONL_PATH", str(DEFAULT_JSONL)))
    parser.add_argument("--index", default=INDEX_NAME)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    client = make_client()
    succeeded, errors = index_jsonl(args.input, client, args.index, args.batch_size)
    print(f"Indexed {succeeded} documents into {args.index}; errors: {errors}")


if __name__ == "__main__":
    main()
