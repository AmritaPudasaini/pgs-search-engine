"""Shared test fixtures."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pgs_search.query import normalizer


@pytest.fixture(autouse=True)
def stub_translation() -> SimpleNamespace:
    """Stub the NLLB translation calls used by query expansion.

    The model is a ~2.3 GB download, far too heavy for the unit-test suite, and
    query expansion is the only production caller. Stubbing is applied to every
    test so no test can accidentally trigger a real translation; the default
    return value of "" means query expansion behaves as if translation were
    unavailable, which keeps expansion results and counts unchanged.

    Tests that assert on translation behavior take this fixture and set their
    own return_value or side_effect on the exposed mocks.
    """
    with (
        patch.object(normalizer, "translate_to_nepali", return_value="") as to_nepali,
        patch.object(normalizer, "translate_to_english", return_value="") as to_english,
    ):
        yield SimpleNamespace(to_nepali=to_nepali, to_english=to_english)
