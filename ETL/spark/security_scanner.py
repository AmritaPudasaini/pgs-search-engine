"""Spark Security Scanner - two layers of checks on a file before it
enters the pipeline:

  Layer 1: basic, metadata-only checks (extension, size, filename, hash).
  Layer 2: real content scanning via ClamAV (the clamd daemon).

Layer 1 alone cannot see inside a file - a file called invoice.pdf could
still contain a real payload. Layer 2 closes that gap using an actual
antivirus engine instead of us trying to write one.
"""

import hashlib
import io
import os
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

# ClamAV (clamd) connection settings. Overridable via environment variables
# so the same code works whether the scanner runs directly on the host
# (CLAMD_HOST=localhost) or inside a Docker container that needs to reach
# the host (CLAMD_HOST=host.docker.internal).
CLAMD_HOST = os.environ.get("CLAMD_HOST", "localhost")
CLAMD_PORT = int(os.environ.get("CLAMD_PORT", "3310"))
CLAMD_TIMEOUT_SECONDS = 15


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
    """Layer 1: fast, metadata-only checks. No network access, no ClamAV -
    kept pure and easy to unit test on its own."""
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


def scan_with_clamav(content: bytes) -> dict[str, Any]:
    """Layer 2: send the actual file bytes to ClamAV (clamd) over the
    network and ask it to scan them. This is real antivirus scanning -
    we are not attempting to detect malware ourselves.

    Returns one of:
      {"status": "CLEAN",    "signature": None}
      {"status": "INFECTED", "signature": "<threat name>"}
      {"status": "ERROR",    "signature": None, "error": "<message>"}

    A connection failure or any unexpected response is always ERROR,
    never CLEAN - a security check that fails open is not a security
    check.
    """
    import clamd

    try:
        client = clamd.ClamdNetworkSocket(
            host=CLAMD_HOST, port=CLAMD_PORT, timeout=CLAMD_TIMEOUT_SECONDS
        )
        response = client.instream(io.BytesIO(content))
        status, signature = response["stream"]
    except Exception as exc:  # clamd down, connection refused, timeout, etc.
        return {"status": "ERROR", "signature": None, "error": str(exc)}

    if status == "OK":
        return {"status": "CLEAN", "signature": None}
    if status == "FOUND":
        return {"status": "INFECTED", "signature": signature}
    return {"status": "ERROR", "signature": None, "error": f"unexpected clamd status: {status!r}"}


def inspect_file(path: str) -> dict[str, Any]:
    """Return the intake-check contract consumed by transform_file().

    Combines Layer 1 (basic checks) and Layer 2 (ClamAV content scan)
    into one verdict: SAFE, SUSPICIOUS, INFECTED, or UNKNOWN.

    accepted is True only when Layer 1 found nothing AND ClamAV actively
    confirmed the content is clean. If ClamAV can't be reached, the file
    is NOT accepted - an unreachable scanner is not the same as a clean
    result.
    """
    from pathlib import Path

    file_path = Path(path)
    return inspect_bytes(file_path.name, file_path.read_bytes())


def inspect_bytes(filename: str, content: bytes) -> dict[str, Any]:
    """inspect_file() for content already in memory (an object read from S3)."""
    result = scan_file(filename, content)

    findings: list[str] = []
    extension = result["extension"]
    if extension in SUSPICIOUS_EXTENSIONS:
        findings.append("suspicious_extension")
    if extension not in EXPECTED_EXTENSIONS:
        findings.append("unexpected_extension")
    if result["size_bytes"] == 0:
        findings.append("empty_file")
    elif result["size_bytes"] > MAX_SAFE_SIZE_BYTES:
        findings.append("file_too_large")
    if len(filename) > MAX_FILENAME_LENGTH:
        findings.append("filename_too_long")
    if has_double_extension(filename):
        findings.append("multiple_extensions")

    clamav_result = scan_with_clamav(content)
    clamav_status = clamav_result["status"]

    if clamav_status == "INFECTED":
        findings.append(f"clamav_infected:{clamav_result['signature']}")
        verdict = "INFECTED"
    elif clamav_status == "ERROR":
        findings.append("clamav_unavailable")
        verdict = "UNKNOWN"
    elif findings:
        verdict = "SUSPICIOUS"
    else:
        verdict = "SAFE"

    accepted = clamav_status == "CLEAN" and not findings

    return {
        "accepted": accepted,
        "filename": result["filename"],
        "extension": extension,
        "size_bytes": result["size_bytes"],
        "sha256": result["sha256"],
        "findings": findings,
        "verdict": verdict,
        "clamav_status": clamav_status,
    }


def scan_file_spark(spark: Any, filename: str, content: bytes) -> Any:
    """Same as scan_file(), but wraps the Layer-1 result in a Spark
    DataFrame - matches the pattern used by analyze_text() in
    transform.py. Kept to Layer 1 only (no ClamAV) since this is used
    for the Docker Spark smoke test, not the real ingestion path;
    inspect_file() is the function the real pipeline calls."""
    result = scan_file(filename, content)
    spark_result: dict[str, Any] = dict(result)
    spark_result["reasons"] = ", ".join(result["reasons"])  # flatten list for DataFrame
    df = spark.createDataFrame([spark_result])
    return df.select("filename", "extension", "size_bytes", "sha256", "verdict", "reasons")


if __name__ == "__main__":
    # Quick manual check, no Spark/Docker needed: python3 security_scanner.py
    sample = scan_file("hello.txt", b"This is a normal file used to test the Spark Security Scanner.")
    print(sample)