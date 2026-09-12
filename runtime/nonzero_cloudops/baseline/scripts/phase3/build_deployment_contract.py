#!/usr/bin/env python3
"""Validate the canonical Phase 3 contract and build its deterministic projections."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aioa_cloudops_agent.release import (  # noqa: E402
    contract_sha256,
    load_deployment_contract,
    operator_input_blockers,
    render_contract_markdown,
    render_contract_schema,
)
from aioa_cloudops_agent.release.deployment_contract import (  # noqa: E402
    DeploymentContractError,
    validate_contract_has_no_secret_material,
)

DEFAULT_CONTRACT: Final = ROOT / "requirements" / "phase3-deployment-contract.json"
DEFAULT_SCHEMA: Final = ROOT / "requirements" / "phase3-deployment-contract.schema.json"
DEFAULT_DOCUMENT: Final = ROOT / "docs" / "architecture" / "phase3-deployment-contract.md"


def _replace(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def build(
    *,
    contract_path: Path = DEFAULT_CONTRACT,
    schema_path: Path = DEFAULT_SCHEMA,
    document_path: Path = DEFAULT_DOCUMENT,
    check: bool = False,
) -> dict[str, object]:
    contract = load_deployment_contract(contract_path)
    validate_contract_has_no_secret_material(contract)
    outputs = {
        schema_path: render_contract_schema(),
        document_path: render_contract_markdown(contract),
    }
    if check:
        drift = sorted(
            path.relative_to(ROOT).as_posix()
            for path, expected in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        )
        if drift:
            raise DeploymentContractError("DEPLOYMENT_CONTRACT_PROJECTION_DRIFT")
    else:
        for path, content in outputs.items():
            _replace(path, content)
    blockers = operator_input_blockers(contract)
    return {
        "contract_sha256": contract_sha256(contract),
        "external_blocker_count": len(blockers),
        "projections": [
            path.relative_to(ROOT).as_posix() for path in sorted(outputs)
        ],
        "schema_version": 1,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = build(
            contract_path=args.contract,
            schema_path=args.schema,
            document_path=args.document,
            check=args.check,
        )
    except DeploymentContractError as error:
        payload = {
            "reasons": [error.reason],
            "schema_version": 1,
            "status": "FAIL",
        }
    if args.json:
        print(json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True))
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"PHASE3_CONTRACT {payload['status']} reasons={reasons}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
