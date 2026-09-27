# PGS Search Engine Service

## gRPC Search Service

Rabin's gRPC layer owns communication between the external FastAPI API service and the
internal Search Engine service. It exposes `SearchService.ExecuteSearch`, converts protobuf
requests into a typed adapter input, calls `SearchPipelineAdapter`, and returns protobuf
`SearchResponse` messages.

Architecture flow:

```text
Frontend
  -> HTTP/REST
FastAPI Gateway
  -> gRPC
Search Engine SearchService
  -> SearchPipelineAdapter
  -> gRPC SearchResponse
FastAPI Gateway
  -> JSON response
Frontend
```

The service listens on port `50051` by default. Override the bind address with
`SEARCH_GRPC_HOST` and `SEARCH_GRPC_PORT`.

Generate protobuf code:

```bash
PYTHONPATH=search-engine/src search-engine/.venv/bin/python -m grpc_tools.protoc \
  -Isearch-engine/proto \
  --python_out=search-engine/src/pgs_search/grpc/generated \
  --grpc_python_out=search-engine/src/pgs_search/grpc/generated \
  search-engine/proto/search.proto
```

If `search_pb2_grpc.py` generates `import search_pb2 as search__pb2`, change it to:

```python
from . import search_pb2 as search__pb2
```

Start the gRPC server:

```bash
PYTHONPATH=search-engine/src python -m pgs_search.grpc.server
```

Run the manual client:

```bash
PYTHONPATH=search-engine/src python search-engine/scripts/test_grpc_client.py
```

Example request:

```python
SearchRequest(
    query="पोखरा बजेट",
    province_code="P4",
    district_code="D39",
    language="ne",
    page=1,
    limit=10,
)
```

`SearchPipelineAdapter` is a temporary integration stub. It returns one deterministic mock
result until the BM25, vector search, embeddings, and LightGBM reranking pipeline is ready to
be wired in.
