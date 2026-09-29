"""Spark Security Scanner - basic, harmless checks on a file before it
enters the pipeline (extension, size, filename, hash). This is NOT a
real virus scanner - it's a simple rule-based check for a university
project demo. Real malware scanning (ClamAV) is separate, later work.
"""

# Security Scanner
# -----------------
# Basic, rule-based checks run on each file before it's handed to
# transform.py. Not a real antivirus - for real malware detection see
# the ClamAV step described in the main ETL README.
#
# Checks performed:
#   - Extension    - flags known-risky extensions (.exe, .bat, etc.)
#                    and unrecognized ones.
#   - Size         - flags empty files and files over 10 MB.
#   - Filename     - flags unusually long names and double-extension
#                    patterns (e.g. invoice.pdf.exe).
#   - SHA-256 hash - a content fingerprint, for later duplicate detection.
#
# Returns one of SAFE, SUSPICIOUS, or UNKNOWN, with reasons.

import hashlib
from typing import Any, TypedDict


class ScanResult(TypedDict):
    filename: str
    extension: str
    size_bytes: int
    sha256: str
    verdict: str
    reasons: list[str]


# Extensions we treat as risky to auto-run/auto-open.
SUSPICIOUS_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "scr",
    "msi", "vbs", "js", "jar", "ps1", "sh",
}

# Extensions we expect to see routinely from the web crawler.
EXPECTED_EXTENSIONS = {
    "html", "htm", "pdf", "txt", "json",
    "png", "jpg", "jpeg", "gif", "docx", "csv",
}

MAX_SAFE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILENAME_LENGTH = 100


def get_extension(filename: str) -> str:
    name = filename.lstrip(".")  # ignore one leading dot, e.g. hidden files like .gitattributes
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def get_file_size(content: bytes) -> int:
    return len(content)


def get_sha256(content: bytes) -> str:
    """Return the SHA-256 hash of the file content as a hex string.

    Verified example: hashing the hello.txt sample content gives
    a3a8893ea3e12eab2e099103b9af1ebedd80e9b7b812a23909dc4d4d607e1a55
    """
    return hashlib.sha256(content).hexdigest()


def has_double_extension(filename: str) -> bool:
    parts = filename.split(".")
    return len(parts) > 2


def scan_file(filename: str, content: bytes) -> ScanResult:
    suspicious_reasons: list[str] = []
    unknown_reasons: list[str] = []

    ext = get_extension(filename)
    if ext in SUSPICIOUS_EXTENSIONS:
        suspicious_reasons.append(f"'.{ext}' is a risky/executable extension")
    elif ext == "":
        unknown_reasons.append("file has no extension - can't identify its type")
    elif ext not in EXPECTED_EXTENSIONS:
        unknown_reasons.append(f"'.{ext}' is not a recognized extension")

    if has_double_extension(filename):
        suspicious_reasons.append("filename has multiple extensions (e.g. file.pdf.exe pattern)")

    size = get_file_size(content)
    if size == 0:
        suspicious_reasons.append("file is empty (0 bytes)")
    elif size > MAX_SAFE_SIZE_BYTES:
        suspicious_reasons.append(f"file is larger than {MAX_SAFE_SIZE_BYTES} bytes")

    if len(filename) > MAX_FILENAME_LENGTH:
        suspicious_reasons.append(f"filename is unusually long ({len(filename)} characters)")

    if suspicious_reasons:
        verdict = "SUSPICIOUS"
        reasons = suspicious_reasons
    elif unknown_reasons:
        verdict = "UNKNOWN"
        reasons = unknown_reasons
    else:
        verdict = "SAFE"
        reasons = ["no issues found"]

    return {
        "filename": filename,
        "extension": ext,
        "size_bytes": size,
        "sha256": get_sha256(content),
        "verdict": verdict,
        "reasons": reasons,
    }


def scan_file_spark(spark: Any, filename: str, content: bytes) -> Any:
    """Same as scan_file(), but wraps the result in a Spark DataFrame -
    matches the pattern used by analyze_text() in transform.py so both
    modules look and behave the same way."""
    result = scan_file(filename, content)
    spark_result: dict[str, Any] = {
        "filename": result["filename"],
        "extension": result["extension"],
        "size_bytes": result["size_bytes"],
        "sha256": result["sha256"],
        "verdict": result["verdict"],
        "reasons": ", ".join(result["reasons"]),  # flatten list for DataFrame
    }
    df = spark.createDataFrame([spark_result])
    # put columns in a sensible reading order (Spark would otherwise sort them A-Z)
    return df.select("filename", "extension", "size_bytes", "sha256", "verdict", "reasons")


if __name__ == "__main__":
    # Quick manual check, no Spark/Docker needed: python3 security_scanner.py
    sample = scan_file("hello.txt", b"This is a normal file used to test the Spark Security Scanner.")
    print(sample)