"""Rule-based file intake checks for the ETL pipeline.

This module performs lightweight extension, size, filename, and hash checks
before a file enters transformation. It is not a malware scanner; ClamAV or an
equivalent antivirus engine remains a separate production integration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Extensions we treat as risky to auto-run/auto-open.
SUSPICIOUS_EXTENSIONS = {
    "exe",
    "bat",
    "cmd",
    "com",
    "scr",
    "msi",
    "vbs",
    "js",
    "jar",
    "ps1",
    "sh",
}

# Extensions we expect to see routinely from the web crawler.
EXPECTED_EXTENSIONS = {
    "html",
    "htm",
    "pdf",
    "txt",
    "json",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "docx",
    "csv",
}

MAX_SAFE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILENAME_LENGTH = 100


def get_extension(filename: str) -> str:
    name = filename.lstrip(".")
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def get_file_size(content: bytes) -> int:
    return len(content)


def get_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_double_extension(filename: str) -> bool:
    parts = filename.lstrip(".").split(".")
    return len(parts) > 2


def scan_file(filename: str, content: bytes) -> dict:
    suspicious_reasons = []
    unknown_reasons = []

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


def inspect_file(path: str | Path) -> dict:
    file_path = Path(path)
    scan = scan_file(file_path.name, file_path.read_bytes())
    findings = []

    if len(file_path.name) > MAX_FILENAME_LENGTH:
        findings.append("filename_too_long")
    if has_double_extension(file_path.name):
        findings.append("multiple_extensions")
    if scan["extension"] in SUSPICIOUS_EXTENSIONS:
        findings.append("suspicious_extension")
    if scan["extension"] not in EXPECTED_EXTENSIONS:
        findings.append("unexpected_extension")
    if scan["size_bytes"] == 0:
        findings.append("file_empty")
    elif scan["size_bytes"] > MAX_SAFE_SIZE_BYTES:
        findings.append("file_too_large")

    return {
        "filename": file_path.name,
        "extension": scan["extension"],
        "size_bytes": scan["size_bytes"],
        "sha256": scan["sha256"],
        "accepted": not findings,
        "findings": findings,
        "verdict": scan["verdict"],
        "reasons": scan["reasons"],
    }


def scan_file_spark(spark, filename: str, content: bytes):
    """Wrap scan_file() in a Spark DataFrame."""
    result = scan_file(filename, content)
    result["reasons"] = ", ".join(result["reasons"])
    df = spark.createDataFrame([result])
    return df.select("filename", "extension", "size_bytes", "sha256", "verdict", "reasons")


if __name__ == "__main__":
    sample = scan_file("hello.txt", b"This is a normal file used to test the Spark Security Scanner.")
    print(sample)
