"""Run the complete offline post-deploy chain; live mode remains disabled."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from aioa_cloudops_agent.persistence.local_integrity import (
    LocalIntegrityError,
    atomic_write_private_json,
    read_private_json,
    validate_local_path,
)
from aioa_cloudops_agent.release.deployment_contract import load_deployment_contract
from aioa_cloudops_agent.release.post_deploy_verifier import (
    PostDeployVerificationReceipt,
    PostDeployVerifierError,
    VerifierMode,
    load_verifier_fixture,
    run_post_deploy_verifier,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "requirements" / "phase3-deployment-contract.json"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "phase3" / "post-deploy-verifier-pass.json"
DEFAULT_RECEIPT = (
    ROOT / "docs" / "evidence" / "release" / "phase3-offline-verifier-receipt.json"
)


def _atomic_write(path: Path, content: str) -> None:
    if (
        not isinstance(path, Path)
        or not str(path).strip()
        or ".." in path.parts
        or len(str(path).encode()) > 4_096
    ):
        raise PostDeployVerifierError("VERIFIER_OUTPUT_PATH_INVALID")
    if path.is_symlink() or any(
        parent.is_symlink() for parent in path.parents if parent.exists()
    ):
        raise PostDeployVerifierError("VERIFIER_OUTPUT_SYMLINK_FORBIDDEN")
    if path.exists():
        try:
            PostDeployVerificationReceipt.model_validate(read_private_json(path))
        except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
            raise PostDeployVerifierError("VERIFIER_OUTPUT_EXISTING_FILE_UNSAFE") from error
    try:
        value = json.loads(content)
        validate_local_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_local_path(path)
        atomic_write_private_json(path, value)
    except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
        raise PostDeployVerifierError("VERIFIER_OUTPUT_UNAVAILABLE") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mode = (
        VerifierMode.LIVE_AWS
        if args.mode == "live"
        else VerifierMode.OFFLINE_LOCAL_FIXTURE
    )
    try:
        contract = load_deployment_contract(args.contract)
        fixture = load_verifier_fixture(args.fixture) if mode is not VerifierMode.LIVE_AWS else None
        if args.workspace is None:
            with tempfile.TemporaryDirectory(prefix="phase3-verifier-") as temporary:
                receipt = run_post_deploy_verifier(
                    mode=mode,
                    fixture=fixture,
                    deployment_contract=contract,
                    workspace=Path(temporary),
                )
        else:
            receipt = run_post_deploy_verifier(
                mode=mode,
                fixture=fixture,
                deployment_contract=contract,
                workspace=args.workspace,
            )
        payload: dict[str, object] = receipt.model_dump(mode="json")
        rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
        if args.check:
            if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
                raise PostDeployVerifierError("VERIFIER_RECEIPT_DRIFT")
        else:
            _atomic_write(args.output, rendered)
        code = 0
    except PostDeployVerifierError as error:
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reason": error.reason,
            "status": "BLOCKED_EXTERNAL" if error.reason.startswith("LIVE_") else "FAIL",
        }
        code = 3 if error.reason.startswith("LIVE_") else 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
