from pgs_search.config import settings
from pgs_search.query.normalizer import expand_query_terms
from pgs_search.retrieval.lexical import search_bm25


class FakeClient:
    def __init__(self, hits):
        self.hits = hits
        self.search_calls = []

    def search(self, index, body):
        self.search_calls.append((index, body))
        return {"hits": {"hits": self.hits}}

    def make_search(self, query, limit=10):
        return search_bm25(self, query, limit=limit)


def fake_hits(ids):
    return [{"_id": doc_id, "_source": {"title": doc_id}} for doc_id in ids]


def _variant_queries(body):
    return [clause["multi_match"]["query"] for clause in body["query"]["bool"]["should"]]


def _multi_match_clauses(body):
    return [clause["multi_match"] for clause in body["query"]["bool"]["should"]]


def test_normalizes_query_before_searching():
    client = FakeClient(fake_hits(["doc1"]))
    client.make_search("  PokharA   VALLEY ")
    body = client.search_calls[0][1]
    assert _variant_queries(body)[0] == "pokhara valley"


def test_sends_expanded_variants_to_opensearch():
    client = FakeClient(fake_hits(["doc1"]))
    client.make_search("Kathmandu")
    body = client.search_calls[0][1]
    assert _variant_queries(body) == expand_query_terms("Kathmandu")
    assert _variant_queries(body) == ["kathmandu", "काठमाडौं"]


def test_multi_match_clauses_enable_fuzziness():
    client = FakeClient(fake_hits(["doc1"]))
    client.make_search("Katmandu")
    body = client.search_calls[0][1]
    clauses = _multi_match_clauses(body)
    assert clauses, "expected at least one multi_match clause"
    for clause in clauses:
        assert clause.get("fuzziness") == "AUTO"


class FuzzyAwareClient(FakeClient):
    def __init__(self, hit_ids):
        super().__init__([])
        self.hit_ids = hit_ids
        self.search_calls = []

    def search(self, index, body):
        self.search_calls.append((index, body))
        clauses = _multi_match_clauses(body)
        if any(clause.get("fuzziness") == "AUTO" for clause in clauses):
            return {"hits": {"hits": fake_hits(self.hit_ids)}}
        return {"hits": {"hits": []}}


def test_misspelled_query_returns_correctly_spelled_document():
    client = FuzzyAwareClient(["doc_kathmandu"])
    results = client.make_search("Katmandu")
    assert [hit["_id"] for hit in results] == ["doc_kathmandu"]
    body = client.search_calls[0][1]
    assert _variant_queries(body) == expand_query_terms("Katmandu")


def test_exact_match_behavior_unchanged():
    client = FakeClient(fake_hits(["doc_kathmandu"]))
    results = client.make_search("Kathmandu")
    assert [hit["_id"] for hit in results] == ["doc_kathmandu"]
    body = client.search_calls[0][1]
    clauses = _multi_match_clauses(body)
    assert clauses[0]["query"] == "kathmandu"
    assert clauses[0]["fields"] == ["title^3", "description^2", "searchable_text"]
    assert clauses[0]["type"] == "best_fields"


def test_searches_configured_index():
    client = FakeClient(fake_hits(["doc1"]))
    client.make_search("kathmandu")
    assert client.search_calls[0][0] == settings.opensearch_index


def test_removes_duplicate_results():
    client = FakeClient(fake_hits(["doc0", "doc0", "doc1", "doc1", "doc2"]))
    results = client.make_search("kathmandu")
    doc_ids = [hit["_id"] for hit in results]
    assert doc_ids == ["doc0", "doc1", "doc2"]
    assert len(doc_ids) == len(set(doc_ids))


def test_respects_limit():
    client = FakeClient(fake_hits([f"doc{i}" for i in range(20)]))
    results = client.make_search("kathmandu", limit=3)
    assert [hit["_id"] for hit in results] == ["doc0", "doc1", "doc2"]
    assert len(results) == 3


def test_empty_query_returns_empty_list():
    client = FakeClient(fake_hits(["doc1"]))
    results = client.make_search("   ")
    assert results == []
    assert client.search_calls == []
