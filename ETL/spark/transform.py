from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

WORD_RE = re.compile(r"[\w\u0900-\u097F]+", re.UNICODE) # create tokens like ["Hello", "नेपाल", "123"]
SPACE_RE = re.compile(r"\s+") # remove space

@dataclass(frozen=True)
class GeoRule:
    province: str
    district: str
    municipality: str
    aliases: tuple[str, ...]

SAMPLE_GEO_RULES = (
    GeoRule(
        province="Bagmati Province",
        district="Kathmandu",
        municipality="Kathmandu Metropolitan City",
        aliases=("kathmandu", "kathmandu metropolitan", "kathmandu metropolitan city"),
    ),
    GeoRule(
        province="Gandaki Province",
        district="Kaski",
        municipality="Pokhara Metropolitan City",
        aliases=("pokhara", "pokhara metropolitan", "pokhara metropolitan city"),
    ),
    GeoRule(
        province="Madhesh Province",
        district="Dhanusha",
        municipality="Janakpur Sub-Metropolitan City",
        aliases=("janakpur", "janakpurdham", "janakpur sub-metropolitan"),
    ),
)

class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0 # tracks whether the parser is currently inside tags that should be ignored, like <script> or <style>.

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return normalize_text(" ".join(self._parts))

def normalize_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip() # replace spaces with text or if text null then ""

