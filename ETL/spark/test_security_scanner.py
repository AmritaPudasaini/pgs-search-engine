import tempfile
import unittest
from pathlib import Path

from security_scanner import inspect_file


class SecurityScannerTests(unittest.TestCase):
    def test_accepts_expected_document_type(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notice.html"
            path.write_text("<h1>Notice</h1>", encoding="utf-8")

            result = inspect_file(path)

            self.assertTrue(result["accepted"])
            self.assertEqual(result["extension"], "html")
            self.assertEqual(result["findings"], [])
            self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_suspicious_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.exe"
            path.write_bytes(b"binary")

            result = inspect_file(path)

            self.assertFalse(result["accepted"])
            self.assertIn("suspicious_extension", result["findings"])
            self.assertIn("unexpected_extension", result["findings"])


if __name__ == "__main__":
    unittest.main()
