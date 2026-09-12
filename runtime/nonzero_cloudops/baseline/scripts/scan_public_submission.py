#!/usr/bin/env python3
"""Scan a staged public submission tree without emitting matched values."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Final

_MAX_FILE_BYTES: Final = 10_000_000
_BINARY_ALLOWLIST: Final = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})
_FORBIDDEN_SUFFIXES: Final = frozenset(
    {".credential", ".credentials", ".key", ".p12", ".pem", ".pfx"}
)
_FORBIDDEN_NAMES: Final = frozenset(
    {
        ".env",
        "cookies",
        "history",
        "login data",
        "web data",
    }
)
_FATAL_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
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
_PRIVATE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "ABSOLUTE_USER_PATH",
        re.compile(
            r"(?:/" + r"home/|/Users/|[A-Za-z]:\\Users\\)"
            r"[A-Za-z0-9._-]+(?:[/\\][^\s'\"`<>)]*)?"
        ),
    ),
    (
        "AWS_ACCOUNT_IDENTIFIER",
        re.compile(r"(?<![0-9a-f])[0-9]{12}(?![0-9a-f])"),
    ),
    (
        "EMAIL_ADDRESS",
        re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ),
    (
        "E164_PHONE_NUMBER",
        re.compile(r"(?<![A-Za-z0-9])\+[1-9][0-9]{7,14}(?![A-Za-z0-9])"),
    ),
    (
        "URL_EMBEDDED_CREDENTIAL",
        re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE),
    ),
)


class PublicScanError(RuntimeError):
    """The candidate could not be scanned safely."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _record(path: str, category: str) -> dict[str, str]:
    return {"category": category, "path": path}


def _is_reviewed_synthetic(path: str, category: str, match: str) -> bool:
    if not path.startswith("tests/"):
        return False
    if category == "EMAIL_ADDRESS" and match.casefold().endswith((".invalid", ".example")):
        return True
    return category in {
        "ABSOLUTE_USER_PATH",
        "AWS_ACCOUNT_IDENTIFIER",
        "URL_EMBEDDED_CREDENTIAL",
    }


def scan_tree(root: Path) -> dict[str, object]:
    """Return a deterministic, value-free privacy and secret scan receipt."""

    resolved = root.resolve(strict=False)
    if not resolved.is_dir():
        raise PublicScanError("PUBLIC_CANDIDATE_UNAVAILABLE")

    findings: list[dict[str, str]] = []
    reviewed: list[dict[str, str]] = []
    binary_files = 0
    bytes_scanned = 0
    files_scanned = 0
    regular_files = 0

    for path in sorted(resolved.rglob("*")):
        relative = path.relative_to(resolved).as_posix()
        if path.is_symlink():
            findings.append(_record(relative, "SYMLINK_FORBIDDEN"))
            continue
        if not path.is_file():
            continue
        regular_files += 1
        lowered_name = path.name.casefold()
        if lowered_name in _FORBIDDEN_NAMES or (
            lowered_name.startswith(".env.") and lowered_name != ".env.example"
        ):
            findings.append(_record(relative, "PRIVATE_OR_SESSION_FILE"))
        if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
            findings.append(_record(relative, "CREDENTIAL_FILE"))
        if path.suffix.casefold() == ".pdf":
            findings.append(_record(relative, "PERSONAL_PDF_RISK"))
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise PublicScanError("PUBLIC_CANDIDATE_FILE_UNREADABLE") from error
        if len(raw) > _MAX_FILE_BYTES:
            findings.append(_record(relative, "UNSCANNED_OVERSIZED_FILE"))
            continue
        if b"\0" in raw:
            binary_files += 1
            if path.suffix.casefold() not in _BINARY_ALLOWLIST:
                findings.append(_record(relative, "UNREVIEWED_BINARY_FILE"))
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(_record(relative, "NON_UTF8_TEXT_FILE"))
            continue
        files_scanned += 1
        bytes_scanned += len(raw)
        for category, pattern in _FATAL_PATTERNS:
            if pattern.search(text) is not None:
                findings.append(_record(relative, category))
        for category, pattern in _PRIVATE_PATTERNS:
            for match in pattern.finditer(text):
                target = reviewed if _is_reviewed_synthetic(relative, category, match.group(0)) else findings
                target.append(_record(relative, category))

    findings = sorted(
        {json.dumps(item, sort_keys=True): item for item in findings}.values(),
        key=lambda item: (item["path"], item["category"]),
    )
    reviewed = sorted(
        {json.dumps(item, sort_keys=True): item for item in reviewed}.values(),
        key=lambda item: (item["path"], item["category"]),
    )
    material: dict[str, object] = {
        "aws_account_values_emitted": False,
        "aws_mutations": 0,
        "binary_files_reviewed": binary_files,
        "bytes_scanned": bytes_scanned,
        "emails_emitted": False,
        "external_deployments": 0,
        "files_scanned": files_scanned,
        "findings": findings,
        "findings_count": len(findings),
        "personal_values_emitted": False,
        "publication_actions": 0,
        "regular_files": regular_files,
        "remote_pushes": 0,
        "reviewed_synthetic_fixtures": reviewed,
        "reviewed_synthetic_fixtures_count": len(reviewed),
        "schema_version": 1,
        "secret_values_emitted": False,
        "status": "PASS" if not findings else "FAIL",
    }
    return {
        **material,
        "receipt_sha256": hashlib.sha256(_canonical_bytes(material)).hexdigest(),
    }


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    if path.is_symlink():
        raise PublicScanError("PUBLIC_SCAN_OUTPUT_SYMLINK_FORBIDDEN")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                (
                    json.dumps(receipt, allow_nan=False, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
            )
    except OSError as error:
        raise PublicScanError("PUBLIC_SCAN_OUTPUT_UNAVAILABLE") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = scan_tree(args.root)
        if args.output is not None:
            _write_receipt(args.output, receipt)
        code = 0 if receipt["status"] == "PASS" else 1
    except PublicScanError as error:
        receipt = {
            "aws_mutations": 0,
            "external_deployments": 0,
            "findings": [{"category": error.reason, "path": "."}],
            "findings_count": 1,
            "publication_actions": 0,
            "remote_pushes": 0,
            "schema_version": 1,
            "secret_values_emitted": False,
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(receipt, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
