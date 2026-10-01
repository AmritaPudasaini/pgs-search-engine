shreya/bilingual-query-normalization
# PGS Search Engine Core

Python search engine core for the PGS bilingual (English/Nepali) search backend.
Searches an OpenSearch index of Nepalese web pages using BM25 with fuzzy matching
and query-time normalization/expansion.

## Implemented Features

- **Language detection** for English, Nepali, mixed, and unknown queries
  (`detect_language` in `pgs_search/query/normalizer.py`).
- **Unicode and whitespace normalization** — NFC normalization and collapsing of
  runs of whitespace (`normalize_query`).
- **English lowercasing** — applied to Latin-script queries during normalization.
- **Place-name expansion** — English-to-Nepali and Nepali-to-English expansion
  using a fixed EN-NE place dictionary (`query/data/en_ne_places.json`), applied
  to the full normalized query and each of its tokens.
- **Romanized Nepali recognition** — common romanized Nepali words and place
  names are detected (`detect_language`).
- **Fuzzy/typo-tolerant BM25 matching** — a `multi_match` query with
  `fuzziness: "AUTO"` over title, description, and searchable text
  (`pgs_search/retrieval/lexical.py`).
- **English stemming** — NLTK `PorterStemmer` stems English Latin-script tokens;
  stemmed query added as an additional search variant (`lemmatize_query`).
- **English ↔ Nepali machine translation** — `facebook/nllb-200-distilled-600M`
  (NLLB-200) translates a query in either direction, using the `npi_Deva` and
  `eng_Latn` language codes. The model and tokenizer are loaded once and cached
  with `functools.lru_cache` (`pgs_search/query/translation.py`).
- **Cross-language query expansion** — `expand_query_terms` translates the full
  original query when `detect_language` returns `"en"` or `"ne"` and appends the
  result as one more search variant, alongside normalization, stemming /
  lemmatization, and place-name expansion. Mixed and unknown queries are never
  translated. A translation failure is caught and logged as a warning, so the
  normal expansion variants are still returned.
- **Standalone query-vector generation** — `all-MiniLM-L6-v2` via
  `SentenceTransformer`, cached with `functools.lru_cache`
  (`pgs_search/query/embeddings.py`). Not yet integrated into retrieval.
- **Result processing** — duplicate-result removal and blank-query handling
  (blank queries return no results without contacting OpenSearch).

## Known Limitations / Out of Scope

- **Translation only feeds query expansion.** It is not wired into retrieval,
  ranking, indexing, or result generation; the translated term is just another
  search variant handed to the existing search path.
- **Only single-language queries are translated.** `detect_language` returning
  `"mixed"` or `"unknown"` skips translation entirely.
- **Nepali lemmatization is not implemented.** The stemmer is English-only and
  leaves Devanagari tokens untouched; Nepali morphological analysis is out of
  scope.
- **Semantic reranking is not integrated.** Query vectors can be generated but
  are not wired into search/reranking; that belongs to a separate task.
- **Live BM25 search requires OpenSearch** to be running and reachable at the
  configured host/port/index (see `pgs_search/config.py`).
- **The first embedding call may download** the `all-MiniLM-L6-v2`
  sentence-transformer model from Hugging Face.
- **The first translation call downloads** the `facebook/nllb-200-distilled-600M`
  model (~2.3 GB) from Hugging Face and keeps it in memory for the process
  lifetime. The test suite mocks the loader, so tests never download it.

## Quick Start

```bash
pip install -e ".[dev]"
py -m pytest -q
```
=======
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
search-engine
