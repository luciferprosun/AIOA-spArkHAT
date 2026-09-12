"""Scan tracked and non-ignored repository files without printing secret values."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_FATAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "AWS_ACCESS_KEY_ID",
        re.compile(r"(?:AK" + r"IA|AS" + r"IA)[A-Z0-9]{16}"),
    ),
    (
        "PRIVATE_KEY_MATERIAL",
        re.compile(r"-{5}BEGIN [A-Z0-9 ]*" + r"PRIVATE KEY-{5}"),
    ),
    (
        "GITHUB_TOKEN",
        re.compile(r"gh" + r"[pousr]_[A-Za-z0-9]{20,}"),
    ),
    (
        "OPENAI_API_KEY",
        re.compile(r"sk" + r"-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    ),
    (
        "AWS_SECRET_ACCESS_KEY",
        re.compile(
            r"(?i)(?:aws_secret_access_key|secret_access_key)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9/+=]{40}"
        ),
    ),
    (
        "HARDCODED_AUTHORIZATION_TOKEN",
        re.compile(
            r"(?i)(?:bearer_token|approval_token|authorization_token)\s*[:=]\s*"
            r"['\"][A-Za-z0-9._~+/=-]{24,}['\"]"
        ),
    ),
)
_ACCOUNT_ID = re.compile(r"(?<![0-9a-f])[0-9]{12}(?![0-9a-f])")
_INSTANCE_ID = re.compile(r"\bi-[0-9a-f]{8}(?:[0-9a-f]{9})?\b")
_ALLOWED_SYNTHETIC_SOURCE_PATHS = frozenset(
    {
        "src/aioa_cloudops_agent/cloudops/provider.py",
        "src/aioa_cloudops_agent/local_api/application.py",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _record(path: str, category: str) -> dict[str, str]:
    return {"category": category, "path": path}


def _is_review_fixture(path: str) -> bool:
    return path.startswith(("tests/", "docs/")) or path in _ALLOWED_SYNTHETIC_SOURCE_PATHS


def scan_files(root: Path, relative_paths: tuple[str, ...]) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    reviewed_identifiers: list[dict[str, str]] = []
    binary_skipped = 0
    scanned = 0
    for relative in sorted(set(relative_paths)):
        path = root / relative
        if path.is_symlink():
            findings.append(_record(relative, "SYMLINKED_REPOSITORY_FILE"))
            continue
        name = path.name.casefold()
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            findings.append(_record(relative, "ENVIRONMENT_SECRET_FILE"))
        if path.suffix.casefold() in {".key", ".p12", ".pfx", ".pem"}:
            findings.append(_record(relative, "PRIVATE_KEY_FILE"))
        if not path.is_file():
            findings.append(_record(relative, "REPOSITORY_FILE_UNAVAILABLE"))
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            findings.append(_record(relative, "REPOSITORY_FILE_UNREADABLE"))
            continue
        if len(raw) > 5_000_000:
            findings.append(_record(relative, "UNSCANNED_OVERSIZED_FILE"))
            continue
        if b"\0" in raw:
            binary_skipped += 1
            continue
        scanned += 1
        text = raw.decode("utf-8", errors="replace")
        for category, pattern in _FATAL_PATTERNS:
            if pattern.search(text) is not None:
                findings.append(_record(relative, category))
        for category, pattern in (
            ("RAW_AWS_ACCOUNT_ID", _ACCOUNT_ID),
            ("RAW_EC2_INSTANCE_ID", _INSTANCE_ID),
        ):
            if pattern.search(text) is None:
                continue
            target = reviewed_identifiers if _is_review_fixture(relative) else findings
            target.append(_record(relative, category))
    findings = sorted(findings, key=lambda item: (item["path"], item["category"]))
    reviewed_identifiers = sorted(
        reviewed_identifiers,
        key=lambda item: (item["path"], item["category"]),
    )
    material: dict[str, object] = {
        "aws_mutations": 0,
        "binary_files_skipped": binary_skipped,
        "files_scanned": scanned,
        "findings": findings,
        "findings_count": len(findings),
        "live_receipts": 0,
        "network_connections": 0,
        "reviewed_synthetic_identifiers": reviewed_identifiers,
        "reviewed_synthetic_identifiers_count": len(reviewed_identifiers),
        "schema_version": 1,
        "secret_values_emitted": False,
        "status": "PASS" if not findings else "FAIL",
    }
    return {
        **material,
        "receipt_sha256": hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest(),
    }


def repository_paths(root: Path = ROOT) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"),
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("SECRET_SCAN_FILE_ENUMERATION_FAILED") from error
    if result.returncode != 0:
        raise RuntimeError("SECRET_SCAN_FILE_ENUMERATION_FAILED")
    return tuple(name for name in result.stdout.split("\0") if name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        payload = scan_files(ROOT, repository_paths())
        code = 0 if payload["status"] == "PASS" else 1
    except RuntimeError as error:
        payload = {
            "aws_mutations": 0,
            "findings": [{"category": str(error), "path": "."}],
            "findings_count": 1,
            "live_receipts": 0,
            "network_connections": 0,
            "schema_version": 1,
            "secret_values_emitted": False,
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
