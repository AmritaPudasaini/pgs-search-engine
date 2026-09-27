"""Spark Security Scanner - basic, harmless checks on a file before it
enters the pipeline (extension, size, filename, hash). This is NOT a
real virus scanner - it's a simple rule-based check for a university
project demo. Real malware scanning (ClamAV) is separate, later work.
"""

import hashlib
from typing import TYPE_CHECKING, Any, TypedDict, cast

try:
    from pyspark.sql import DataFrame
except ImportError:  # pragma: no cover - optional dependency for type checking/runtime
    DataFrame = Any  # type: ignore[misc,assignment]

if TYPE_CHECKING:
    from pyspark.sql import DataFrame as SparkDataFrame

# Extensions we treat as risky to auto-run/auto-open.
SUSPICIOUS_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "scr", "msi", "vbs", "js", "jar", "ps1", "sh"
}

# Extensions we expect to see routinely from the web crawler.
EXPECTED_EXTENSIONS = {
    "html", "htm", "pdf", "txt", "json", "png", "jpg", "jpeg", "gif", "docx", "csv"
}

MAX_SAFE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILENAME_LENGTH = 100


def get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()

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

class ScanResult(TypedDict):
    filename: str
    extension: str
    size_bytes: int
    sha256: str
    verdict: str
    reasons: list[str]


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
    
def scan_file_spark(spark: Any, filename: str, content: bytes) -> "DataFrame":
    """Same as scan_file(), but wraps the result in a Spark DataFrame -
    matches the pattern used by analyze_text() in transform.py so both
    modules look and behave the same way."""
    result = scan_file(filename, content)
    result["reasons"] = ", ".join(result["reasons"])  # flatten list for DataFrame
    df = spark.createDataFrame([result])
    # put columns in a sensible reading order (Spark would otherwise sort them A-Z)
    return df.select("filename", "extension", "size_bytes", "sha256", "verdict", "reasons")

if __name__ == "__main__":
    # Quick manual check, no Spark/Docker needed: python3 security_scanner.py
    sample = scan_file("hello.txt", b"This is a normal file used to test the Spark Security Scanner.")
    print(sample)

    from pyspark.sql import SparkSession
    from security_scanner import scan_file_spark

    spark: SparkSession = (
        SparkSession.builder
        .appName("SecurityScannerTest")
        .master("local[*]")
        .getOrCreate()
    )

    # Every file below is 100% harmless. Verdicts are triggered by
    # filename/size patterns only, never by actual malicious content.
    test_files = {
        "hello.txt": b"This is a normal file used to test the Spark Security Scanner.",
        "notice.pdf": b"%PDF-1.4 dummy pdf content for testing",
        "photo.jpg": b"dummy jpeg bytes for testing",
        "weird_report.xyz": b"harmless content with an unusual extension",
        "a_very_long_filename_that_someone_might_accidentally_save_from_a_browser_download_dialog_without_editing_it.txt": b"short harmless content",
    }

    for filename, content in test_files.items():
        df = scan_file_spark(spark, filename, content)
        df.show(truncate=60)  # type: ignore[union-attr]

    spark.stop()
        