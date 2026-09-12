#!/usr/bin/env python3
"""Render and authenticate the Day 15 SAM template without contacting AWS."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.validate_template import (  # noqa: E402
    DEFAULT_TEMPLATE,
    DEFAULT_TOOLCHAIN,
    TemplateFailure,
    canonical_json,
    load_template,
    load_toolchain,
    validate_structure,
    validate_template_toolchain,
)

DEFAULT_RENDERED_TEMPLATE: Final = ROOT / "dist" / "day15" / "rendered-template.yaml"
DEFAULT_PROVENANCE: Final = ROOT / "dist" / "day15" / "rendered-template.provenance.json"
VALIDATOR_SOURCE: Final = ROOT / "scripts" / "day15" / "validate_template.py"
EXPECTED_REGION: Final = "eu-central-1"
LOCAL_CODE_URI: Final = "../../dist/day15/aioa-lambda.zip"
ARTIFACT_BUCKET_PARAMETER: Final = "Day15ArtifactBucketName"
ARTIFACT_KEY_PARAMETER: Final = "Day15ArtifactObjectKey"
PACKAGING_TRANSFORM: Final = {
    "bucket_parameter": ARTIFACT_BUCKET_PARAMETER,
    "key_parameter": ARTIFACT_KEY_PARAMETER,
    "source_code_uri": LOCAL_CODE_URI,
}
PROVENANCE_KEYS: Final = frozenset(
    {
        "repository_commit_oid",
        "packaging_transform",
        "rendered_template_sha256",
        "renderer_sha256",
        "schema_version",
        "source_model_sha256",
        "source_template_sha256",
        "status",
        "tool_versions",
        "toolchain_sha256",
        "validator_sha256",
    }
)


class RenderFailure(RuntimeError):
    """A stable, public-safe renderer failure."""

    def __init__(self, reason: str, *, status: str = "FAIL") -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            env=_git_environment(),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RenderFailure("RENDER_REPOSITORY_UNAVAILABLE", status="BLOCKED") from error
    if result.returncode != 0:
        raise RenderFailure("RENDER_REPOSITORY_UNAVAILABLE", status="BLOCKED")
    return result.stdout


def _relative(path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(ROOT.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as error:
        raise RenderFailure("RENDER_INPUT_NOT_CANONICAL") from error


def repository_binding(template: Path, toolchain: Path) -> str:
    """Bind rendering to clean, tracked source inputs and the renderer itself."""

    inputs = tuple(
        _relative(path) for path in (template, toolchain, Path(__file__), VALIDATOR_SOURCE)
    )
    repository = Path(_git("rev-parse", "--show-toplevel").strip())
    if repository.resolve() != ROOT.resolve():
        raise RenderFailure("RENDER_REPOSITORY_ROOT_MISMATCH")
    status = _git("status", "--porcelain=v1", "--untracked-files=all", "--", *inputs)
    if status.strip():
        raise RenderFailure("RENDER_INPUTS_NOT_CLEAN", status="BLOCKED")
    _git("ls-files", "--error-unmatch", "--", *inputs)
    head = _git("rev-parse", "--verify", "HEAD").strip()
    if len(head) not in {40, 64} or any(character not in "0123456789abcdef" for character in head):
        raise RenderFailure("RENDER_COMMIT_OID_INVALID")
    return head


def render_model(template: dict[str, object]) -> dict[str, object]:
    """Run the pinned local SAM Translator with an explicit region and no AWS calls."""

    if validate_structure(template):
        raise RenderFailure("RENDER_SOURCE_TEMPLATE_INVALID")
    prepared = copy.deepcopy(template)
    parameters = prepared.get("Parameters")
    resources = prepared.get("Resources")
    if not isinstance(parameters, dict) or not isinstance(resources, dict):
        raise RenderFailure("RENDER_SOURCE_TEMPLATE_INVALID")
    if ARTIFACT_BUCKET_PARAMETER in parameters or ARTIFACT_KEY_PARAMETER in parameters:
        raise RenderFailure("RENDER_PACKAGING_PARAMETER_COLLISION")
    parameters[ARTIFACT_BUCKET_PARAMETER] = {
        "AllowedPattern": r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
        "Type": "String",
    }
    parameters[ARTIFACT_KEY_PARAMETER] = {
        "AllowedPattern": r"^day15/reviewed/[A-Za-z0-9._-]+$",
        "Type": "String",
    }
    rewritten = 0
    for resource in resources.values():
        if not isinstance(resource, dict) or resource.get("Type") != "AWS::Serverless::Function":
            continue
        properties = resource.get("Properties")
        if not isinstance(properties, dict) or properties.get("CodeUri") != LOCAL_CODE_URI:
            raise RenderFailure("RENDER_CODE_URI_CONTRACT_INVALID")
        properties["CodeUri"] = {
            "Bucket": {"Ref": ARTIFACT_BUCKET_PARAMETER},
            "Key": {"Ref": ARTIFACT_KEY_PARAMETER},
        }
        rewritten += 1
    if rewritten != 2:
        raise RenderFailure("RENDER_CODE_URI_CONTRACT_INVALID")
    try:
        from boto3.session import Session
        from samtranslator.parser.parser import Parser
        from samtranslator.translator.translator import Translator
    except ImportError as error:
        raise RenderFailure("SAM_TRANSLATOR_UNAVAILABLE", status="BLOCKED") from error
    try:
        rendered = Translator(
            {},
            Parser(),
            boto_session=Session(region_name=EXPECTED_REGION),
        ).translate(prepared, {})
    except Exception as error:  # SAM uses a family of non-public validation exceptions.
        raise RenderFailure("SAM_TRANSLATION_FAILED") from error
    if not isinstance(rendered, dict):
        raise RenderFailure("SAM_TRANSLATION_OUTPUT_INVALID")
    resources = rendered.get("Resources")
    if "Transform" in rendered or not isinstance(resources, dict):
        raise RenderFailure("SAM_TRANSLATION_OUTPUT_INVALID")
    if any(
        isinstance(resource, dict)
        and isinstance(resource.get("Type"), str)
        and str(resource["Type"]).startswith("AWS::Serverless::")
        for resource in resources.values()
    ):
        raise RenderFailure("SAM_TRANSLATION_INCOMPLETE")
    return rendered


def _provenance(
    *,
    template: Path,
    toolchain: Path,
    rendered_bytes: bytes,
    versions: dict[str, str],
) -> dict[str, object]:
    source = load_template(template)
    return {
        "packaging_transform": PACKAGING_TRANSFORM,
        "repository_commit_oid": repository_binding(template, toolchain),
        "rendered_template_sha256": _sha256(rendered_bytes),
        "renderer_sha256": _sha256(Path(__file__).read_bytes()),
        "schema_version": 1,
        "source_model_sha256": _sha256(canonical_json(source).encode()),
        "source_template_sha256": _sha256(template.read_bytes()),
        "status": "PASS",
        "tool_versions": versions,
        "toolchain_sha256": _sha256(toolchain.read_bytes()),
        "validator_sha256": _sha256(VALIDATOR_SOURCE.read_bytes()),
    }


def _atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise RenderFailure("RENDER_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="day15-render-", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise RenderFailure("RENDER_OUTPUT_WRITE_FAILED") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def render_template(
    *,
    template: Path = DEFAULT_TEMPLATE,
    toolchain: Path = DEFAULT_TOOLCHAIN,
    output: Path = DEFAULT_RENDERED_TEMPLATE,
    provenance: Path = DEFAULT_PROVENANCE,
) -> dict[str, object]:
    """Render the source and atomically publish canonical output plus provenance."""

    status, reasons, versions = validate_template_toolchain(toolchain)
    if status != "PASS":
        raise RenderFailure(
            reasons[0] if reasons else "TEMPLATE_TOOLCHAIN_UNAVAILABLE",
            status="BLOCKED" if status in {"BLOCKED", "PARTIAL"} else "FAIL",
        )
    load_toolchain(toolchain)
    rendered = render_model(load_template(template))
    rendered_bytes = (canonical_json(rendered) + "\n").encode()
    proof = _provenance(
        template=template,
        toolchain=toolchain,
        rendered_bytes=rendered_bytes,
        versions=versions,
    )
    _atomic_write(output, rendered_bytes)
    _atomic_write(provenance, (canonical_json(proof) + "\n").encode())
    return proof


def verify_rendered_template(
    *,
    template: Path,
    toolchain: Path,
    rendered_template: Path,
    provenance: Path | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Re-render and verify bytes and closed provenance rather than trusting evidence files."""

    proof_path = provenance or rendered_template.with_name(
        f"{rendered_template.stem}.provenance.json"
    )
    try:
        rendered_bytes = rendered_template.read_bytes()
        proof_raw = proof_path.read_text(encoding="utf-8")
        proof = json.loads(proof_raw)
    except FileNotFoundError as error:
        raise RenderFailure("RENDERED_TEMPLATE_PROOF_REQUIRED", status="BLOCKED") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RenderFailure("RENDERED_TEMPLATE_PROOF_INVALID") from error
    if (
        not isinstance(proof, dict)
        or set(proof) != PROVENANCE_KEYS
        or proof_raw != canonical_json(proof) + "\n"
    ):
        raise RenderFailure("RENDERED_TEMPLATE_PROOF_INVALID")
    try:
        stored = load_template(rendered_template)
    except TemplateFailure as error:
        raise RenderFailure("RENDERED_TEMPLATE_INVALID") from error
    if "Transform" in stored:
        raise RenderFailure("RENDERED_TEMPLATE_STILL_HAS_TRANSFORM")
    status, reasons, versions = validate_template_toolchain(toolchain)
    if status != "PASS":
        raise RenderFailure(
            reasons[0] if reasons else "TEMPLATE_TOOLCHAIN_UNAVAILABLE",
            status="BLOCKED" if status in {"BLOCKED", "PARTIAL"} else "FAIL",
        )
    expected_model = render_model(load_template(template))
    expected_bytes = (canonical_json(expected_model) + "\n").encode()
    if rendered_bytes != expected_bytes or stored != expected_model:
        raise RenderFailure("RENDERED_TEMPLATE_REPRODUCIBILITY_MISMATCH")
    expected_proof = _provenance(
        template=template,
        toolchain=toolchain,
        rendered_bytes=expected_bytes,
        versions=versions,
    )
    if proof != expected_proof:
        raise RenderFailure("RENDERED_TEMPLATE_PROVENANCE_MISMATCH")
    return expected_model, expected_proof


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--toolchain", type=Path, default=DEFAULT_TOOLCHAIN)
    parser.add_argument("--output", type=Path, default=DEFAULT_RENDERED_TEMPLATE)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            _, proof = verify_rendered_template(
                template=args.template,
                toolchain=args.toolchain,
                rendered_template=args.output,
                provenance=args.provenance,
            )
        else:
            proof = render_template(
                template=args.template,
                toolchain=args.toolchain,
                output=args.output,
                provenance=args.provenance,
            )
        payload: dict[str, object] = {"provenance": proof, "status": "PASS"}
    except RenderFailure as error:
        payload = {"reasons": [error.reason], "status": error.status}
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"DAY15_RENDER {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
