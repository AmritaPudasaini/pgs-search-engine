import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from security_scanner import inspect_file

CLEAN_RESULT = {"status": "CLEAN", "signature": None}
INFECTED_RESULT = {"status": "INFECTED", "signature": "Eicar-Test-Signature"}
ERROR_RESULT = {"status": "ERROR", "signature": None, "error": "connection refused"}


class SecurityScannerTests(unittest.TestCase):
    # -- Layer 1: basic checks (ClamAV mocked as CLEAN so these test only
    #    the metadata logic, with no real network/Docker dependency) --

    @patch("security_scanner.scan_with_clamav", return_value=CLEAN_RESULT)
    def test_accepts_expected_document_type(self, mock_clamav):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notice.html"
            path.write_text("<h1>Notice</h1>", encoding="utf-8")

            result = inspect_file(path)

            self.assertTrue(result["accepted"])
            self.assertEqual(result["extension"], "html")
            self.assertEqual(result["findings"], [])
            self.assertEqual(result["verdict"], "SAFE")
            self.assertEqual(len(result["sha256"]), 64)
            mock_clamav.assert_called_once()

    @patch("security_scanner.scan_with_clamav", return_value=CLEAN_RESULT)
    def test_rejects_suspicious_extension(self, mock_clamav):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.exe"
            path.write_bytes(b"binary")

            result = inspect_file(path)

            self.assertFalse(result["accepted"])
            self.assertIn("suspicious_extension", result["findings"])
            self.assertIn("unexpected_extension", result["findings"])
            self.assertEqual(result["verdict"], "SUSPICIOUS")

    # -- Layer 2: ClamAV content scanning (mocked - no live ClamAV needed) --

    @patch("security_scanner.scan_with_clamav", return_value=INFECTED_RESULT)
    def test_rejects_clamav_detected_threat(self, mock_clamav):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.pdf"
            path.write_bytes(b"harmless-looking bytes, ClamAV mocked as FOUND")

            result = inspect_file(path)

            self.assertFalse(result["accepted"])
            self.assertEqual(result["verdict"], "INFECTED")
            self.assertTrue(any(f.startswith("clamav_infected") for f in result["findings"]))

    @patch("security_scanner.scan_with_clamav", return_value=ERROR_RESULT)
    def test_unknown_when_clamav_unavailable(self, mock_clamav):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notice.html"
            path.write_text("<h1>Notice</h1>", encoding="utf-8")

            result = inspect_file(path)

            # A ClamAV outage must NOT be silently treated as clean.
            self.assertFalse(result["accepted"])
            self.assertEqual(result["verdict"], "UNKNOWN")
            self.assertIn("clamav_unavailable", result["findings"])


if __name__ == "__main__":
    unittest.main()