def extract_html_text(raw_html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(raw_html)
    return parser.text()

def extract_pdf_text(raw_bytes: bytes) -> str:
    """Extract text from a PDF using pypdf when available."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires pypdf; install ETL/spark requirements") from exc

    reader = PdfReader(io.BytesIO(raw_bytes))
    return normalize_text(" ".join(page.extract_text() or "" for page in reader.pages))

def extract_text_from_file(path: str | Path, content_type: str | None = None) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    kind = (content_type or "").lower()

    if suffix == ".pdf" or "pdf" in kind:
        return extract_pdf_text(file_path.read_bytes())

    raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".html", ".htm"} or "html" in kind:
        return extract_html_text(raw_text)
    return normalize_text(raw_text)

def detect_language(text: str) -> str:
    devanagari = sum(1 for char in text if "\u0900" <= char <= "\u097F")
    latin = sum(1 for char in text if ("A" <= char <= "Z") or ("a" <= char <= "z"))
    if devanagari and latin:
        return "mixed"
    if devanagari:
        return "ne"
    if latin:
        return "en"
    return "unknown"

def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in WORD_RE.finditer(text)]

def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()

def simhash_text(text: str, bits: int = 64) -> int:
    tokens = tokenize(text)
    if not tokens:
        return 0

    weights = [0] * bits
    for token in tokens:
        digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        for index in range(bits):
            weights[index] += 1 if digest & (1 << index) else -1

    fingerprint = 0
    for index, weight in enumerate(weights):
        if weight > 0:
            fingerprint |= 1 << index
    return fingerprint

def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count() # if diff bits then 1 and counts all those 1s

def resolve_geo(text: str, domain: str = "") -> dict[str, str] | None:
    haystack = f"{domain} {text}".lower()
    for rule in SAMPLE_GEO_RULES:
        if any(alias in haystack for alias in rule.aliases):
            return {
                "province": rule.province,
                "district": rule.district,
                "municipality": rule.municipality,
                "source": "seed_gazetteer",
            }
    return None


EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL_NAME", "sentence-transformers/LaBSE"
)
_embedding_model = None


def _get_embedding_model():
    """Load and cache the configured sentence-transformers model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Embeddings require sentence-transformers; install ETL dependencies"
            ) from exc
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def generate_embeddings(
    texts: list[str], batch_size: int = 32
) -> list[list[float] | None]:
    """Generate normalized LaBSE vectors, chunking long inputs to avoid truncation."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    results: list[list[float] | None] = [None for _ in texts]
    if not any(text and text.strip() for text in texts):
        return results

    model = _get_embedding_model()
    tokenizer = model.tokenizer
    chunk_size = model.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
    if chunk_size < 1:
        raise ValueError("Model max_seq_length must allow at least one text token")

    chunks: list[str] = []
    owners: list[int] = []
    for index, text in enumerate(texts):
        if not text or not text.strip():
            continue
        token_ids = tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"]
        for start in range(0, len(token_ids), chunk_size):
            chunk = tokenizer.decode(
                token_ids[start : start + chunk_size], skip_special_tokens=True
            )
            if chunk.strip():
                chunks.append(chunk)
                owners.append(index)

    if not chunks:
        return results

    vectors = model.encode(
        chunks,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    grouped: list[list] = [[] for _ in texts]
    for index, vector in zip(owners, vectors):
        grouped[index].append(vector)

    for index, document_vectors in enumerate(grouped):
        if document_vectors:
            mean_vector = sum(document_vectors) / len(document_vectors)
            norm = float((mean_vector**2).sum() ** 0.5)
            if norm:
                results[index] = [float(value) for value in mean_vector / norm]
    return results


def generate_embedding(text: str) -> list[float] | None:
    """Generate one normalized LaBSE vector, or None for blank text."""
    return generate_embeddings([text])[0]

def transform_document( # * means, after it, all should be named
    *,
    source_url: str,
    text: str,
    title: str = "",
    target_domain: str = "",
    object_key: str = "",
    with_embedding: bool = False,
) -> dict:
    normalized = normalize_text(text)
    exact_hash = sha256_text(normalized)
    simhash = simhash_text(normalized)
    tokens = tokenize(normalized)
    embedding = generate_embedding(normalized) if with_embedding else None

    return {
        "document_id": f"doc_{exact_hash[:12]}",
        "source_url": source_url,
        "object_key": object_key,
        "target_domain": target_domain,
        "title": title,
        "language_detected": detect_language(normalized),
        "searchable_text": normalized,
        "word_count": len(tokens),
        "char_count": len(normalized),
        "content_sha256": exact_hash,
        "simhash": f"{simhash:016x}",
        "geo_location": resolve_geo(normalized, target_domain),
        "duplicate": False,
        "duplicate_type": None,
        "duplicate_of": None,
        "embedding": embedding,
        "embedding_model": EMBEDDING_MODEL_NAME if embedding else None,
        "embedding_dim": len(embedding) if embedding else 0,
    }


def add_embeddings(
    documents: list[dict], batch_size: int = 32
) -> list[dict]:
    """Add LaBSE vectors to transformed documents in batches."""
    vectors = generate_embeddings(
        [document["searchable_text"] for document in documents], batch_size
    )
    for document, vector in zip(documents, vectors):
        document["embedding"] = vector
        document["embedding_model"] = EMBEDDING_MODEL_NAME if vector else None
        document["embedding_dim"] = len(vector) if vector else 0
    return documents


def transform_file(
    signal: dict, dfs_root: str | Path, *, with_embedding: bool = True
) -> dict:
    object_key = signal["object_key"]
    file_path = Path(dfs_root) / object_key
    from security_scanner import inspect_file

    security_scan = inspect_file(file_path)
    if not security_scan["accepted"]:
        raise ValueError(f"File failed intake security checks: {security_scan['findings']}")

    text = extract_text_from_file(file_path, signal.get("content_type"))
    transformed = transform_document(
        source_url=signal.get("source_url") or signal.get("page_url") or "",
        text=text,
        title=signal.get("title", ""),
        target_domain=signal.get("target_domain", ""),
        object_key=object_key,
        with_embedding=with_embedding,
    )
    transformed["security_scan"] = security_scan
    return transformed

def mark_duplicates(documents: Iterable[dict], fuzzy_distance: int = 3) -> list[dict]:
    """Mark exact SHA256 duplicates and near-duplicates by SimHash distance."""
    seen_hashes: dict[str, str] = {}
    seen_simhashes: list[tuple[int, str]] = []
    output: list[dict] = []

    for document in documents:
        current = dict(document)
        exact_hash = current["content_sha256"]
        simhash = int(current["simhash"], 16)

        if exact_hash in seen_hashes:
            current["duplicate"] = True
            current["duplicate_type"] = "exact_sha256"
            current["duplicate_of"] = seen_hashes[exact_hash]
        else:
            for previous_simhash, previous_id in seen_simhashes:
                if hamming_distance(simhash, previous_simhash) <= fuzzy_distance:
                    current["duplicate"] = True
                    current["duplicate_type"] = "simhash"
                    current["duplicate_of"] = previous_id
                    break

        if not current["duplicate"]:
            seen_hashes[exact_hash] = current["document_id"]
            seen_simhashes.append((simhash, current["document_id"]))
        output.append(current)

    return output

def append_jsonl(path: str | Path, records: Iterable[dict]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def analyze_text(spark, text: str):
    """Spark DataFrame wrapper used by the Docker Spark smoke test."""
    from pyspark.sql.types import (
        BooleanType,
        IntegerType,
        MapType,
        StringType,
        StructField,
        StructType,
        ArrayType,
        FloatType,
    )

    transformed = transform_document(source_url="", text=text)
    schema = StructType(
        [
            StructField("document_id", StringType(), nullable=False),
            StructField("source_url", StringType(), nullable=False),
            StructField("object_key", StringType(), nullable=False),
            StructField("target_domain", StringType(), nullable=False),
            StructField("title", StringType(), nullable=False),
            StructField("language_detected", StringType(), nullable=False),
            StructField("searchable_text", StringType(), nullable=False),
            StructField("word_count", IntegerType(), nullable=False),
            StructField("char_count", IntegerType(), nullable=False),
            StructField("content_sha256", StringType(), nullable=False),
            StructField("simhash", StringType(), nullable=False),
            StructField("geo_location", MapType(StringType(), StringType()), nullable=True),
            StructField("duplicate", BooleanType(), nullable=False),
            StructField("duplicate_type", StringType(), nullable=True),
            StructField("duplicate_of", StringType(), nullable=True),
            StructField("embedding", ArrayType(FloatType()), nullable=True),
            StructField("embedding_model", StringType(), nullable=True),
            StructField("embedding_dim", IntegerType(), nullable=False),
        ]
    )
    return spark.createDataFrame([transformed], schema=schema)
