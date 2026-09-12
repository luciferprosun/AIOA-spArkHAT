"""Build or check the Phase 3 post-deployment verifier schemas and fixture."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from aioa_cloudops_agent.release.deployment_contract import pretty_json
from aioa_cloudops_agent.release.post_deploy_verifier import (
    PostDeployVerifierError,
    VerifierFixture,
    render_verifier_fixture_schema,
    render_verifier_markdown,
    render_verifier_receipt_schema,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "phase3" / "post-deploy-verifier-pass.json"
DEFAULT_RECEIPT_SCHEMA = ROOT / "requirements" / "phase3-verifier-receipt.schema.json"
DEFAULT_FIXTURE_SCHEMA = ROOT / "requirements" / "phase3-verifier-fixture.schema.json"
DEFAULT_DOCUMENT = ROOT / "docs" / "operations" / "phase3-post-deploy-verification.md"


def canonical_fixture() -> VerifierFixture:
    return VerifierFixture(
        schema_version=1,
        fixture_id="PHASE3_POST_DEPLOY_VERIFIER_OFFLINE_V1",
        synthetic=True,
        generated_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        authorized_identity=True,
        expected_account_match=True,
        expected_region_match=True,
        api_contract_match=True,
        model_access_contract_match=True,
        resource_binding_contract_match=True,
        verification_evidence_contract_match=True,
        network_connections=0,
        aws_mutations=0,
        live_receipt=False,
    )


def _atomic_write(path: Path, content: str) -> None:
    if path.is_symlink():
        raise PostDeployVerifierError("VERIFIER_OUTPUT_SYMLINK_FORBIDDEN")
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


def _display_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name


def build(*, check: bool = False) -> dict[str, object]:
    fixture = canonical_fixture()
    outputs = {
        DEFAULT_FIXTURE: pretty_json(fixture.model_dump(mode="json")),
        DEFAULT_RECEIPT_SCHEMA: render_verifier_receipt_schema(),
        DEFAULT_FIXTURE_SCHEMA: render_verifier_fixture_schema(),
        DEFAULT_DOCUMENT: render_verifier_markdown(),
    }
    if check:
        if any(
            not path.is_file() or path.read_text(encoding="utf-8") != content
            for path, content in outputs.items()
        ):
            raise PostDeployVerifierError("VERIFIER_GENERATED_ARTIFACT_DRIFT")
    else:
        for path, content in outputs.items():
            _atomic_write(path, content)
    return {
        "aws_mutations": 0,
        "generated_artifacts": [_display_path(path) for path in sorted(outputs)],
        "live_receipts": 0,
        "network_connections": 0,
        "schema_version": 1,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        payload = build(check=args.check)
        code = 0
    except PostDeployVerifierError as error:
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reason": error.reason,
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
