from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import scripts.run_b5_container_gate as gate

from aioa_cloudops_agent.config import ModelProviderName, RuntimeMode, RuntimeSettings
from aioa_cloudops_agent.persistence.local_integrity import atomic_write_private_json
from aioa_cloudops_agent.portable import run_portable_demo

COMMIT = "d18f945a1484a1255339a3b4bcb1560c58d06d9b"
IMAGE_ID = "1" * 64
DIGEST = f"sha256:{'2' * 64}"


def _image_document() -> dict[str, object]:
    return {
        "Architecture": "amd64",
        "Config": {
            "Entrypoint": ["python", "-m", "aioa_cloudops_agent.portable_server"],
            "Labels": {
                "org.opencontainers.image.licenses": "MIT",
                "org.opencontainers.image.revision": COMMIT,
            },
            "User": "aioa",
        },
        "Digest": DIGEST,
        "Id": IMAGE_ID,
        "Os": "linux",
        "RepoDigests": [f"localhost/aioa-portable@{DIGEST}"],
        "Size": 123_456,
    }


def _image_contract() -> dict[str, object]:
    return {
        "architecture": "amd64",
        "configured_user": "aioa",
        "content_identity": DIGEST,
        "digest": DIGEST,
        "entrypoint": ["python", "-m", "aioa_cloudops_agent.portable_server"],
        "id": IMAGE_ID,
        "license": "MIT",
        "os": "linux",
        "size_bytes": 123_456,
        "source_commit": COMMIT,
    }


def _nonroot_receipt() -> dict[str, object]:
    return {
        "cap_eff": "0000000000000000",
        "effective_gid": 65532,
        "effective_uid": 65532,
        "groups": [65532],
        "health": {"mode": "mock", "service": "aioa-local-hitl", "status": "ok"},
        "image_digest": DIGEST,
        "image_id": IMAGE_ID,
        "no_new_privs": "1",
        "pid1": "python -m aioa_cloudops_agent.portable_server",
        "ready": {
            "process_status": "READY",
            "provider_status": "READY",
            "runtime": {
                "agent_framework": "strands-agents",
                "aws_calls_allowed": False,
                "external_network_allowed": False,
                "process_external_network_calls": 0,
                "process_provider_calls": 0,
                "process_sandbox_mutations": 0,
                "provider": "mock",
                "real_cloud_mutations_enabled": False,
                "runtime_mode": "portable",
            },
            "sandbox_status": "READY",
            "status": "ready",
        },
        "receipt_type": "AIOA_OCI_NONROOT_SERVER_PROOF",
        "schema_version": 1,
        "source_commit": COMMIT,
        "token_file": {"gid": 65532, "mode": "0o600", "uid": 65532},
    }


def test_image_inspection_requires_exact_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = subprocess.CompletedProcess(
        args=(),
        returncode=0,
        stdout=json.dumps([_image_document()]),
        stderr="",
    )
    monkeypatch.setattr(gate, "_run_command", lambda *_args, **_kwargs: result)

    assert gate.inspect_image("engine", "aioa-portable:test", COMMIT) == _image_contract()

    invalid = _image_document()
    invalid["Config"]["User"] = "root"
    result.stdout = json.dumps([invalid])
    with pytest.raises(gate.ContainerGateError, match="CONTAINER_IMAGE_CONFIG_INVALID"):
        gate.inspect_image("engine", "aioa-portable:test", COMMIT)


def test_external_nonroot_receipt_is_private_and_bound_to_image(tmp_path: Path) -> None:
    path = tmp_path / "nonroot.json"
    atomic_write_private_json(path, _nonroot_receipt())

    proof = gate._external_nonroot_proof(path, _image_contract(), COMMIT)

    assert proof["effective_uid"] == proof["effective_gid"] == 65532
    assert proof["cap_eff"] == "0000000000000000"
    assert proof["no_new_privs"] == "1"
    tampered = _nonroot_receipt()
    tampered["image_id"] = "3" * 64
    atomic_write_private_json(path, tampered)
    with pytest.raises(gate.ContainerGateError, match="CONTAINER_NONROOT_RECEIPT_INVALID"):
        gate._external_nonroot_proof(path, _image_contract(), COMMIT)


def test_portable_flow_validator_covers_approve_deny_recovery_replay_and_binding(
    tmp_path: Path,
) -> None:
    receipt = run_portable_demo(
        settings=RuntimeSettings(
            mode=RuntimeMode.PORTABLE,
            model_provider=ModelProviderName.MOCK,
            aws_integration_enabled=False,
        ),
        workspace=tmp_path / "workspace",
    )

    summary = gate.validate_portable_flow(receipt)

    assert summary["approved_final_state"] == "SUCCESS_WITH_EVIDENCE"
    assert summary["approved_mock_mutations"] == 1
    assert summary["denied_final_state"] == "DENIED_BY_HUMAN"
    assert summary["denied_mock_mutations"] == 0
    assert summary["binding_tamper"] == "REJECTED_FAIL_CLOSED"
    assert summary["replay_mutation_delta"] == 0
    assert summary["recovery_reconciled"] is True
    invalid_approved = receipt.nonzero_verification.approved_path.model_copy(
        update={"replay_mutation_delta": 1}
    )
    invalid_verification = receipt.nonzero_verification.model_copy(
        update={"approved_path": invalid_approved}
    )
    invalid_receipt = receipt.model_copy(
        update={"nonzero_verification": invalid_verification}
    )
    with pytest.raises(gate.ContainerGateError, match="CONTAINER_JUDGE_FLOW_INVALID"):
        gate.validate_portable_flow(invalid_receipt)


def test_gate_receipt_binds_two_ephemeral_invocations_and_hardening() -> None:
    flows = (
        {"invocation": 1, "receipt_sha256": "a" * 64},
        {"invocation": 2, "receipt_sha256": "a" * 64},
    )
    receipt = gate.build_gate_receipt(
        image_reference="aioa-portable:test",
        image_contract=_image_contract(),
        nonroot_mode="ENGINE_DEFAULT_IMAGE_USER",
        nonroot_proof={"effective_uid": 65532},
        flows=flows,
        engine_user_override=None,
    )

    material = {name: value for name, value in receipt.items() if name != "receipt_sha256"}
    canonical = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert receipt["receipt_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert receipt["session_isolation"] == {
        "ephemeral_container_invocations": 2,
        "fresh_workspace_per_invocation": True,
        "run_auto_remove": True,
        "shared_state": False,
    }
    assert receipt["runtime_hardening"]["network"] == "none"
    with pytest.raises(gate.ContainerGateError, match="CONTAINER_SESSION_ISOLATION_INVALID"):
        gate.build_gate_receipt(
            image_reference="aioa-portable:test",
            image_contract=_image_contract(),
            nonroot_mode="ENGINE_DEFAULT_IMAGE_USER",
            nonroot_proof={"effective_uid": 65532},
            flows=flows[:1],
            engine_user_override=None,
        )


def test_engine_run_arguments_cannot_weaken_gate_isolation() -> None:
    command = gate._hardened_run_prefix(
        "/usr/bin/podman",
        ("--cgroups=disabled", "--log-driver=k8s-file"),
        "0:0",
    )

    assert command.count("--network") == 1
    assert "none" in command
    assert "--cap-drop" in command
    assert "--read-only" in command
    assert command[-2:] == ["--user", "0:0"]
    with pytest.raises(gate.ContainerGateError, match="CONTAINER_ENGINE_RUN_ARGUMENT_UNSAFE"):
        gate._hardened_run_prefix("/usr/bin/podman", ("--network=host",), None)
