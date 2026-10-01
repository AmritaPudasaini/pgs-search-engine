import json
import tempfile
import unittest
from types import SimpleNamespace

from consumer import ETLStore, export_documents, process_message, validate_document


def document():
    return {
        "url": "https://example.com/news?id=1",
        "normalized_url": "https://example.com/news?id=1",
        "host": "example.com",
        "title": "Example news",
        "text": "A small document for ETL testing.",
        "headings": [{"level": 1, "text": "Example news"}],
        "links": ["https://example.com/about"],
        "anchor_texts": ["About"],
        "country": "NP",
        "depth": 1,
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "content_hash": "a" * 64,
        "fetched_at": "2026-09-18T08:00:00Z",
        "fetch_duration_ms": 42,
    }


def message(value=None, key=None, offset=7):
    value = document() if value is None else value
    key = value.get("normalized_url", "").encode() if key is None else key
    return SimpleNamespace(
        topic="crawled-documents",
        partition=0,
        offset=offset,
        key=key,
        value=json.dumps(value).encode(),
    )


class ConsumerTests(unittest.TestCase):
    def test_validates_scraper_document(self):
        self.assertEqual(validate_document(document()), document())
        for field, bad in (
            ("url", "file:///tmp/page"),
            ("content_hash", "bad"),
            ("status_code", 500),
            ("fetched_at", "2026-09-18T08:00:00"),
            ("depth", -1),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_document({**document(), field: bad})

    def test_load_is_durable_and_replay_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + "/etl.sqlite3"
            store = ETLStore(path)
            first = process_message(store, message())
            second = process_message(store, message())
            store.close()

            self.assertEqual(first["status"], "loaded")
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(list(export_documents(path)), [document()])

    def test_bad_key_and_json_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ETLStore(directory + "/etl.sqlite3")
            bad_key = process_message(store, message(key=b"wrong", offset=8))
            bad_json_message = SimpleNamespace(
                topic="crawled-documents",
                partition=0,
                offset=9,
                key=b"key",
                value=b"not-json",
            )
            bad_json = process_message(store, bad_json_message)
            rejected = store.db.execute(
                "SELECT offset_id, body FROM rejected ORDER BY offset_id"
            ).fetchall()
            store.close()

            self.assertEqual(bad_key["status"], "rejected")
            self.assertEqual(bad_json["status"], "rejected")
            self.assertEqual([row[0] for row in rejected], [8, 9])
            self.assertEqual(rejected[1][1], b"not-json")

    def test_optional_lists_accept_go_null_values(self):
        value = {**document(), "links": None}
        value.pop("anchor_texts")
        self.assertEqual(validate_document(value), value)


if __name__ == "__main__":
    unittest.main()
