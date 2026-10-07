import io
import json
import unittest
from unittest import mock

import site_pipeline
from site_pipeline import ScannerUnavailable, process_page, validate_event

EVENT = {
    "event_type": "site_crawl_completed",
    "crawl_run_id": 7,
    "target_domain": "ward.gov.np",
    "status": "completed",
    "bucket": "crawled-pages",
    "key_prefix": "dev",
    "documents_prefix": "dev/7/ward.gov.np/",
}

HTML = b"<html><body><h1>Ward Office</h1><p>Public notice for Kathmandu</p></body></html>"


class FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.read = []

    def get_object(self, Bucket, Key):
        self.read.append(Key)
        return {"Body": io.BytesIO(self.objects[Key])}


def scan(status="CLEAN", accepted=True):
    findings = [] if accepted else ["x"]
    return {"accepted": accepted, "clamav_status": status, "findings": findings, "verdict": "SAFE"}


class ValidateEventTests(unittest.TestCase):
    def test_accepts_a_site_event(self):
        self.assertIs(validate_event(EVENT), EVENT)

    def test_rejects_other_messages(self):
        for bad in ({}, {**EVENT, "event_type": "file_ready"}, {**EVENT, "bucket": ""},
                    {**EVENT, "documents_prefix": "dev/7/ward.gov.np"}, ["not", "a", "dict"]):
            with self.assertRaises(ValueError):
                validate_event(bad)


class ProcessPageTests(unittest.TestCase):
    def setUp(self):
        document = {
            "url": "https://ward.gov.np/notice",
            "title": "Notice",
            "html_key": "html/ward.gov.np/abc.html",
        }
        self.s3 = FakeS3({
            "dev/7/ward.gov.np/1.json": json.dumps(document).encode(),
            "dev/html/ward.gov.np/abc.html": HTML,
        })

    def test_scans_and_transforms_the_stored_html(self):
        with mock.patch("security_scanner.inspect_bytes", return_value=scan()) as inspect:
            result = process_page(self.s3, EVENT, "dev/7/ward.gov.np/1.json")
        inspect.assert_called_once_with("abc.html", HTML)
        self.assertEqual(result["status"], "transformed")
        record = result["record"]
        self.assertEqual(record["searchable_text"], "Ward Office Public notice for Kathmandu")
        self.assertEqual(record["object_key"], "s3://crawled-pages/dev/html/ward.gov.np/abc.html")
        self.assertEqual((record["crawl_run_id"], record["target_domain"]), (7, "ward.gov.np"))

    def test_rejected_page_is_not_transformed(self):
        infected = scan(status="INFECTED", accepted=False)
        with mock.patch("security_scanner.inspect_bytes", return_value=infected):
            result = process_page(self.s3, EVENT, "dev/7/ward.gov.np/1.json")
        self.assertEqual(result["status"], "rejected")

    def test_unreachable_clamav_fails_instead_of_rejecting(self):
        unscanned = scan(status="ERROR", accepted=False)
        with (
            mock.patch("security_scanner.inspect_bytes", return_value=unscanned),
            self.assertRaises(ScannerUnavailable),
        ):
            process_page(self.s3, EVENT, "dev/7/ward.gov.np/1.json")


class AlreadyProcessedTests(unittest.TestCase):
    def test_a_retried_site_is_skipped(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.jsonl"
            done = {"crawl_run_id": 7, "target_domain": "ward.gov.np"}
            output.write_text(json.dumps(done) + "\n")
            with mock.patch("site_pipeline.list_document_keys") as listing:
                summary = site_pipeline.run_site_pipeline(EVENT, output)
            listing.assert_not_called()
            self.assertTrue(summary["already_processed"])
            self.assertFalse(site_pipeline._already_processed(output, 8, "ward.gov.np"))


class DedupeTests(unittest.TestCase):
    def test_duplicate_reuses_the_canonical_embedding(self):
        from transform import transform_document

        existing = transform_document(source_url="https://a.np", text="same notice text")
        existing["embedding"], existing["embedding_dim"] = [0.5], 1
        new = transform_document(source_url="https://b.np", text="same notice text")
        with mock.patch("transform.add_embeddings") as embed:
            [marked] = site_pipeline.dedupe_and_embed([new], [existing])
        embed.assert_called_once_with([])
        self.assertTrue(marked["duplicate"])
        self.assertEqual(marked["embedding"], [0.5])


if __name__ == "__main__":
    unittest.main()
