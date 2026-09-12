from __future__ import annotations

import copy
import hashlib
import hmac
from pathlib import Path

import pytest
from scripts.day15 import external_preflight_attestation as attestation
from scripts.day15.validate_template import canonical_json


def _write_canonical(path: Path, value: object, *, mode: int = 0o600) -> Path:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _candidate_bindings() -> dict[str, str]:
    return {
        "artifact_manifest_sha256": "1" * 64,
        "artifact_sha256": "2" * 64,
        "configuration_sha256": "3" * 64,
        "generator_sha256": "4" * 64,
        "judge_token_not_after_sha256": "5" * 64,
        "rendered_template_sha256": "6" * 64,
        "repository_commit_oid": "7" * 40,
        "template_sha256": "8" * 64,
    }


def _raw_bindings() -> dict[str, object]:
    account = "".join(("123456", "789012"))
    return {
        "checks": {name: "PASS" for name in attestation.CHECK_NAMES},
        "identities": {
            "artifact_bucket": "aioa-day15-private-artifacts",
            "artifact_path": "day15/reviewed/aioa-lambda.zip",
            "aws_account_id": account,
            "change_set_name": "day15-reviewed-release",
            "cloudwatch_evidence_digest": hashlib.sha256(
                b"sanitized-read-only-cloudwatch-evidence"
            ).hexdigest(),
            "cost_notification_owner": "authorized.owner" + "@example.invalid",
            "deployment_profile": "aioa-day15-deployer",
            "deployment_role_arn": (
                f"arn:aws:iam::{account}:role/AIOANonZeroCloudOpsDay15DeploymentRole"
            ),
            "judge_secret_id": (
                f"arn:aws:secretsmanager:eu-central-1:{account}:secret:aioa-day15-judge"
            ),
            "nova_inference_profile_id": "eu.amazon.nova-2-lite-v1:0",
            "sandbox_instance_id": "i-" + ("a" * 17),
            "sandbox_region": "eu-central-1",
            "sandbox_tag_key": "AIOACloudOpsSandbox",
            "sandbox_tag_value": "true",
            "stack_name": "aioa-nonzero-cloudops-day15",
        },
        "schema_version": 2,
    }


def _trust_policy(path: Path, key: bytes) -> Path:
    return _write_canonical(
        path,
        {
            "algorithm": "HMAC-SHA256",
            "operator_hmac_key_sha256": hashlib.sha256(key).hexdigest(),
            "schema_version": 1,
            "status": "PASS",
        },
        mode=0o644,
    )


def _key_file(path: Path, key: bytes) -> Path:
    path.write_bytes(key)
    path.chmod(0o600)
    return path


def _trusted_receipt(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, str], bytes, Path]:
    raw_model = _raw_bindings()
    raw_path = _write_canonical(tmp_path / "external-bindings.json", raw_model)
    external_hashes = attestation.external_identity_bindings(raw_path)
    key = b"reviewed-operator-key-material-" + (b"x" * 32)
    policy = _trust_policy(tmp_path / "trust-policy.json", key)
    receipt = attestation.create_receipt(
        _candidate_bindings(),
        key,
        external_hashes,
        trust_policy=policy,
    )
    return receipt, raw_model, external_hashes, key, policy


def _resign(payload: dict[str, object], key: bytes) -> None:
    unsigned = {name: value for name, value in payload.items() if name != "attestation_hmac_sha256"}
    payload["attestation_hmac_sha256"] = hmac.new(
        key,
        canonical_json(unsigned).encode(),
        hashlib.sha256,
    ).hexdigest()


def test_external_contract_names_every_required_confirmation_and_identity() -> None:
    assert attestation.CHECK_NAMES == (
        "artifact_bucket_encryption_ready",
        "artifact_bucket_lifecycle_ready",
        "artifact_bucket_ownership_controls_ready",
        "artifact_bucket_public_access_block_ready",
        "artifact_bucket_tls_only_ready",
        "artifact_bucket_versioning_ready",
        "artifact_path_ready",
        "authorized_profile_ready",
        "authorized_role_ready",
        "cloudwatch_sufficient_data_ready",
        "correct_account_ready",
        "cost_notification_owned",
        "iam_capability_acknowledged",
        "judge_secret_create_ready",
        "judge_secret_read_ready",
        "nova_profile_access_ready",
        "sandbox_ebs_backed_ready",
        "sandbox_region_ready",
        "sandbox_running_ready",
        "sandbox_tag_ready",
        "sandbox_target_ready",
    )
    assert attestation.EXTERNAL_IDENTITY_NAMES == (
        "artifact_bucket",
        "artifact_path",
        "aws_account_id",
        "change_set_name",
        "cloudwatch_evidence_digest",
        "cost_notification_owner",
        "deployment_profile",
        "deployment_role_arn",
        "judge_secret_id",
        "nova_inference_profile_id",
        "sandbox_instance_id",
        "sandbox_region",
        "sandbox_tag_key",
        "sandbox_tag_value",
        "stack_name",
    )


