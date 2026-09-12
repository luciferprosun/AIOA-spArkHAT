#!/usr/bin/env python3
"""Certify two clean, isolated portable judge flows from one local OCI image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import ValidationError

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aioa_cloudops_agent.persistence.local_integrity import (  # noqa: E402
    LocalIntegrityError,
    atomic_write_private_json,
    read_private_json,
)
from aioa_cloudops_agent.portable import PortableDemoReceipt  # noqa: E402
from aioa_cloudops_agent.release.post_deploy_verifier import (  # noqa: E402
    FailureProbeId,
)

DEFAULT_OUTPUT: Final = ROOT / ".local" / "b5-b6" / "container-judge-gate.json"
_COMMIT: Final = re.compile(r"^[0-9a-f]{40}$")
_IMAGE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,255}$")
_SHA256: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENTRYPOINT: Final = ["python", "-m", "aioa_cloudops_agent.portable_server"]
_SAFE_ENGINE_RUN_ARGS: Final = frozenset(
    {
        "--cgroups=disabled",
        "--log-driver=k8s-file",
    }
)
_BLOCKED_ENV_NAMES: Final = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_CONFIG_FILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "BOTO_CONFIG",
        "NETRC",
        "OPENAI_API_KEY",
    }
)


class ContainerGateError(RuntimeError):
    """One public-safe, fixed-reason container gate failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _strict_json(raw: str, *, reason: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in values:
            if name in result:
                raise ValueError("duplicate key")
            result[name] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ContainerGateError(reason) from error


def _safe_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in _BLOCKED_ENV_NAMES
        and not name.startswith("AWS_")
        and not name.startswith("BEDROCK_")
    }
    environment.update(
        {
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _resolve_engine(value: str | None) -> str:
    candidates = (value,) if value is not None else ("docker", "podman")
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
        path = Path(candidate)
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise ContainerGateError("CONTAINER_ENGINE_UNAVAILABLE")


def _run_command(
    command: Sequence[str],
    *,
    timeout: int,
    failure_reason: str,
    stdout_limit: int = 2 * 1024 * 1024,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            tuple(command),
            cwd=ROOT,
            env=_safe_environment(),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContainerGateError(failure_reason) from error
    if (
        result.returncode != 0
        or len(result.stdout.encode("utf-8")) > stdout_limit
        or len(result.stderr.encode("utf-8")) > 256 * 1024
    ):
        raise ContainerGateError(failure_reason)
    return result


def _normalize_image_id(value: object) -> str:
    if not isinstance(value, str):
        raise ContainerGateError("CONTAINER_IMAGE_IDENTITY_INVALID")
    normalized = value.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ContainerGateError("CONTAINER_IMAGE_IDENTITY_INVALID")
    return normalized


def inspect_image(
    engine: str,
    image: str,
    expected_source_commit: str,
) -> dict[str, object]:
    """Return only the validated, non-secret image identity contract."""

    result = _run_command(
        (engine, "image", "inspect", image),
        timeout=60,
        failure_reason="CONTAINER_IMAGE_INSPECT_FAILED",
    )
    value = _strict_json(result.stdout, reason="CONTAINER_IMAGE_INSPECT_INVALID")
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ContainerGateError("CONTAINER_IMAGE_INSPECT_INVALID")
    document = value[0]
    config = document.get("Config")
    if not isinstance(config, dict):
        raise ContainerGateError("CONTAINER_IMAGE_CONFIG_INVALID")
    labels = config.get("Labels", document.get("Labels"))
    if not isinstance(labels, dict):
        raise ContainerGateError("CONTAINER_IMAGE_CONFIG_INVALID")
    image_id = _normalize_image_id(document.get("Id"))
    user = config.get("User", document.get("User"))
    entrypoint = config.get("Entrypoint")
    if (
        user != "aioa"
        or entrypoint != _ENTRYPOINT
        or labels.get("org.opencontainers.image.revision") != expected_source_commit
        or labels.get("org.opencontainers.image.licenses") != "MIT"
        or document.get("Architecture") != "amd64"
        or document.get("Os") != "linux"
    ):
        raise ContainerGateError("CONTAINER_IMAGE_CONFIG_INVALID")
    digest: str | None = None
    repo_digests = document.get("RepoDigests")
    if isinstance(repo_digests, list) and repo_digests:
        first = repo_digests[0]
        if isinstance(first, str) and "@" in first:
            candidate = first.rsplit("@", maxsplit=1)[-1]
            if _SHA256.fullmatch(candidate) is not None:
                digest = candidate
    if digest is None:
        candidate = document.get("Digest")
        if isinstance(candidate, str) and _SHA256.fullmatch(candidate) is not None:
            digest = candidate
    content_identity = digest if digest is not None else f"sha256:{image_id}"
    size = document.get("Size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ContainerGateError("CONTAINER_IMAGE_CONFIG_INVALID")
    return {
        "architecture": "amd64",
        "configured_user": "aioa",
        "content_identity": content_identity,
        "digest": digest,
        "entrypoint": _ENTRYPOINT,
        "id": image_id,
        "license": "MIT",
        "os": "linux",
        "size_bytes": size,
        "source_commit": expected_source_commit,
    }


def _hardened_run_prefix(
    engine: str,
    extra_args: Sequence[str],
    user_override: str | None,
) -> list[str]:
    if len(extra_args) != len(set(extra_args)) or any(
        value not in _SAFE_ENGINE_RUN_ARGS for value in extra_args
    ):
        raise ContainerGateError("CONTAINER_ENGINE_RUN_ARGUMENT_UNSAFE")
    command = [
        engine,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--env",
        "AWS_EC2_METADATA_DISABLED=true",
        "--env",
        "PYTHONNOUSERSITE=1",
        *extra_args,
    ]
    if user_override is not None:
        if user_override != "0:0":
            raise ContainerGateError("CONTAINER_ENGINE_USER_OVERRIDE_UNSAFE")
        command.extend(("--user", user_override))
    return command


def _engine_nonroot_probe(
    engine: str,
    image: str,
    extra_args: Sequence[str],
) -> dict[str, object]:
    program = (
        "import json,os,pathlib;"
        "s={k:v.strip() for k,v in (line.split(':',1) for line in "
        "pathlib.Path('/proc/self/status').read_text().splitlines() if ':' in line)};"
        "print(json.dumps({'cap_eff':s['CapEff'],'effective_gid':os.getegid(),"
        "'effective_uid':os.geteuid(),'no_new_privs':s['NoNewPrivs']},sort_keys=True))"
    )
    command = [
        *_hardened_run_prefix(engine, extra_args, None),
        "--entrypoint",
        "python",
        image,
        "-c",
        program,
    ]
    result = _run_command(
        command,
        timeout=60,
        failure_reason="CONTAINER_NONROOT_PROBE_FAILED",
        stdout_limit=16 * 1024,
    )
    proof = _strict_json(result.stdout, reason="CONTAINER_NONROOT_PROBE_INVALID")
    if not isinstance(proof, dict) or proof != {
        "cap_eff": "0000000000000000",
        "effective_gid": 65532,
        "effective_uid": 65532,
        "no_new_privs": "1",
    }:
        raise ContainerGateError("CONTAINER_NONROOT_PROBE_INVALID")
    return proof


def _external_nonroot_proof(
    path: Path,
    image_contract: Mapping[str, object],
    expected_source_commit: str,
) -> dict[str, object]:
    try:
        metadata = path.stat()
        value = read_private_json(path)
    except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
        raise ContainerGateError("CONTAINER_NONROOT_RECEIPT_INVALID") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or not isinstance(value, dict)
    ):
        raise ContainerGateError("CONTAINER_NONROOT_RECEIPT_INVALID")
    required_keys = {
        "cap_eff",
        "effective_gid",
        "effective_uid",
        "groups",
        "health",
        "image_digest",
        "image_id",
        "no_new_privs",
        "pid1",
        "ready",
        "receipt_type",
        "schema_version",
        "source_commit",
        "token_file",
    }
    if set(value) != required_keys:
        raise ContainerGateError("CONTAINER_NONROOT_RECEIPT_INVALID")
    health = value.get("health")
    ready = value.get("ready")
    token = value.get("token_file")
    groups = value.get("groups")
    if (
        value.get("schema_version") != 1
        or value.get("receipt_type") != "AIOA_OCI_NONROOT_SERVER_PROOF"
        or _normalize_image_id(value.get("image_id")) != image_contract["id"]
        or value.get("image_digest") != image_contract["content_identity"]
        or value.get("source_commit") != expected_source_commit
        or value.get("effective_uid") != 65532
        or value.get("effective_gid") != 65532
        or value.get("cap_eff") != "0000000000000000"
        or value.get("no_new_privs") != "1"
        or value.get("pid1") != "python -m aioa_cloudops_agent.portable_server"
        or not isinstance(groups, list)
        or 65532 not in groups
        or health != {"mode": "mock", "service": "aioa-local-hitl", "status": "ok"}
        or token != {"gid": 65532, "mode": "0o600", "uid": 65532}
        or not isinstance(ready, dict)
    ):
        raise ContainerGateError("CONTAINER_NONROOT_RECEIPT_INVALID")
    runtime = ready.get("runtime")
    if (
        ready.get("status") != "ready"
        or ready.get("process_status") != "READY"
        or ready.get("provider_status") != "READY"
        or ready.get("sandbox_status") != "READY"
        or not isinstance(runtime, dict)
        or runtime.get("agent_framework") != "strands-agents"
        or runtime.get("runtime_mode") != "portable"
        or runtime.get("provider") != "mock"
        or runtime.get("aws_calls_allowed") is not False
        or runtime.get("external_network_allowed") is not False
        or runtime.get("real_cloud_mutations_enabled") is not False
        or runtime.get("process_external_network_calls") != 0
        or runtime.get("process_provider_calls") != 0
        or runtime.get("process_sandbox_mutations") != 0
    ):
        raise ContainerGateError("CONTAINER_NONROOT_RECEIPT_INVALID")
    return {
        "cap_eff": value["cap_eff"],
        "effective_gid": value["effective_gid"],
        "effective_uid": value["effective_uid"],
        "health": "ok",
        "no_new_privs": value["no_new_privs"],
        "pid1": value["pid1"],
        "readiness": "ready",
        "token_mode": token["mode"],
    }


def validate_portable_flow(receipt: PortableDemoReceipt) -> dict[str, object]:
    """Validate and reduce one public portable receipt to the judge gate facts."""

    verification = receipt.nonzero_verification
    approved = verification.approved_path
    denied = verification.deny_path
    binding = next(
        (
            probe
            for probe in verification.failure_probes
            if probe.probe_id is FailureProbeId.RESOURCE_BINDING_MISMATCH
        ),
        None,
    )
    if (
        receipt.status != "PASS"
        or receipt.runtime_mode != "portable"
        or receipt.provider != "mock"
        or not receipt.provider_selection_explicit
        or receipt.external_network_connections != 0
        or receipt.provider_network_calls != 0
        or receipt.aws_calls != 0
        or receipt.aws_mutations != 0
        or receipt.sandbox_mutations != 1
        or approved.final_state != "SUCCESS_WITH_EVIDENCE"
        or approved.mock_mutations_before_explicit_decision != 0
        or approved.pending_approval_recovered_after_restart is not True
        or approved.mock_mutation_count != 1
        or approved.replay_rejected is not True
        or approved.replay_mutation_delta != 0
        or approved.recovery_reconciled is not True
        or approved.recovery_receipt_hash_match is not True
        or approved.recovery_mock_mutation_count != 0
        or denied.final_state != "DENIED_BY_HUMAN"
        or denied.execution_receipt_absent is not True
        or denied.independent_verification_absent is not True
        or denied.mock_mutation_count != 0
        or binding is None
        or binding.outcome != "REJECTED_FAIL_CLOSED"
        or binding.mock_mutation_delta != 0
        or binding.aws_mutations != 0
    ):
        raise ContainerGateError("CONTAINER_JUDGE_FLOW_INVALID")
    return {
        "approved_final_state": approved.final_state,
        "approved_mock_mutations": approved.mock_mutation_count,
        "aws_calls": receipt.aws_calls,
        "aws_mutations": receipt.aws_mutations,
        "binding_tamper": binding.outcome,
        "denied_final_state": denied.final_state,
        "denied_mock_mutations": denied.mock_mutation_count,
        "external_network_connections": receipt.external_network_connections,
        "pending_approval_recovered": approved.pending_approval_recovered_after_restart,
        "provider_network_calls": receipt.provider_network_calls,
        "receipt_sha256": receipt.receipt_sha256,
        "recovery_reconciled": approved.recovery_reconciled,
        "replay_mutation_delta": approved.replay_mutation_delta,
        "replay_rejected": approved.replay_rejected,
    }


def _run_portable_flow(
    engine: str,
    image: str,
    extra_args: Sequence[str],
    user_override: str | None,
    index: int,
) -> dict[str, object]:
    command = [
        *_hardened_run_prefix(engine, extra_args, user_override),
        "--entrypoint",
        "python",
        image,
        "-m",
        "aioa_cloudops_agent.portable",
        "--workspace",
        "/tmp/aioa-workspace",
        "--output",
        f"/tmp/aioa-receipt-{index}.json",
    ]
    result = _run_command(
        command,
        timeout=300,
        failure_reason="CONTAINER_JUDGE_FLOW_FAILED",
    )
    _strict_json(result.stdout, reason="CONTAINER_JUDGE_RECEIPT_INVALID")
    try:
        receipt = PortableDemoReceipt.model_validate_json(result.stdout)
    except ValidationError as error:
        raise ContainerGateError("CONTAINER_JUDGE_RECEIPT_INVALID") from error
    return {"invocation": index, **validate_portable_flow(receipt)}


def build_gate_receipt(
    *,
    image_reference: str,
    image_contract: Mapping[str, object],
    nonroot_mode: str,
    nonroot_proof: Mapping[str, object],
    flows: Sequence[Mapping[str, object]],
    engine_user_override: str | None,
) -> dict[str, object]:
    """Build one hash-bound gate receipt after all subprocess proof is validated."""

    if len(flows) != 2 or [flow.get("invocation") for flow in flows] != [1, 2]:
        raise ContainerGateError("CONTAINER_SESSION_ISOLATION_INVALID")
    material: dict[str, object] = {
        "aws_calls": 0,
        "aws_mutations": 0,
        "credential_environment_inherited": False,
        "engine_user_override": engine_user_override,
        "external_deployments": 0,
        "external_network_connections": 0,
        "flows": list(flows),
        "image": {"reference": image_reference, **dict(image_contract)},
        "nonroot_proof": {"mode": nonroot_mode, **dict(nonroot_proof)},
        "receipt_type": "AIOA_B5_CONTAINER_JUDGE_GATE",
        "remote_pushes": 0,
        "runtime_hardening": {
            "capabilities_dropped": "ALL",
            "host_ports_published": 0,
            "network": "none",
            "no_new_privileges": True,
            "read_only_rootfs": True,
            "shared_mounts": 0,
            "tmpfs": "/tmp:rw,nosuid,nodev,noexec,size=64m",
        },
        "schema_version": 1,
        "session_isolation": {
            "ephemeral_container_invocations": 2,
            "fresh_workspace_per_invocation": True,
            "run_auto_remove": True,
            "shared_state": False,
        },
        "status": "PASS",
    }
    canonical = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {**material, "receipt_sha256": hashlib.sha256(canonical).hexdigest()}


def _write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    resolved = path.resolve(strict=False)
    private_root = (ROOT / ".local").resolve(strict=False)
    if not resolved.is_relative_to(private_root):
        raise ContainerGateError("CONTAINER_GATE_OUTPUT_OUTSIDE_PRIVATE_ROOT")
    if path.is_symlink() or any(
        parent.is_symlink() for parent in path.parents if parent.exists()
    ):
        raise ContainerGateError("CONTAINER_GATE_OUTPUT_SYMLINK_FORBIDDEN")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        atomic_write_private_json(path, dict(receipt))
    except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
        raise ContainerGateError("CONTAINER_GATE_OUTPUT_UNAVAILABLE") from error


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine")
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--engine-run-arg", action="append", default=[])
    parser.add_argument("--user-override")
    parser.add_argument("--skip-engine-nonroot-probe", action="store_true")
    parser.add_argument("--nonroot-receipt", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        if _COMMIT.fullmatch(args.expected_source_commit) is None:
            raise ContainerGateError("CONTAINER_SOURCE_COMMIT_INVALID")
        if _IMAGE.fullmatch(args.image) is None:
            raise ContainerGateError("CONTAINER_IMAGE_REFERENCE_INVALID")
        engine = _resolve_engine(args.engine)
        image_contract = inspect_image(engine, args.image, args.expected_source_commit)
        use_external_proof = args.skip_engine_nonroot_probe or args.user_override is not None
        if use_external_proof:
            if args.nonroot_receipt is None:
                raise ContainerGateError("CONTAINER_NONROOT_RECEIPT_REQUIRED")
            nonroot_proof = _external_nonroot_proof(
                args.nonroot_receipt,
                image_contract,
                args.expected_source_commit,
            )
            nonroot_mode = "BOUND_EXTERNAL_OCI_RUNTIME"
        else:
            nonroot_proof = _engine_nonroot_probe(
                engine,
                args.image,
                args.engine_run_arg,
            )
            nonroot_mode = "ENGINE_DEFAULT_IMAGE_USER"
        flows = tuple(
            _run_portable_flow(
                engine,
                args.image,
                args.engine_run_arg,
                args.user_override,
                index,
            )
            for index in (1, 2)
        )
        receipt = build_gate_receipt(
            image_reference=args.image,
            image_contract=image_contract,
            nonroot_mode=nonroot_mode,
            nonroot_proof=nonroot_proof,
            flows=flows,
            engine_user_override=args.user_override,
        )
        _write_receipt(args.output, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except ContainerGateError as error:
        print(
            json.dumps(
                {
                    "aws_mutations": 0,
                    "external_deployments": 0,
                    "reason": error.reason,
                    "remote_pushes": 0,
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
