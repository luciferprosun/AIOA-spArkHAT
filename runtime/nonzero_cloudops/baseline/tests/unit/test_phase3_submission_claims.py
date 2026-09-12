from __future__ import annotations

import json
from pathlib import Path

from scripts.phase3.audit_submission_claims import audit_draft

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_devpost_is_sentence_audited_and_has_no_unsupported_live_claim() -> None:
    receipt = audit_draft()

    assert receipt["status"] == "PASS"
    assert receipt["unsupported_claims"] == []
    assert receipt["sentences_audited"] >= 50
    assert receipt["evidence_map_rows"] == 8
    assert receipt["live_placeholders"] == 6
    assert receipt["network_connections"] == receipt["aws_mutations"] == 0
    assert receipt["live_receipts"] == 0


def test_audit_rejects_unmapped_or_positive_live_claim_without_leaking_sentence(
    tmp_path: Path,
) -> None:
    canonical = (ROOT / "docs/submission/devpost-draft.md").read_text(encoding="utf-8")
    tampered = canonical.replace(
        "No AWS infrastructure or live mutation has been performed by this project.",
        "We deployed the service and performed a real AWS mutation.",
    )
    path = tmp_path / "draft.md"
    path.write_text(tampered, encoding="utf-8")

    receipt = audit_draft(path)
    encoded = json.dumps(receipt)

    assert receipt["status"] == "FAIL"
    assert any(
        item["reason"] == "UNSUPPORTED_LIVE_CLAIM"  # type: ignore[index]
        for item in receipt["unsupported_claims"]  # type: ignore[union-attr]
    )
    assert "performed a real AWS mutation" not in encoded


def test_readme_and_release_docs_use_consistent_phase3_status_and_name() -> None:
    paths = (
        ROOT / "README.md",
        ROOT / "docs/architecture/phase3-deployment-ready-local-rc.md",
        ROOT / "docs/submission/demo-runbook.md",
        ROOT / "docs/submission/devpost-draft.md",
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "DEPLOYMENT_READY_LOCAL_RC" in content
        assert "AIOA Non-Zero CloudOps" in content
        assert "/home/" not in content
        assert "/media/" not in content
