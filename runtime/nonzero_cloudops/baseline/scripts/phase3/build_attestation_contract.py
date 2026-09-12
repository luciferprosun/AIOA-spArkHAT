"""Build or check the Phase 3 RC attestation schemas and documentation."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from aioa_cloudops_agent.release.attestation import (
    AttestationError,
    render_attestation_markdown,
    render_attestation_schema,
    render_local_gate_evidence_schema,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ATTESTATION_SCHEMA = ROOT / "requirements" / "phase3-rc-attestation.schema.json"
DEFAULT_GATE_EVIDENCE_SCHEMA = (
    ROOT / "requirements" / "phase3-local-gate-evidence.schema.json"
)
DEFAULT_DOCUMENT = ROOT / "docs" / "operations" / "phase3-rc-attestation.md"


def _atomic_write(path: Path, content: str) -> None:
    if path.is_symlink():
        raise AttestationError("RC_OUTPUT_SYMLINK_FORBIDDEN")
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
    outputs = {
        DEFAULT_ATTESTATION_SCHEMA: render_attestation_schema(),
        DEFAULT_GATE_EVIDENCE_SCHEMA: render_local_gate_evidence_schema(),
        DEFAULT_DOCUMENT: render_attestation_markdown(),
    }
    if check:
        if any(
            not path.is_file() or path.read_text(encoding="utf-8") != content
            for path, content in outputs.items()
        ):
            raise AttestationError("RC_GENERATED_ARTIFACT_DRIFT")
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
    except AttestationError as error:
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
