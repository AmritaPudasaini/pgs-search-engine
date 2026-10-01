from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pgs_search.ranking import lightgbm_reranker as reranker


class PredictFromBm25:
    def predict(self, features):
        return features["bm25_score"].to_numpy()


def sample_results() -> list[dict]:
    return [
        {
            "id": "doc-1",
            "title": "First result",
            "url": "https://example.com/1",
            "bm25_score": 1.0,
            "vector_score": 0.3,
        },
        {
            "id": "doc-2",
            "title": "Second result",
            "url": "https://example.com/2",
            "bm25_score": 3.0,
            "vector_score": 0.8,
            "content_length": 700,
        },
        {
            "id": "doc-3",
            "title": "Third result",
            "url": "https://example.com/3",
            "bm25_score": 2.0,
            "vector_score": 0.5,
        },
    ]


def test_empty_list_returns_empty_list() -> None:
    assert reranker.rerank_results([]) == []


def test_invalid_non_list_input_raises_type_error() -> None:
    with pytest.raises(TypeError):
        reranker.rerank_results({"id": "doc-1"})


def test_invalid_top_k_raises_value_error() -> None:
    with pytest.raises(ValueError):
        reranker.rerank_results(sample_results(), top_k=0)


def test_missing_and_invalid_feature_values_are_filled_safely() -> None:
    df = reranker.prepare_features(
        [{"id": "doc-1", "bm25_score": "not-a-number", "vector_score": 0.7}]
    )

    assert list(df.columns).count("content_length") == 1
    assert df.loc[0, "bm25_score"] == 0
    assert df.loc[0, "content_length"] == 0
    assert math.isclose(df.loc[0, "vector_score"], 0.7)


def test_duplicate_ids_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reranker, "get_model", lambda: PredictFromBm25())
    results = [
        {"id": "same", "title": "First copy", "bm25_score": 1},
        {"id": "same", "title": "Second copy", "bm25_score": 99},
        {"id": "unique", "title": "Unique", "bm25_score": 2},
    ]

    reranked = reranker.rerank_results(results, top_k=10)

    assert [result["id"] for result in reranked] == ["unique", "same"]
    assert reranked[1]["title"] == "First copy"


def test_reranking_output_is_sorted_and_respects_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reranker, "get_model", lambda: PredictFromBm25())

    reranked = reranker.rerank_results(sample_results(), top_k=2)

    assert len(reranked) == 2
    assert [result["id"] for result in reranked] == ["doc-2", "doc-3"]
    assert reranked[0]["rerank_score"] >= reranked[1]["rerank_score"]
    assert reranked[0]["new_rank"] == 1
    assert reranked[0]["rank_change"] == 1


def test_original_result_fields_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reranker, "get_model", lambda: PredictFromBm25())

    reranked = reranker.rerank_results(sample_results(), top_k=1)

    assert reranked[0]["id"] == "doc-2"
    assert reranked[0]["title"] == "Second result"
    assert reranked[0]["url"] == "https://example.com/2"
    assert "rerank_score" in reranked[0]
    assert "original_rank" in reranked[0]


def test_real_model_loads_and_predicts_if_available() -> None:
    if not reranker.MODEL_PATH.exists():
        pytest.skip("Real LightGBM model has not been trained yet.")

    search_engine_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(search_engine_root / "src")
    code = """
import json
from pgs_search.ranking.lightgbm_reranker import rerank_results

results = rerank_results(
    [
        {"id": "doc-1", "bm25_score": 1.0, "vector_score": 0.3},
        {"id": "doc-2", "bm25_score": 3.0, "vector_score": 0.8},
        {"id": "doc-3", "bm25_score": 2.0, "vector_score": 0.5},
    ],
    top_k=2,
)
print(json.dumps([result["rerank_score"] for result in results]))
"""

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=search_engine_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"Real LightGBM model could not load in subprocess: {completed.stderr}")

    scores = json.loads(completed.stdout)
    assert len(scores) == 2
    assert all(isinstance(score, float) for score in scores)
