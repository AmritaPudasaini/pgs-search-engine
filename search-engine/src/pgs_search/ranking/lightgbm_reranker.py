"""LightGBM reranking helpers for search results."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

logger = logging.getLogger(__name__)

FEATURES = [
    "bm25_score",
    "vector_score",
    "title_match",
    "geo_match",
    "freshness",
    "source_authority",
    "language_match",
    "query_term_ratio",
    "content_length",
]

SEARCH_ENGINE_ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = SEARCH_ENGINE_ROOT / "models" / "lightgbm_reranker.pkl"


@lru_cache(maxsize=1)
def get_model() -> Any:
    """Load and cache the trained LightGBM reranker model."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "LightGBM reranker model is missing. Expected it at "
            f"{MODEL_PATH}. Run `PYTHONPATH=search-engine/src "
            "python search-engine/scripts/train_reranker.py` to create it."
        )

    logger.info("Loading LightGBM reranker model from %s", MODEL_PATH)
    return joblib.load(MODEL_PATH)


def prepare_features(results: list[dict[str, Any]]) -> pd.DataFrame:
    """Return a DataFrame with all reranker features coerced to safe numeric values."""
    if not isinstance(results, list):
        raise TypeError("results must be provided as a list.")

    logger.info("Preparing LightGBM features for %d result(s).", len(results))
    df = pd.DataFrame(results).copy()

    missing_features = [feature for feature in FEATURES if feature not in df.columns]
    for feature in missing_features:
        df[feature] = 0

    if missing_features:
        logger.warning("Added missing LightGBM feature(s) with default 0: %s", missing_features)

    df[FEATURES] = df[FEATURES].apply(pd.to_numeric, errors="coerce")
    df[FEATURES] = df[FEATURES].replace([float("inf"), float("-inf")], pd.NA)
    invalid_count = int(df[FEATURES].isna().sum().sum())

    if invalid_count:
        logger.warning("Replaced %d invalid LightGBM feature value(s) with 0.", invalid_count)

    df[FEATURES] = df[FEATURES].fillna(0)
    return df


def rerank_results(results: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
    """Rerank search results with the trained LightGBM model."""
    if not isinstance(results, list):
        logger.error("Invalid results type for LightGBM reranking: %s", type(results).__name__)
        raise TypeError("results must be provided as a list.")

    if not results:
        logger.info("No search results provided for LightGBM reranking.")
        return []

    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        logger.error("Invalid top_k value for LightGBM reranking: %r", top_k)
        raise ValueError("top_k must be a positive integer.")

    df = prepare_features(results)
    df["original_rank"] = range(1, len(df) + 1)

    original_count = len(df)
    if "id" in df.columns:
        df = df.drop_duplicates(subset=["id"], keep="first")

    duplicate_count = original_count - len(df)
    if duplicate_count:
        logger.warning("Removed %d duplicate LightGBM result(s).", duplicate_count)

    model = get_model()
    df["rerank_score"] = model.predict(df[FEATURES])
    df["rerank_score"] = pd.to_numeric(df["rerank_score"], errors="coerce")
    invalid_scores = int(df["rerank_score"].isna().sum())

    if invalid_scores:
        logger.warning("Replaced %d invalid LightGBM prediction score(s) with 0.", invalid_scores)

    df["rerank_score"] = df["rerank_score"].fillna(0)
    df = df.sort_values("rerank_score", ascending=False, kind="mergesort")
    df["new_rank"] = range(1, len(df) + 1)
    df["rank_change"] = df["original_rank"] - df["new_rank"]

    reranked = df.head(top_k).to_dict(orient="records")
    logger.info("Returning %d LightGBM reranked result(s).", len(reranked))
    return reranked
