#!/usr/bin/env python3
"""Build or check the deterministic B5 build-complete release evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
RELEASE_ROOT: Final = ROOT / "docs" / "evidence" / "release"
PACKAGE_MANIFEST_PATH: Final = RELEASE_ROOT / "portable-b5-python-packages.json"
ARTIFACT_MANIFEST_PATH: Final = RELEASE_ROOT / "portable-b5-artifact-manifest.json"
SHA256SUMS_PATH: Final = RELEASE_ROOT / "portable-b5-SHA256SUMS"
ATTESTATION_PATH: Final = RELEASE_ROOT / "portable-b5-build-complete-attestation.json"
CONTAINER_GATE_PATH: Final = RELEASE_ROOT / "portable-b5-container-gate.json"
NONROOT_RECEIPT_PATH: Final = RELEASE_ROOT / "portable-b5-nonroot-runtime.json"
IMAGE_SCAN_PATH: Final = RELEASE_ROOT / "portable-b5-image-privacy-scan.json"

SOURCE_COMMIT: Final = "dbea5411b1c0d81de0035d9ef08e28211fb79e79"
IMAGE_ID: Final = "524fe1212fc65e3d35a015717d03250e25c5ad32359e1c9595878c5bc6b057e8"
IMAGE_DIGEST: Final = "sha256:a835f9bdbc7a3854304e5574440a6a9944ea4bd04e839eae317a8e6554855eae"
IMAGE_SIZE_BYTES: Final = 219_809_071
IMAGE_REFERENCE: Final = "localhost/aioa-portable:b5-c2"
BASE_IMAGE: Final = (
    "docker.io/library/python:3.12-slim-bookworm@"
    "sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254"
)
PYTHON_VERSION: Final = "3.12.14"
APPLICATION_VERSION: Final = "0.2.0rc1"
WHEEL_SHA256: Final = "fe5b5df0448bf41c9aa0d6460b998adf280cab567b9ba688e5111cb71c0ff395"
CONTAINER_GATE_RECEIPT_SHA256: Final = (
    "8d3de09bc1d6756647eba8b74d67b4e86ee302be3889e666ac90058c2ec28db3"
)
NONROOT_RECEIPT_IMAGE_DIGEST: Final = IMAGE_DIGEST
IMAGE_SCAN_RECEIPT_SHA256: Final = (
    "19fc3b0c12ba11305f25f595fd85d7344ccf0999af58ea70f5703daa926ffcac"
)
_LOCK_LINE: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^ ]+) "
    r"--hash=sha256:(?P<sha256>[0-9a-f]{64})$"
)
_SOURCE_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (
    ("BUILD_CONTEXT_POLICY", ".dockerignore"),
    ("CONTAINER_DEFINITION", "Dockerfile"),
    ("LICENSE", "LICENSE"),
    ("PACKAGE_DATA_MANIFEST", "MANIFEST.in"),
    ("PROJECT_README", "README.md"),
    ("PYTHON_PACKAGE_CONTRACT", "pyproject.toml"),
    ("BUILD_DEPENDENCY_LOCK", "requirements/build.lock"),
    ("RUNTIME_DEPENDENCY_LOCK", "requirements/portable.lock"),
    ("PORTABLE_RUNTIME_CONTRACT", "docs/PORTABLE_RUNTIME.md"),
    (
        "CONTAINER_JUDGE_RUNBOOK",
        "docs/operations/container-judge-certification.md",
    ),
    ("SUBMISSION_DEMO_RUNBOOK", "docs/submission/demo-runbook.md"),
    (
        "REVIEWER_EVIDENCE_MANIFEST",
        "docs/evidence/reviewer-evidence-manifest.json",
    ),
)
_CHECKS: Final[tuple[dict[str, object], ...]] = (
    {"check_id": "B4_HARDENING_GATE", "proof_tests": 43, "scenarios": 11, "status": "PASS"},
    {"check_id": "CLEAN_CLONE", "exact_source_commit": True, "status": "PASS"},
    {"check_id": "CONTAINER_JUDGE_GATE", "invocations": 2, "status": "PASS"},
    {"check_id": "DIFF_CHECK", "status": "PASS"},
    {"check_id": "FULL_PYTEST", "proof_tests": 1428, "skipped": 0, "status": "PASS"},
    {"check_id": "IMAGE_EXPORT_PRIVACY_SCAN", "findings": 0, "status": "PASS"},
    {"check_id": "NATIVE_PORTABLE_FLOW", "status": "PASS"},
    {"check_id": "NONROOT_OCI_RUNTIME", "effective_uid": 65532, "status": "PASS"},
    {"check_id": "P0_GATE", "gates": 15, "status": "PASS"},
    {"check_id": "P1_GATE", "gates": 6, "status": "PASS"},
    {"check_id": "PACKAGE_BUILD", "status": "PASS"},
    {"check_id": "PIP_CHECK", "status": "PASS"},
    {"check_id": "RUFF", "status": "PASS"},
    {"check_id": "SECRET_SCAN", "findings": 0, "status": "PASS"},
)


class B5EvidenceError(RuntimeError):
    """A deterministic release input or output failed closed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _compact_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise B5EvidenceError("B5_RELEASE_INPUT_UNAVAILABLE") from error


