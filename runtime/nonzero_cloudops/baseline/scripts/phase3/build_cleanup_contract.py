"""Build or check the canonical Phase 3 rollback and cleanup artifacts."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from aioa_cloudops_agent.release.cleanup import (
    CleanupAttemptState,
    CleanupError,
    CleanupObservationFixture,
    DeploymentCleanupBinding,
    ObservedCleanupResource,
    build_cleanup_contract,
    load_expected_resource_manifest,
    manifest_sha256,
    render_cleanup_contract_markdown,
    render_cleanup_contract_schema,
    render_cleanup_plan_schema,
)
from aioa_cloudops_agent.release.deployment_contract import (
    load_deployment_contract,
    pretty_json,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEPLOYMENT_CONTRACT = ROOT / "requirements" / "phase3-deployment-contract.json"
DEFAULT_RESOURCE_MANIFEST = (
    ROOT / "docs" / "evidence" / "release" / "phase3-expected-resources.json"
)
DEFAULT_CLEANUP_CONTRACT = ROOT / "requirements" / "phase3-cleanup-contract.json"
DEFAULT_CONTRACT_SCHEMA = ROOT / "requirements" / "phase3-cleanup-contract.schema.json"
DEFAULT_PLAN_SCHEMA = ROOT / "requirements" / "phase3-cleanup-plan.schema.json"
DEFAULT_DOCUMENT = ROOT / "docs" / "operations" / "phase3-rollback-cleanup.md"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "phase3" / "cleanup-owned-partial.json"


def _atomic_write(path: Path, content: str) -> None:
    if path.is_symlink():
        raise CleanupError("CLEANUP_OUTPUT_SYMLINK_FORBIDDEN")
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


def _fixture(contract_hash: str, resource_manifest_hash: str) -> CleanupObservationFixture:
    binding = DeploymentCleanupBinding(
        deployment_id="p3-1234abcd-1234-abcd",
        repo_sha="a" * 40,
        deployment_contract_sha256=contract_hash,
        expected_resource_manifest_sha256=resource_manifest_hash,
        stack_id_sha256="b" * 64,
    )
    tags = {
        "AIOAProject": "NonZeroCloudOps",
        "AIOAStage": "hackathon",
        "ManagedBy": "CloudFormation",
    }
    return CleanupObservationFixture(
        schema_version=1,
        fixture_id="PHASE3_SYNTHETIC_CLEANUP_OBSERVATIONS",
        synthetic=True,
        binding=binding,
        resources=tuple(
            ObservedCleanupResource(
                logical_id=logical_id,
                resource_type=resource_type,
                deployment_id=binding.deployment_id,
                deployment_contract_sha256=binding.deployment_contract_sha256,
                stack_id_sha256=binding.stack_id_sha256,
                stack_membership_confirmed=True,
                ownership_tags=tags,
                cleanup_attempt_state=attempt,
            )
            for logical_id, resource_type, attempt in (
                (
                    "OrchestratorFunction",
                    "AWS::Serverless::Function",
                    CleanupAttemptState.PREVIOUSLY_FAILED,
                ),
                (
                    "OrchestratorRole",
                    "AWS::IAM::Role",
                    CleanupAttemptState.PREVIOUSLY_FAILED,
                ),
                (
                    "StateTable",
                    "AWS::DynamoDB::Table",
                    CleanupAttemptState.NEVER_ATTEMPTED,
                ),
            )
        ),
        network_connections=0,
        aws_mutations=0,
        live_receipts=0,
    )


def _display_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name


def build(*, check: bool = False) -> dict[str, object]:
    deployment_contract = load_deployment_contract(DEFAULT_DEPLOYMENT_CONTRACT)
    manifest = load_expected_resource_manifest(DEFAULT_RESOURCE_MANIFEST)
    contract = build_cleanup_contract(deployment_contract, manifest)
    fixture = _fixture(contract.deployment_contract_sha256, manifest_sha256(manifest))
    outputs = {
        DEFAULT_CLEANUP_CONTRACT: pretty_json(contract.model_dump(mode="json")),
        DEFAULT_CONTRACT_SCHEMA: render_cleanup_contract_schema(),
        DEFAULT_PLAN_SCHEMA: render_cleanup_plan_schema(),
        DEFAULT_DOCUMENT: render_cleanup_contract_markdown(contract),
        DEFAULT_FIXTURE: pretty_json(fixture.model_dump(mode="json")),
    }
    if check:
        drift = [
            _display_path(path)
            for path, content in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        if drift:
            raise CleanupError("CLEANUP_GENERATED_ARTIFACT_DRIFT")
    else:
        for path, content in outputs.items():
            _atomic_write(path, content)
    return {
        "aws_mutations": 0,
        "generated_artifacts": [_display_path(path) for path in sorted(outputs)],
        "live_receipts": 0,
        "network_connections": 0,
        "resource_rules": len(contract.rules),
        "schema_version": contract.schema_version,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        payload = build(check=args.check)
        code = 0
    except CleanupError as error:
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