def test_tracked_default_policy_is_truthfully_blocked_without_operator_fingerprint(
    tmp_path: Path,
) -> None:
    key_path = _key_file(tmp_path / "operator.key", b"k" * 32)

    with pytest.raises(attestation.AttestationFailure) as blocked:
        attestation.read_attestation_key(key_path)

    assert blocked.value.status == "BLOCKED"
    assert blocked.value.reason == "TRUSTED_OPERATOR_FINGERPRINT_REQUIRED"


def test_arbitrary_key_cannot_create_or_validate_receipt(tmp_path: Path) -> None:
    trusted_key = b"trusted-operator-key-material-" + (b"t" * 32)
    arbitrary_key = b"arbitrary-local-key-material-" + (b"a" * 32)
    policy = _trust_policy(tmp_path / "trust-policy.json", trusted_key)
    raw_path = _write_canonical(tmp_path / "external-bindings.json", _raw_bindings())
    external_hashes = attestation.external_identity_bindings(raw_path)

    with pytest.raises(attestation.AttestationFailure) as create_failure:
        attestation.create_receipt(
            _candidate_bindings(),
            arbitrary_key,
            external_hashes,
            trust_policy=policy,
        )
    assert create_failure.value.reason == "EXTERNAL_ATTESTATION_KEY_NOT_TRUSTED"

    trusted_receipt = attestation.create_receipt(
        _candidate_bindings(),
        trusted_key,
        external_hashes,
        trust_policy=policy,
    )
    with pytest.raises(attestation.AttestationFailure) as validate_failure:
        attestation.validate_receipt(
            trusted_receipt,
            expected_bindings=_candidate_bindings(),
            key=arbitrary_key,
            trust_policy=policy,
        )
    assert validate_failure.value.reason == "EXTERNAL_ATTESTATION_KEY_NOT_TRUSTED"


def test_protected_raw_bindings_require_exact_mode_closed_schema_and_cloudwatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe_mode = _write_canonical(
        tmp_path / "unsafe-mode.json",
        _raw_bindings(),
        mode=0o640,
    )
    with pytest.raises(attestation.AttestationFailure) as permissions:
        attestation.external_identity_bindings(unsafe_mode)
    assert permissions.value.reason == "EXTERNAL_RAW_BINDINGS_PERMISSIONS_UNSAFE"

    missing_cloudwatch = _raw_bindings()
    checks = missing_cloudwatch["checks"]
    assert isinstance(checks, dict)
    checks.pop("cloudwatch_sufficient_data_ready")
    missing_path = _write_canonical(tmp_path / "missing-cloudwatch.json", missing_cloudwatch)
    with pytest.raises(attestation.AttestationFailure) as missing:
        attestation.external_identity_bindings(missing_path)
    assert missing.value.status == "BLOCKED"
    assert missing.value.reason == "EXTERNAL_PREFLIGHT_CONFIRMATIONS_REQUIRED"

    missing_evidence = _raw_bindings()
    identities = missing_evidence["identities"]
    assert isinstance(identities, dict)
    identities.pop("cloudwatch_evidence_digest")
    evidence_path = _write_canonical(tmp_path / "missing-evidence.json", missing_evidence)
    with pytest.raises(attestation.AttestationFailure) as evidence:
        attestation.external_identity_bindings(evidence_path)
    assert evidence.value.status == "BLOCKED"
    assert evidence.value.reason == "EXTERNAL_IDENTITY_BINDINGS_REQUIRED"

    extra_field = _raw_bindings()
    extra_field["unreviewed"] = "PASS"
    extra_path = _write_canonical(tmp_path / "extra-field.json", extra_field)
    with pytest.raises(attestation.AttestationFailure) as schema:
        attestation.external_identity_bindings(extra_path)
    assert schema.value.reason == "EXTERNAL_RAW_BINDINGS_SCHEMA_INVALID"

    source = _write_canonical(tmp_path / "source.json", _raw_bindings())
    symlink = tmp_path / "bindings-link.json"
    symlink.symlink_to(source)
    with pytest.raises(attestation.AttestationFailure) as linked:
        attestation.external_identity_bindings(symlink)
    assert linked.value.reason == "EXTERNAL_RAW_BINDINGS_REQUIRED"

    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    inside = _write_canonical(repository_root / "inside.json", _raw_bindings())
    monkeypatch.setattr(attestation, "ROOT", repository_root)
    with pytest.raises(attestation.AttestationFailure) as repository_file:
        attestation.external_identity_bindings(inside)
    assert repository_file.value.reason == "EXTERNAL_RAW_BINDINGS_INSIDE_REPOSITORY"


