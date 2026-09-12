"""Build or check the deterministic Phase 3 offline IaC resource manifest."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from aioa_cloudops_agent.release.deployment_contract import (
    load_deployment_contract,
    pretty_json,
)
from aioa_cloudops_agent.release.iac import (
    IacValidationError,
    build_expected_resource_manifest,
    load_iac_template,
    render_iac_manifest_markdown,
    render_iac_manifest_schema,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "requirements" / "phase3-deployment-contract.json"
DEFAULT_TEMPLATE = ROOT / "infra" / "sam" / "template.yaml"
DEFAULT_MANIFEST = ROOT / "docs" / "evidence" / "release" / "phase3-expected-resources.json"
DEFAULT_DOCUMENT = ROOT / "docs" / "evidence" / "release" / "phase3-expected-resources.md"
DEFAULT_SCHEMA = ROOT / "requirements" / "phase3-iac-manifest.schema.json"


def _display_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name


def _atomic_write(path: Path, content: str) -> None:
    if path.is_symlink():
        raise IacValidationError("IAC_OUTPUT_SYMLINK_FORBIDDEN")
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


def build(*, check: bool = False) -> dict[str, object]:
    contract = load_deployment_contract(DEFAULT_CONTRACT)
    template_bytes = DEFAULT_TEMPLATE.read_bytes()
    template = load_iac_template(DEFAULT_TEMPLATE)
    manifest = build_expected_resource_manifest(
        template,
        contract,
        template_bytes=template_bytes,
    )
    expected = {
        DEFAULT_MANIFEST: pretty_json(manifest.model_dump(mode="json")),
        DEFAULT_DOCUMENT: render_iac_manifest_markdown(manifest),
        DEFAULT_SCHEMA: render_iac_manifest_schema(),
    }
    if check:
        drift = [
            _display_path(path)
            for path, content in expected.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        if drift:
            raise IacValidationError("IAC_GENERATED_ARTIFACT_DRIFT")
    else:
        for path, content in expected.items():
            _atomic_write(path, content)
    return {
        "aws_mutations": 0,
        "deployment_contract_sha256": manifest.deployment_contract_sha256,
        "generated_artifacts": [
            _display_path(path) for path in sorted(expected)
        ],
        "live_receipts": 0,
        "network_connections": 0,
        "resource_count": manifest.resource_count,
        "schema_version": manifest.schema_version,
        "status": "PASS",
        "template_sha256": manifest.template_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        payload = build(check=args.check)
        exit_code = 0
    except IacValidationError as error:
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reason": error.reason,
            "status": "FAIL",
        }
        exit_code = 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