def _git_environment() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _source_bound_sha256(relative_path: str) -> str:
    try:
        result = subprocess.run(
            ("git", "show", f"{SOURCE_COMMIT}:{relative_path}"),
            cwd=ROOT,
            env=_git_environment(),
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise B5EvidenceError("B5_SOURCE_ARTIFACT_UNAVAILABLE") from error
    current = _sha256_path(ROOT / relative_path)
    if result.returncode != 0 or _sha256_bytes(result.stdout) != current:
        raise B5EvidenceError("B5_SOURCE_ARTIFACT_DRIFT")
    return current


def _normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _project_version() -> str:
    try:
        document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = document["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise B5EvidenceError("B5_PROJECT_VERSION_INVALID") from error
    if version != APPLICATION_VERSION:
        raise B5EvidenceError("B5_PROJECT_VERSION_INVALID")
    return version


def _locked_packages() -> list[dict[str, object]]:
    try:
        lines = (ROOT / "requirements/portable.lock").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise B5EvidenceError("B5_PORTABLE_LOCK_UNAVAILABLE") from error
    packages: list[dict[str, object]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise B5EvidenceError("B5_PORTABLE_LOCK_INVALID")
        packages.append(
            {
                "artifact_sha256": match.group("sha256"),
                "name": _normalize_name(match.group("name")),
                "provenance": "HASH_PINNED_PORTABLE_LOCK",
                "version": match.group("version"),
            }
        )
    names = [str(package["name"]) for package in packages]
    if len(packages) != 55 or names != sorted(names) or len(names) != len(set(names)):
        raise B5EvidenceError("B5_PORTABLE_LOCK_INVALID")
    return packages


def build_package_manifest() -> dict[str, object]:
    packages = _locked_packages()
    packages.extend(
        [
            {
                "artifact_sha256": WHEEL_SHA256,
                "name": "aioa-nonzero-cloudops-agent",
                "provenance": "REPRODUCIBLE_PROJECT_WHEEL",
                "version": _project_version(),
            },
            {
                "artifact_sha256": None,
                "name": "pip",
                "provenance": "DIGEST_PINNED_BASE_IMAGE",
                "version": "25.0.1",
            },
        ]
    )
    packages.sort(key=lambda package: (str(package["name"]), str(package["version"])))
    material: dict[str, object] = {
        "base_image": BASE_IMAGE,
        "document_type": "AIOA_B5_DETERMINISTIC_PYTHON_PACKAGE_MANIFEST",
        "image_digest": IMAGE_DIGEST,
        "package_count": len(packages),
        "packages": packages,
        "platform": "linux/amd64",
        "portable_lock_sha256": _sha256_path(ROOT / "requirements/portable.lock"),
        "python_version": PYTHON_VERSION,
        "sbom_generator": "LOCK_PLUS_EXACT_IMAGE_OBSERVATION",
        "sbom_tool_status": "DEDICATED_SBOM_TOOL_UNAVAILABLE_PACKAGE_MANIFEST_USED",
        "schema_version": 1,
        "source_commit": SOURCE_COMMIT,
        "wheel_sha256": WHEEL_SHA256,
    }
    return {**material, "manifest_sha256": _sha256_bytes(_compact_bytes(material))}


def _load_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in values:
            if name in result:
                raise ValueError("duplicate key")
            result[name] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise B5EvidenceError("B5_RELEASE_RECEIPT_INVALID") from error
    if not isinstance(value, dict):
        raise B5EvidenceError("B5_RELEASE_RECEIPT_INVALID")
    return value


def _source_tree_oid() -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", f"{SOURCE_COMMIT}^{{tree}}"),
            cwd=ROOT,
            env=_git_environment(),
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise B5EvidenceError("B5_SOURCE_COMMIT_UNAVAILABLE") from error
    oid = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", oid) is None:
        raise B5EvidenceError("B5_SOURCE_COMMIT_UNAVAILABLE")
    return oid


def _validate_bound_receipts() -> None:
    gate = _load_json(CONTAINER_GATE_PATH)
    nonroot = _load_json(NONROOT_RECEIPT_PATH)
    scan = _load_json(IMAGE_SCAN_PATH)
    gate_image = gate.get("image")
    gate_material = {name: value for name, value in gate.items() if name != "receipt_sha256"}
    scan_material = {name: value for name, value in scan.items() if name != "receipt_sha256"}
    if (
        gate.get("status") != "PASS"
        or gate.get("receipt_sha256") != CONTAINER_GATE_RECEIPT_SHA256
        or gate.get("receipt_sha256") != _sha256_bytes(_compact_bytes(gate_material))
        or gate.get("aws_calls") != 0
        or gate.get("aws_mutations") != 0
        or gate.get("external_network_connections") != 0
        or not isinstance(gate_image, dict)
        or gate_image.get("id") != IMAGE_ID
        or gate_image.get("digest") != IMAGE_DIGEST
        or gate_image.get("source_commit") != SOURCE_COMMIT
        or nonroot.get("receipt_type") != "AIOA_OCI_NONROOT_SERVER_PROOF"
        or nonroot.get("image_id") != IMAGE_ID
        or nonroot.get("image_digest") != NONROOT_RECEIPT_IMAGE_DIGEST
        or nonroot.get("source_commit") != SOURCE_COMMIT
        or nonroot.get("effective_uid") != 65532
        or nonroot.get("cap_eff") != "0000000000000000"
        or nonroot.get("no_new_privs") != "1"
        or scan.get("status") != "PASS"
        or scan.get("receipt_sha256") != IMAGE_SCAN_RECEIPT_SHA256
        or scan.get("receipt_sha256") != _sha256_bytes(_compact_bytes(scan_material))
        or scan.get("findings_count") != 0
        or scan.get("image_id") != IMAGE_ID
        or scan.get("image_digest") != IMAGE_DIGEST
        or scan.get("source_commit") != SOURCE_COMMIT
    ):
        raise B5EvidenceError("B5_RELEASE_RECEIPT_INVALID")


def build_artifact_manifest(package_bytes: bytes) -> dict[str, object]:
    _validate_bound_receipts()
    artifacts = {
        artifact_id: {
            "path": relative_path,
            "sha256": _source_bound_sha256(relative_path),
        }
        for artifact_id, relative_path in _SOURCE_ARTIFACTS
    }
    evidence = {
        "container_gate": {
            "file_sha256": _sha256_path(CONTAINER_GATE_PATH),
            "path": CONTAINER_GATE_PATH.relative_to(ROOT).as_posix(),
            "receipt_sha256": CONTAINER_GATE_RECEIPT_SHA256,
        },
        "image_privacy_scan": {
            "file_sha256": _sha256_path(IMAGE_SCAN_PATH),
            "path": IMAGE_SCAN_PATH.relative_to(ROOT).as_posix(),
            "receipt_sha256": IMAGE_SCAN_RECEIPT_SHA256,
        },
        "nonroot_runtime": {
            "file_sha256": _sha256_path(NONROOT_RECEIPT_PATH),
            "path": NONROOT_RECEIPT_PATH.relative_to(ROOT).as_posix(),
        },
        "python_packages": {
            "file_sha256": _sha256_bytes(package_bytes),
            "path": PACKAGE_MANIFEST_PATH.relative_to(ROOT).as_posix(),
        },
    }
    material: dict[str, object] = {
        "application_version": APPLICATION_VERSION,
        "artifacts": artifacts,
        "build": {
            "clean_clone": True,
            "dependency_install": "PIP_REQUIRE_HASHES",
            "platform": "linux/amd64",
            "reproducible_wheel_sha256": WHEEL_SHA256,
            "source_date_epoch": 0,
        },
        "document_type": "AIOA_B5_PORTABLE_ARTIFACT_MANIFEST",
        "evidence": evidence,
        "external_actions": {
            "aws_calls": 0,
            "aws_mutations": 0,
            "deployments": 0,
            "image_pushes": 0,
            "publications": 0,
            "remote_git_pushes": 0,
        },
        "image": {
            "base_image": BASE_IMAGE,
            "configured_user": "aioa",
            "entrypoint": ["python", "-m", "aioa_cloudops_agent.portable_server"],
            "health_path": "/health",
            "id": IMAGE_ID,
            "local_manifest_digest": IMAGE_DIGEST,
            "local_reference": IMAGE_REFERENCE,
            "readiness_path": "/ready",
            "registry_digest": None,
            "size_bytes": IMAGE_SIZE_BYTES,
            "status": "LOCAL_ONLY_NOT_PUSHED",
        },
        "runtime_contract": {
            "allowed_egress": "none",
            "authority_mode": "HUMAN_APPROVAL_REQUIRED",
            "model_provider": "mock",
            "runtime_mode": "portable",
            "storage_mode": "file",
        },
        "schema_version": 1,
        "source_commit": SOURCE_COMMIT,
        "source_tree_git_oid": _source_tree_oid(),
        "status": "FROZEN_LOCAL_ARTIFACT",
    }
    return {**material, "manifest_sha256": _sha256_bytes(_compact_bytes(material))}


def _sums_bytes(
    package_bytes: bytes,
    artifact_bytes: bytes,
) -> bytes:
    values = {
        relative_path: _sha256_path(ROOT / relative_path)
        for _artifact_id, relative_path in _SOURCE_ARTIFACTS
    }
    values.update(
        {
            ARTIFACT_MANIFEST_PATH.relative_to(ROOT).as_posix(): _sha256_bytes(
                artifact_bytes
            ),
            CONTAINER_GATE_PATH.relative_to(ROOT).as_posix(): _sha256_path(
                CONTAINER_GATE_PATH
            ),
            IMAGE_SCAN_PATH.relative_to(ROOT).as_posix(): _sha256_path(IMAGE_SCAN_PATH),
            NONROOT_RECEIPT_PATH.relative_to(ROOT).as_posix(): _sha256_path(
                NONROOT_RECEIPT_PATH
            ),
            PACKAGE_MANIFEST_PATH.relative_to(ROOT).as_posix(): _sha256_bytes(
                package_bytes
            ),
        }
    )
    return "".join(f"{digest}  {path}\n" for path, digest in sorted(values.items())).encode(
        "utf-8"
    )


def build_attestation(
    *,
    package_bytes: bytes,
    artifact_bytes: bytes,
    sums_bytes: bytes,
) -> dict[str, object]:
    material: dict[str, object] = {
        "artifact_manifest_file_sha256": _sha256_bytes(artifact_bytes),
        "aws_calls": 0,
        "aws_mutations": 0,
        "checks": list(_CHECKS),
        "container_digest": IMAGE_DIGEST,
        "container_id": IMAGE_ID,
        "deployments": 0,
        "document_type": "AIOA_B5_BUILD_COMPLETE_ATTESTATION",
        "freeze_rule": (
            "ANY_RUNTIME_SOURCE_DEPENDENCY_CONTAINER_OR_BOUND_DOCUMENT_CHANGE_"
            "INVALIDATES_BUILD_COMPLETE_AND_REQUIRES_B5_REBUILD"
        ),
        "image_pushes": 0,
        "limitations": (
            "Local OCI build and offline/mock execution only; no registry publication, public "
            "endpoint, live provider receipt, AWS identity, or live infrastructure mutation is "
            "claimed."
        ),
        "package_manifest_file_sha256": _sha256_bytes(package_bytes),
        "publications": 0,
        "remote_git_pushes": 0,
        "schema_version": 1,
        "sha256sums_file_sha256": _sha256_bytes(sums_bytes),
        "source_commit": SOURCE_COMMIT,
        "status": "BUILD_COMPLETE",
    }
    return {**material, "attestation_sha256": _sha256_bytes(_compact_bytes(material))}


def build_outputs() -> dict[Path, bytes]:
    package_bytes = _canonical_bytes(build_package_manifest())
    artifact_bytes = _canonical_bytes(build_artifact_manifest(package_bytes))
    sums_bytes = _sums_bytes(package_bytes, artifact_bytes)
    attestation_bytes = _canonical_bytes(
        build_attestation(
            package_bytes=package_bytes,
            artifact_bytes=artifact_bytes,
            sums_bytes=sums_bytes,
        )
    )
    return {
        PACKAGE_MANIFEST_PATH: package_bytes,
        ARTIFACT_MANIFEST_PATH: artifact_bytes,
        SHA256SUMS_PATH: sums_bytes,
        ATTESTATION_PATH: attestation_bytes,
    }


def _write_if_changed(path: Path, content: bytes) -> None:
    if path.parent != RELEASE_ROOT or path.is_symlink():
        raise B5EvidenceError("B5_RELEASE_OUTPUT_UNSAFE")
    try:
        if path.exists() and path.read_bytes() == content:
            return
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            os.fchmod(descriptor, 0o644)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            temporary_name = ""
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_name:
                with suppress(OSError):
                    os.unlink(temporary_name)
    except OSError as error:
        raise B5EvidenceError("B5_RELEASE_OUTPUT_UNAVAILABLE") from error


def validate_outputs(outputs: Mapping[Path, bytes] | None = None) -> tuple[str, ...]:
    try:
        expected = build_outputs() if outputs is None else dict(outputs)
    except B5EvidenceError as error:
        return (error.reason,)
    reasons: list[str] = []
    for path, content in expected.items():
        try:
            if path.read_bytes() != content:
                reasons.append("B5_RELEASE_OUTPUT_DRIFT")
        except OSError:
            reasons.append("B5_RELEASE_OUTPUT_MISSING")
    try:
        attestation = json.loads(expected[ATTESTATION_PATH])
        artifact = json.loads(expected[ARTIFACT_MANIFEST_PATH])
        packages = json.loads(expected[PACKAGE_MANIFEST_PATH])
    except (KeyError, TypeError, json.JSONDecodeError):
        reasons.append("B5_RELEASE_OUTPUT_INVALID")
    else:
        attestation_material = {
            name: value for name, value in attestation.items() if name != "attestation_sha256"
        }
        artifact_material = {
            name: value for name, value in artifact.items() if name != "manifest_sha256"
        }
        package_material = {
            name: value for name, value in packages.items() if name != "manifest_sha256"
        }
        if (
            attestation.get("status") != "BUILD_COMPLETE"
            or attestation.get("attestation_sha256")
            != _sha256_bytes(_compact_bytes(attestation_material))
            or attestation.get("container_digest") != IMAGE_DIGEST
            or attestation.get("source_commit") != SOURCE_COMMIT
            or artifact.get("status") != "FROZEN_LOCAL_ARTIFACT"
            or artifact.get("manifest_sha256")
            != _sha256_bytes(_compact_bytes(artifact_material))
            or artifact.get("source_commit") != SOURCE_COMMIT
            or packages.get("package_count") != 57
            or packages.get("manifest_sha256")
            != _sha256_bytes(_compact_bytes(package_material))
        ):
            reasons.append("B5_RELEASE_OUTPUT_INVALID")
    return tuple(sorted(set(reasons)))


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        outputs = build_outputs()
        if args.check:
            reasons = validate_outputs(outputs)
        else:
            RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
            for path, content in outputs.items():
                _write_if_changed(path, content)
            reasons = validate_outputs(outputs)
    except B5EvidenceError as error:
        reasons = (error.reason,)
    payload = {
        "artifact_count": 4 if not reasons else 0,
        "aws_mutations": 0,
        "reason": ",".join(reasons),
        "remote_pushes": 0,
        "status": "PASS" if not reasons else "FAIL",
    }
    if args.json:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    elif reasons:
        print(f"B5_RELEASE_EVIDENCE FAIL reasons={','.join(reasons)}")
    else:
        print("B5_RELEASE_EVIDENCE PASS artifacts=4 status=BUILD_COMPLETE")
    return 0 if not reasons else 1


if __name__ == "__main__":
    raise SystemExit(main())