def test_receipt_contains_only_hashes_for_external_identities(tmp_path: Path) -> None:
    receipt, raw_model, external_hashes, key, policy = _trusted_receipt(tmp_path)

    attestation.validate_receipt(
        receipt,
        expected_bindings=_candidate_bindings(),
        key=key,
        trust_policy=policy,
    )
    assert receipt["schema_version"] == 5
    assert receipt["external_identity_bindings"] == external_hashes
    assert set(receipt["checks"]) == set(attestation.CHECK_NAMES)
    assert all(value == "PASS" for value in receipt["checks"].values())
    assert all(
        isinstance(value, str) and attestation.SHA256_PATTERN.fullmatch(value)
        for value in external_hashes.values()
    )

    rendered = canonical_json(receipt)
    identities = raw_model["identities"]
    assert isinstance(identities, dict)
    sensitive_names = {
        "artifact_bucket",
        "artifact_path",
        "aws_account_id",
        "cost_notification_owner",
        "deployment_profile",
        "deployment_role_arn",
        "judge_secret_id",
        "sandbox_instance_id",
    }
    assert all(str(identities[name]) not in rendered for name in sensitive_names)


def test_tampering_and_resigned_schema_bypass_fail(tmp_path: Path) -> None:
    receipt, _, _, key, policy = _trusted_receipt(tmp_path)
    expected = _candidate_bindings()

    tampered = copy.deepcopy(receipt)
    hashes = tampered["external_identity_bindings"]
    assert isinstance(hashes, dict)
    hashes["artifact_bucket_sha256"] = "f" * 64
    with pytest.raises(attestation.AttestationFailure) as authentication:
        attestation.validate_receipt(
            tampered,
            expected_bindings=expected,
            key=key,
            trust_policy=policy,
        )
    assert authentication.value.reason == "EXTERNAL_ATTESTATION_AUTHENTICATION_FAILED"

    bypass = copy.deepcopy(receipt)
    bypass["unreviewed_field"] = "PASS"
    _resign(bypass, key)
    with pytest.raises(attestation.AttestationFailure) as schema:
        attestation.validate_receipt(
            bypass,
            expected_bindings=expected,
            key=key,
            trust_policy=policy,
        )
    assert schema.value.reason == "EXTERNAL_ATTESTATION_SCHEMA_OR_BINDING_INVALID"

    missing_cloudwatch = copy.deepcopy(receipt)
    checks = missing_cloudwatch["checks"]
    assert isinstance(checks, dict)
    checks.pop("cloudwatch_sufficient_data_ready")
    _resign(missing_cloudwatch, key)
    with pytest.raises(attestation.AttestationFailure) as missing:
        attestation.validate_receipt(
            missing_cloudwatch,
            expected_bindings=expected,
            key=key,
            trust_policy=policy,
        )
    assert missing.value.reason == "EXTERNAL_ATTESTATION_SCHEMA_OR_BINDING_INVALID"


def test_raw_identity_cross_bindings_and_sandbox_contract_fail_closed(tmp_path: Path) -> None:
    wrong_account = _raw_bindings()
    identities = wrong_account["identities"]
    assert isinstance(identities, dict)
    identities["aws_account_id"] = "2" * 12
    path = _write_canonical(tmp_path / "wrong-account.json", wrong_account)
    with pytest.raises(attestation.AttestationFailure) as account:
        attestation.external_identity_bindings(path)
    assert account.value.reason == "EXTERNAL_IDENTITY_BINDINGS_INVALID"

    wrong_region = _raw_bindings()
    identities = wrong_region["identities"]
    assert isinstance(identities, dict)
    identities["sandbox_region"] = "us-east-1"
    path = _write_canonical(tmp_path / "wrong-region.json", wrong_region)
    with pytest.raises(attestation.AttestationFailure) as region:
        attestation.external_identity_bindings(path)
    assert region.value.reason == "EXTERNAL_IDENTITY_BINDINGS_INVALID"

    wrong_tag = _raw_bindings()
    identities = wrong_tag["identities"]
    assert isinstance(identities, dict)
    identities["sandbox_tag_value"] = "false"
    path = _write_canonical(tmp_path / "wrong-tag.json", wrong_tag)
    with pytest.raises(attestation.AttestationFailure) as tag:
        attestation.external_identity_bindings(path)
    assert tag.value.reason == "EXTERNAL_IDENTITY_BINDINGS_INVALID"

    wrong_profile = _raw_bindings()
    identities = wrong_profile["identities"]
    assert isinstance(identities, dict)
    identities["deployment_profile"] = "ambient-default"
    path = _write_canonical(tmp_path / "wrong-profile.json", wrong_profile)
    with pytest.raises(attestation.AttestationFailure) as profile:
        attestation.external_identity_bindings(path)
    assert profile.value.reason == "EXTERNAL_IDENTITY_BINDINGS_INVALID"

    wrong_prefix = _raw_bindings()
    identities = wrong_prefix["identities"]
    assert isinstance(identities, dict)
    identities["artifact_path"] = "unreviewed/aioa-lambda.zip"
    path = _write_canonical(tmp_path / "wrong-prefix.json", wrong_prefix)
    with pytest.raises(attestation.AttestationFailure) as prefix:
        attestation.external_identity_bindings(path)
    assert prefix.value.reason == "EXTERNAL_IDENTITY_BINDINGS_INVALID"
