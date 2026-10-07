from unittest.mock import MagicMock, patch

import numpy as np

from pgs_search.query.embeddings import get_query_vector


def _fake_vector():
    return np.zeros(384, dtype=np.float32)


def _patched_model():
    model = MagicMock()
    model.encode.return_value = _fake_vector()
    return patch("pgs_search.query.embeddings.get_model", return_value=model), model


def test_get_query_vector_calls_encoder_with_text():
    patcher, model = _patched_model()
    with patcher:
        get_query_vector("hospital budget")
    model.encode.assert_called_once_with("hospital budget")


def test_get_query_vector_returns_list():
    patcher, _ = _patched_model()
    with patcher:
        vector = get_query_vector("hospital budget")
    assert isinstance(vector, list)


def test_get_query_vector_length_is_384():
    patcher, _ = _patched_model()
    with patcher:
        vector = get_query_vector("hospital budget")
    assert len(vector) == 384


def test_get_query_vector_items_are_floats():
    patcher, _ = _patched_model()
    with patcher:
        vector = get_query_vector("hospital budget")
    assert all(isinstance(item, float) for item in vector)