"""Packaged command for the canonical AWS-free portable judge sandbox."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path

from aioa_cloudops_agent.config import RuntimeSettings
from aioa_cloudops_agent.domain import ContractValidationError
from aioa_cloudops_agent.release.post_deploy_verifier import PostDeployVerifierError

from .demo import (
    PortableDemoError,
    render_portable_receipt,
    run_portable_demo,
    write_portable_receipt,
)

DEFAULT_OUTPUT = Path(".local/portable/portable-demo-receipt.json")


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Preserve sandbox durable state in a new or empty directory.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _failure(reason: str) -> str:
    return (
        json.dumps(
            {
                "aws_mutations": 0,
                "external_network_connections": 0,
                "reason": reason,
                "status": "FAIL",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one portable proof and print only its validated public receipt."""

    args = _arguments(argv)
    try:
        settings = RuntimeSettings.from_environment()
        if args.workspace is None:
            with tempfile.TemporaryDirectory(prefix="aioa-portable-demo-") as temporary:
                receipt = run_portable_demo(
                    settings=settings,
                    workspace=Path(temporary),
                )
        else:
            receipt = run_portable_demo(settings=settings, workspace=args.workspace)
        write_portable_receipt(args.output, receipt)
        rendered = render_portable_receipt(receipt)
        code = 0
    except ContractValidationError:
        rendered = _failure("PORTABLE_RUNTIME_CONFIGURATION_INVALID")
        code = 1
    except (PortableDemoError, PostDeployVerifierError) as error:
        rendered = _failure(error.reason)
        code = 1
    print(rendered, end="")
    return code


__all__ = ["DEFAULT_OUTPUT", "main"]
