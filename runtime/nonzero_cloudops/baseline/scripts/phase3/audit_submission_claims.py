"""Audit every Devpost sentence against local evidence and reject unsupported live claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DRAFT = ROOT / "docs" / "submission" / "devpost-draft.md"
DEFAULT_RECEIPT = (
    ROOT / "docs" / "evidence" / "release" / "phase3-devpost-claim-audit.json"
)

_SECTION_EVIDENCE: dict[str, tuple[str, ...]] = {
    "": ("requirements/phase3-deployment-contract.json",),
    "One-line pitch": (
        "scripts/run_p0_gate.py",
        "docs/evidence/release/phase3-offline-verifier-receipt.json",
    ),
    "The problem": ("docs/architecture/phase3-deployment-ready-local-rc.md",),
    "What we built": (
        "docs/architecture/phase3-deployment-ready-local-rc.md",
        "infra/sam/template.yaml",
        "tests/unit/test_phase3_post_deploy_verifier.py",
    ),
    "How humans stay in control": (
        "scripts/run_p0_gate.py",
        "scripts/run_p1_gate.py",
    ),
    "Demo": (
        "scripts/phase3/run_jury_demo.py",
        "docs/evidence/release/phase3-offline-verifier-receipt.json",
    ),
    "Technology": (
        "requirements/phase3-deployment-contract.json",
        "docs/evidence/release/phase3-expected-resources.json",
    ),
    "What is distinctive": ("docs/architecture/phase3-deployment-ready-local-rc.md",),
    "Accomplishments proven locally": (
        "requirements/phase3-deployment-contract.json",
        "scripts/phase3/run_local_gate.py",
    ),
    "Challenges and lessons": (
        "docs/architecture/local-first-phase-2.md",
        "tests/integration/test_local_hitl_execution.py",
    ),
    "Evidence map": ("docs/evidence/reviewer-evidence-manifest.json",),
    "Current limitations and next steps": (
        "requirements/phase3-deployment-contract.json",
        "src/aioa_cloudops_agent/release/preflight.py",
    ),
    "Placeholders that require future live evidence": (
        "requirements/phase3-deployment-contract.json",
    ),
    "Repository proof commands": ("scripts/phase3/run_local_gate.py",),
}
_GUARDED_LIVE_LANGUAGE = re.compile(
    r"(?i)\b(?:not|no|never|without|blocked|future|placeholder|required|requires|"
    r"do not|does not|remains|cannot|until)\b"
)
_LIVE_SUBJECT = re.compile(
    r"(?i)\b(?:live|production|deployed|deployment|bedrock|aws mutation|"
    r"effective iam|real aws|external submission)\b"
)
_UNSUPPORTED_POSITIVE = re.compile(
    r"(?i)(?:\bwe\s+(?:deployed|invoked|remediated|submitted)\b|"
    r"\b(?:system|agent|project|service|stack|infrastructure)\s+"
    r"(?:is|was|has been|have been)\s+(?:successfully\s+)?"
    r"(?:deployed|live[- ]verified|production[- ]ready)\b|"
    r"\b(?:live bedrock invocation|real aws mutation|effective live iam)\b)"
)
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")


class SubmissionAuditError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _blocks(markdown: str) -> tuple[tuple[str, str], ...]:
    blocks: list[tuple[str, str]] = []
    paragraph: list[str] = []
    section = ""
    fenced = False

    def flush() -> None:
        if paragraph:
            blocks.append((section, " ".join(paragraph)))
            paragraph.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("## "):
            flush()
            section = line[3:].strip()
            continue
        if line.startswith("# ") or not line:
            flush()
            continue
        if line.startswith("|"):
            flush()
            if not _TABLE_SEPARATOR.match(line):
                blocks.append((section, line))
            continue
        if re.match(r"^(?:[-*]|[0-9]+\.)\s+", line):
            flush()
            blocks.append((section, re.sub(r"^(?:[-*]|[0-9]+\.)\s+", "", line)))
            continue
        paragraph.append(line)
    flush()
    return tuple(blocks)


def _sentences(markdown: str) -> tuple[tuple[str, str], ...]:
    sentences: list[tuple[str, str]] = []
    for section, block in _blocks(markdown):
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`\[])" , block)
        sentences.extend((section, part.strip()) for part in parts if part.strip())
    return tuple(sentences)


def audit_draft(path: Path = DEFAULT_DRAFT) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SubmissionAuditError("DEVPOST_DRAFT_UNAVAILABLE") from error
    if not raw.startswith("# Devpost Draft — AIOA Non-Zero CloudOps Agent\n"):
        raise SubmissionAuditError("DEVPOST_ARCHITECTURE_NAME_DRIFT")
    if "not externally submitted" not in raw:
        raise SubmissionAuditError("DEVPOST_SUBMISSION_STATUS_AMBIGUOUS")
    sentences = _sentences(raw)
    if not sentences:
        raise SubmissionAuditError("DEVPOST_SENTENCE_AUDIT_EMPTY")
    receipts: list[dict[str, object]] = []
    unsupported: list[dict[str, object]] = []
    for index, (section, sentence) in enumerate(sentences, start=1):
        evidence = _SECTION_EVIDENCE.get(section)
        if evidence is None:
            unsupported.append({"reason": "UNMAPPED_SECTION", "sentence_index": index})
            evidence = ()
        live_language = _LIVE_SUBJECT.search(sentence) is not None
        unsupported_positive = _UNSUPPORTED_POSITIVE.search(sentence) is not None
        if unsupported_positive and _GUARDED_LIVE_LANGUAGE.search(sentence) is None:
            unsupported.append(
                {"reason": "UNSUPPORTED_LIVE_CLAIM", "sentence_index": index}
            )
        receipts.append(
            {
                "classification": (
                    "EXPLICIT_LIVE_LIMIT_OR_PLACEHOLDER"
                    if live_language
                    else "LOCAL_EVIDENCE_CLAIM"
                ),
                "evidence": list(evidence),
                "section": section,
                "sentence_index": index,
                "sentence_sha256": hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
            }
        )
    evidence_rows = sum(
        section == "Evidence map" and block.startswith("|")
        for section, block in _blocks(raw)
    ) - 1
    placeholders = len(re.findall(r"\[[A-Z0-9_]+_REQUIRED:", raw))
    if evidence_rows != 8:
        unsupported.append({"reason": "EVIDENCE_MAP_COVERAGE_DRIFT", "sentence_index": 0})
    if placeholders != 6:
        unsupported.append({"reason": "LIVE_PLACEHOLDER_COVERAGE_DRIFT", "sentence_index": 0})
    material: dict[str, object] = {
        "aws_mutations": 0,
        "draft_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "evidence_map_rows": evidence_rows,
        "live_placeholders": placeholders,
        "live_receipts": 0,
        "network_connections": 0,
        "schema_version": 1,
        "sentence_receipts": receipts,
        "sentences_audited": len(receipts),
        "status": "PASS" if not unsupported else "FAIL",
        "unsupported_claims": unsupported,
    }
    return {
        **material,
        "receipt_sha256": hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest(),
    }


def _atomic_write(path: Path, content: str) -> None:
    if path.is_symlink():
        raise SubmissionAuditError("DEVPOST_AUDIT_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        payload = audit_draft(args.draft)
        rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
        if args.check:
            if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
                raise SubmissionAuditError("DEVPOST_AUDIT_RECEIPT_DRIFT")
        else:
            _atomic_write(args.output, rendered)
        code = 0 if payload["status"] == "PASS" else 1
    except (OSError, SubmissionAuditError, UnicodeDecodeError) as error:
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reason": getattr(error, "reason", "DEVPOST_AUDIT_UNAVAILABLE"),
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
