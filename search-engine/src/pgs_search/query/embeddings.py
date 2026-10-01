"""Sentence-embedding helpers for queries."""

from functools import lru_cache

from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the sentence-transformer model once and cache it."""
    return SentenceTransformer("all-MiniLM-L6-v2")


def get_query_vector(text: str) -> list[float]:
    """Embed a query and return it as a plain list of floats."""
    vector = get_model().encode(text)
    return [float(x) for x in vector.tolist()]