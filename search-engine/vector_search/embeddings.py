"""Embedding generation. The model is loaded lazily, on first use."""
from collections.abc import Sequence
from functools import lru_cache
from importlib import import_module
from typing import Protocol, cast, overload

from .config import EMBEDDING_DIM, EMBEDDING_MODEL


class _VectorArray(Protocol):
    def tolist(self) -> list[float]: ...


class _SentenceEncoder(Protocol):
    @overload
    def encode(self, sentences: str, *, normalize_embeddings: bool) -> _VectorArray: ...

    @overload
    def encode(
        self, sentences: Sequence[str], *, normalize_embeddings: bool, batch_size: int
    ) -> Sequence[_VectorArray]: ...


@lru_cache(maxsize=1)
def _get_model() -> _SentenceEncoder:
    sentence_transformers = import_module("sentence_transformers")
    sentence_transformer = sentence_transformers.SentenceTransformer
    return cast(_SentenceEncoder, sentence_transformer(EMBEDDING_MODEL))


def get_model() -> _SentenceEncoder:
    """Load and cache the configured sentence-transformer model."""
    return _get_model()


def _check_dim(vec: list[float]) -> list[float]:
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding has {len(vec)} dims but EMBEDDING_DIM={EMBEDDING_DIM}. "
            "Fix EMBEDDING_DIM or EMBEDDING_MODEL."
        )
    return vec


def generate_embedding(text: str) -> list[float]:
    if not text or not text.strip():
        raise ValueError("Text cannot be empty.")
    vec = _get_model().encode(text, normalize_embeddings=True).tolist()
    return _check_dim(vec)


def generate_embeddings(texts: Sequence[str], batch_size: int = 64) -> list[list[float]]:
    """Batch version, used by the backfill script."""
    if any(not t or not t.strip() for t in texts):
        raise ValueError("Texts cannot be empty.")
    vecs = _get_model().encode(
        texts, normalize_embeddings=True, batch_size=batch_size
    )
    return [_check_dim(v.tolist()) for v in vecs]


def to_pgvector(vec: Sequence[float]) -> str:
    """Format a vector as a pgvector text literal, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
