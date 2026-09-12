#!/usr/bin/env python3
"""Validate the legacy Day 15 operator-attestation evidence format.

This compatibility module never calls AWS. Its manually confirmed HMAC documents are
not deployment authority for the current G10 gate; ``run_g10_closure.py`` owns that
candidate-bound AWS-observation path. The repository-pinned trust policy, not a key
supplied alongside a legacy receipt, still decides which HMAC key is trusted.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.preflight_region import validate_judge_token_not_after  # noqa: E402
from scripts.day15.validate_template import (  # noqa: E402
    DEFAULT_TEMPLATE,
    TemplateFailure,
    canonical_json,
    compare_lambda_configuration_sha256,
    has_sam_transform,
    load_template,
)

DEFAULT_ARTIFACT: Final = ROOT / "dist" / "day15" / "aioa-lambda.zip"
DEFAULT_MANIFEST: Final = ROOT / "dist" / "day15" / "aioa-lambda.manifest.json"
DEFAULT_RENDERED_TEMPLATE: Final = ROOT / "dist" / "day15" / "rendered-template.yaml"
DEFAULT_RECEIPT: Final = ROOT / "dist" / "day15" / "external-preflight.json"
DEFAULT_TRUST_POLICY: Final = ROOT / "requirements" / "day15-external-trust-policy.json"
GENERATOR_PATH: Final = Path(__file__).absolute()
SHA256_LENGTH: Final = 64
MAX_PROTECTED_DOCUMENT_BYTES: Final = 65_536
ATTESTATION: Final = "AUTHORIZED_OPERATOR_CONFIRMS_READ_ONLY_EXTERNAL_PREFLIGHT"
PROVENANCE: Final = "REPOSITORY_PINNED_OPERATOR_HMAC_SHA256"
TRUST_ALGORITHM: Final = "HMAC-SHA256"
COST_NOTIFICATION_CURRENCY: Final = "USD"
COST_NOTIFICATION_THRESHOLDS: Final = (10, 25, 40)
EXPECTED_REGION: Final = "eu-central-1"
EXPECTED_SANDBOX_TAG_KEY: Final = "AIOACloudOpsSandbox"
EXPECTED_SANDBOX_TAG_VALUE: Final = "true"
EXPECTED_NOVA_PROFILE: Final = "eu.amazon.nova-2-lite-v1:0"
EXPECTED_DEPLOYMENT_PROFILE: Final = "aioa-day15-deployer"
EXPECTED_DEPLOYMENT_ROLE_LEAF: Final = "AIOANonZeroCloudOpsDay15DeploymentRole"
EXPECTED_STACK_NAME: Final = "aioa-nonzero-cloudops-day15"
EXPECTED_CHANGE_SET_NAME: Final = "day15-reviewed-release"
EXPECTED_ARTIFACT_PREFIX: Final = "day15/reviewed/"

# Every item is an explicit operator confirmation. None is inferred from another flag.
CHECK_NAMES: Final = (
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
EXTERNAL_IDENTITY_NAMES: Final = (
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
BINDING_NAMES: Final = frozenset(
    {
        "artifact_manifest_sha256",
        "artifact_sha256",
        "configuration_sha256",
        "generator_sha256",
        "judge_token_not_after_sha256",
        "rendered_template_sha256",
        "repository_commit_oid",
        "template_sha256",
    }
)
EXTERNAL_HASH_BINDING_NAMES: Final = frozenset(
    {*(f"{name}_sha256" for name in EXTERNAL_IDENTITY_NAMES), "raw_bindings_sha256"}
)
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
ACCOUNT_PATTERN: Final = re.compile(r"^[0-9]{12}$")
PROFILE_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")
ROLE_ARN_PATTERN: Final = re.compile(r"^arn:aws:iam::([0-9]{12}):role/[A-Za-z0-9+=,.@_/-]{1,512}$")
SECRET_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:secretsmanager:eu-central-1:([0-9]{12}):secret:[A-Za-z0-9/_+=.@-]{1,512}$"
)
SECRET_NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,512}$")
INSTANCE_PATTERN: Final = re.compile(r"^i-[0-9a-f]{8,17}$")
BUCKET_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
IPV4_LIKE_PATTERN: Final = re.compile(r"^[0-9]+(?:\.[0-9]+){3}$")


class AttestationFailure(RuntimeError):
    def __init__(self, reason: str, *, status: str = "FAIL") -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and SHA256_PATTERN.fullmatch(value) is not None
        and value != "0" * SHA256_LENGTH
    )


def _read_regular_file(path: Path, reason: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise AttestationFailure(reason, status="BLOCKED")
    try:
        return path.read_bytes()
    except OSError as error:
        raise AttestationFailure(reason, status="BLOCKED") from error


def _canonical_object(path: Path, reason: str) -> tuple[dict[str, object], bytes]:
    raw = _read_regular_file(path, reason)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AttestationFailure(reason) from error
    if not isinstance(value, dict) or raw != (canonical_json(value) + "\n").encode():
        raise AttestationFailure(reason)
    return value, raw


def _trusted_operator_policy(path: Path | None = None) -> tuple[str, str]:
    policy_path = DEFAULT_TRUST_POLICY if path is None else path
    policy, raw = _canonical_object(policy_path, "TRUSTED_OPERATOR_POLICY_REQUIRED")
    expected_keys = {
        "algorithm",
        "operator_hmac_key_sha256",
        "schema_version",
        "status",
    }
    if set(policy) != expected_keys or policy.get("schema_version") != 1:
        raise AttestationFailure("TRUSTED_OPERATOR_POLICY_INVALID")
    if policy.get("algorithm") != TRUST_ALGORITHM:
        raise AttestationFailure("TRUSTED_OPERATOR_POLICY_INVALID")
    status_value = policy.get("status")
    fingerprint = policy.get("operator_hmac_key_sha256")
    if status_value == "BLOCKED" and fingerprint is None:
        raise AttestationFailure(
            "TRUSTED_OPERATOR_FINGERPRINT_REQUIRED",
            status="BLOCKED",
        )
    if status_value != "PASS" or not _valid_sha256(fingerprint):
        raise AttestationFailure("TRUSTED_OPERATOR_POLICY_INVALID")
    assert isinstance(fingerprint, str)
    return fingerprint, _sha256(raw)


def _require_trusted_key(key: bytes, *, trust_policy: Path | None = None) -> tuple[str, str]:
    fingerprint, policy_sha256 = _trusted_operator_policy(trust_policy)
    if not hmac.compare_digest(_sha256(key), fingerprint):
        raise AttestationFailure("EXTERNAL_ATTESTATION_KEY_NOT_TRUSTED")
    return fingerprint, policy_sha256


def read_attestation_key(
    path: Path | None,
    *,
    trust_policy: Path | None = None,
) -> bytes:
    """Load a protected key and require the independently pinned fingerprint."""

    if path is None or path.is_symlink() or not path.is_file():
        raise AttestationFailure("EXTERNAL_ATTESTATION_KEY_REQUIRED", status="BLOCKED")
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise AttestationFailure("EXTERNAL_ATTESTATION_KEY_INSIDE_REPOSITORY")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        key = path.read_bytes()
    except OSError as error:
        raise AttestationFailure(
            "EXTERNAL_ATTESTATION_KEY_UNAVAILABLE", status="BLOCKED"
        ) from error
    if mode & 0o077:
        raise AttestationFailure("EXTERNAL_ATTESTATION_KEY_PERMISSIONS_UNSAFE")
    if not 32 <= len(key) <= 4_096:
        raise AttestationFailure("EXTERNAL_ATTESTATION_KEY_INVALID")
    _require_trusted_key(key, trust_policy=trust_policy)
    return key


def _read_protected_bindings(path: Path | None) -> tuple[dict[str, object], bytes]:
    if path is None or path.is_symlink() or not path.is_file():
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_REQUIRED", status="BLOCKED")
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_INSIDE_REPOSITORY")
    try:
        file_stat = path.stat()
        mode = stat.S_IMODE(file_stat.st_mode)
        if not stat.S_ISREG(file_stat.st_mode):
            raise AttestationFailure("EXTERNAL_RAW_BINDINGS_REQUIRED", status="BLOCKED")
        if mode != 0o600:
            raise AttestationFailure("EXTERNAL_RAW_BINDINGS_PERMISSIONS_UNSAFE")
        if file_stat.st_size > MAX_PROTECTED_DOCUMENT_BYTES:
            raise AttestationFailure("EXTERNAL_RAW_BINDINGS_TOO_LARGE")
        raw = path.read_bytes()
    except OSError as error:
        raise AttestationFailure(
            "EXTERNAL_RAW_BINDINGS_UNAVAILABLE",
            status="BLOCKED",
        ) from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_INVALID") from error
    if not isinstance(value, dict) or raw != (canonical_json(value) + "\n").encode():
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_INVALID")
    return value, raw


def _plain_identity(value: object) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 2_048 or value != value.strip():
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    return value


def _artifact_path_is_valid(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and value not in {".", ""}
        and all(part not in {"", ".", ".."} for part in path.parts)
        and len(value) <= 1_024
        and value.startswith(EXPECTED_ARTIFACT_PREFIX)
        and len(value) > len(EXPECTED_ARTIFACT_PREFIX)
    )


def _bucket_is_valid(value: str) -> bool:
    return (
        BUCKET_PATTERN.fullmatch(value) is not None
        and ".." not in value
        and ".-" not in value
        and "-." not in value
        and IPV4_LIKE_PATTERN.fullmatch(value) is None
    )


def _external_identities_are_valid(identities: Mapping[str, object]) -> bool:
    if set(identities) != set(EXTERNAL_IDENTITY_NAMES):
        return False
    values = {name: _plain_identity(identities.get(name)) for name in EXTERNAL_IDENTITY_NAMES}
    if any(value is None for value in values.values()):
        return False
    account = values["aws_account_id"]
    role_arn = values["deployment_role_arn"]
    secret_id = values["judge_secret_id"]
    assert account is not None and role_arn is not None and secret_id is not None
    role_match = ROLE_ARN_PATTERN.fullmatch(role_arn)
    secret_match = SECRET_ARN_PATTERN.fullmatch(secret_id)
    if ACCOUNT_PATTERN.fullmatch(account) is None or role_match is None:
        return False
    if role_match.group(1) != account:
        return False
    if secret_match is not None:
        if secret_match.group(1) != account:
            return False
    elif SECRET_NAME_PATTERN.fullmatch(secret_id) is None:
        return False
    return (
        PROFILE_PATTERN.fullmatch(str(values["deployment_profile"])) is not None
        and values["deployment_profile"] == EXPECTED_DEPLOYMENT_PROFILE
        and role_arn.rsplit("/", 1)[-1] == EXPECTED_DEPLOYMENT_ROLE_LEAF
        and _bucket_is_valid(str(values["artifact_bucket"]))
        and _artifact_path_is_valid(str(values["artifact_path"]))
        and values["stack_name"] == EXPECTED_STACK_NAME
        and values["change_set_name"] == EXPECTED_CHANGE_SET_NAME
        and INSTANCE_PATTERN.fullmatch(str(values["sandbox_instance_id"])) is not None
        and values["sandbox_region"] == EXPECTED_REGION
        and values["sandbox_tag_key"] == EXPECTED_SANDBOX_TAG_KEY
        and values["sandbox_tag_value"] == EXPECTED_SANDBOX_TAG_VALUE
        and values["nova_inference_profile_id"] == EXPECTED_NOVA_PROFILE
        and _valid_sha256(values["cloudwatch_evidence_digest"])
    )


def external_identity_bindings(path: Path | None) -> dict[str, str]:
    """Validate protected raw confirmations and return hash-only receipt bindings."""

    document, raw = _read_protected_bindings(path)
    if set(document) != {"checks", "identities", "schema_version"}:
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_SCHEMA_INVALID")
    if document.get("schema_version") != 2:
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_SCHEMA_INVALID")
    checks = document.get("checks")
    if not isinstance(checks, Mapping):
        raise AttestationFailure("EXTERNAL_PREFLIGHT_CONFIRMATIONS_REQUIRED", status="BLOCKED")
    missing_checks = set(CHECK_NAMES) - set(checks)
    if missing_checks or any(checks.get(name) != "PASS" for name in CHECK_NAMES):
        raise AttestationFailure("EXTERNAL_PREFLIGHT_CONFIRMATIONS_REQUIRED", status="BLOCKED")
    if set(checks) != set(CHECK_NAMES):
        raise AttestationFailure("EXTERNAL_RAW_BINDINGS_SCHEMA_INVALID")
    identities = document.get("identities")
    if not isinstance(identities, Mapping):
        raise AttestationFailure("EXTERNAL_IDENTITY_BINDINGS_REQUIRED", status="BLOCKED")
    if set(EXTERNAL_IDENTITY_NAMES) - set(identities):
        raise AttestationFailure("EXTERNAL_IDENTITY_BINDINGS_REQUIRED", status="BLOCKED")
    if not _external_identities_are_valid(identities):
        raise AttestationFailure("EXTERNAL_IDENTITY_BINDINGS_INVALID")
    result = {
        f"{name}_sha256": _sha256(str(identities[name]).encode("utf-8"))
        for name in EXTERNAL_IDENTITY_NAMES
    }
    result["raw_bindings_sha256"] = _sha256(raw)
    return result


def candidate_bindings(
    *,
    artifact: Path,
    manifest: Path,
    template: Path,
    rendered_template: Path,
    configuration_sha256: str,
    judge_token_not_after: str,
) -> dict[str, str]:
    """Bind an attestation to code, config, rendering, source commit, and expiry."""

    artifact_raw = _read_regular_file(artifact, "ATTESTATION_ARTIFACT_REQUIRED")
    manifest_model, manifest_raw = _canonical_object(
        manifest,
        "ATTESTATION_MANIFEST_REQUIRED",
    )
    try:
        template_model = load_template(template)
        rendered_model = load_template(rendered_template)
        digest_status, _, computed_digest = compare_lambda_configuration_sha256(
            template_model,
            configuration_sha256,
        )
    except TemplateFailure as error:
        raise AttestationFailure("ATTESTATION_TEMPLATE_INVALID") from error
    if digest_status != "PASS" or computed_digest != configuration_sha256:
        raise AttestationFailure("ATTESTATION_CONFIGURATION_DIGEST_MISMATCH")
    if has_sam_transform(rendered_model):
        raise AttestationFailure("ATTESTATION_RENDERED_TEMPLATE_REQUIRED", status="BLOCKED")
    artifact_sha256 = _sha256(artifact_raw)
    artifact_model = manifest_model.get("artifact")
    repository = manifest_model.get("repository")
    if (
        not isinstance(artifact_model, Mapping)
        or artifact_model.get("sha256") != artifact_sha256
        or not isinstance(repository, Mapping)
    ):
        raise AttestationFailure("ATTESTATION_MANIFEST_BINDING_INVALID")
    commit_oid = repository.get("commit_oid")
    if (
        not isinstance(commit_oid, str)
        or len(commit_oid) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in commit_oid)
    ):
        raise AttestationFailure("ATTESTATION_COMMIT_BINDING_INVALID")
    generator_raw = _read_regular_file(GENERATOR_PATH, "ATTESTATION_GENERATOR_UNAVAILABLE")
    return {
        "artifact_manifest_sha256": _sha256(manifest_raw),
        "artifact_sha256": artifact_sha256,
        "configuration_sha256": configuration_sha256,
        "generator_sha256": _sha256(generator_raw),
        "judge_token_not_after_sha256": _sha256(judge_token_not_after.encode()),
        "rendered_template_sha256": _sha256(canonical_json(rendered_model).encode()),
        "repository_commit_oid": commit_oid,
        "template_sha256": _sha256(canonical_json(template_model).encode()),
    }


def _candidate_bindings_are_valid(bindings: Mapping[str, object]) -> bool:
    if set(bindings) != BINDING_NAMES:
        return False
    for name, value in bindings.items():
        if name == "repository_commit_oid":
            if (
                not isinstance(value, str)
                or len(value) not in {40, 64}
                or any(character not in "0123456789abcdef" for character in value)
            ):
                return False
        elif not _valid_sha256(value):
            return False
    return True


def _external_hashes_are_valid(bindings: object) -> bool:
    return (
        isinstance(bindings, Mapping)
        and set(bindings) == EXTERNAL_HASH_BINDING_NAMES
        and all(_valid_sha256(value) for value in bindings.values())
    )


def _unsigned_receipt(
    bindings: Mapping[str, str],
    external_bindings: Mapping[str, str] | None = None,
    *,
    trusted_key_sha256: str | None = None,
    trust_policy_sha256: str | None = None,
) -> dict[str, object]:
    if not _candidate_bindings_are_valid(bindings):
        raise AttestationFailure("EXTERNAL_ATTESTATION_BINDINGS_INVALID")
    if not _external_hashes_are_valid(external_bindings):
        raise AttestationFailure("EXTERNAL_IDENTITY_HASH_BINDINGS_INVALID", status="BLOCKED")
    if not _valid_sha256(trusted_key_sha256) or not _valid_sha256(trust_policy_sha256):
        raise AttestationFailure("EXTERNAL_ATTESTATION_TRUST_BINDING_INVALID")
    assert external_bindings is not None
    return {
        "attestation": ATTESTATION,
        "bindings": dict(bindings),
        "checks": {name: "PASS" for name in CHECK_NAMES},
        "cost_notifications": {
            "currency": COST_NOTIFICATION_CURRENCY,
            "thresholds": list(COST_NOTIFICATION_THRESHOLDS),
        },
        "external_identity_bindings": dict(external_bindings),
        "provenance": PROVENANCE,
        "sanitized": True,
        "schema_version": 5,
        "trust": {
            "operator_hmac_key_sha256": trusted_key_sha256,
            "policy_sha256": trust_policy_sha256,
        },
    }


def create_receipt(
    bindings: Mapping[str, str],
    key: bytes,
    external_bindings: Mapping[str, str] | None = None,
    *,
    trust_policy: Path | None = None,
) -> dict[str, object]:
    trusted_key_sha256, trust_policy_sha256 = _require_trusted_key(
        key,
        trust_policy=trust_policy,
    )
    unsigned = _unsigned_receipt(
        bindings,
        external_bindings,
        trusted_key_sha256=trusted_key_sha256,
        trust_policy_sha256=trust_policy_sha256,
    )
    mac = hmac.new(key, canonical_json(unsigned).encode(), hashlib.sha256).hexdigest()
    return {**unsigned, "attestation_hmac_sha256": mac}


def validate_receipt(
    receipt: object,
    *,
    expected_bindings: Mapping[str, str],
    key: bytes,
    trust_policy: Path | None = None,
) -> None:
    if not isinstance(receipt, dict):
        raise AttestationFailure("EXTERNAL_ATTESTATION_SCHEMA_INVALID")
    trusted_key_sha256, trust_policy_sha256 = _require_trusted_key(
        key,
        trust_policy=trust_policy,
    )
    mac = receipt.get("attestation_hmac_sha256")
    external_bindings = receipt.get("external_identity_bindings")
    unsigned = {name: value for name, value in receipt.items() if name != "attestation_hmac_sha256"}
    expected_unsigned = _unsigned_receipt(
        expected_bindings,
        external_bindings if isinstance(external_bindings, Mapping) else None,
        trusted_key_sha256=trusted_key_sha256,
        trust_policy_sha256=trust_policy_sha256,
    )
    if unsigned != expected_unsigned or not _valid_sha256(mac):
        raise AttestationFailure("EXTERNAL_ATTESTATION_SCHEMA_OR_BINDING_INVALID")
    assert isinstance(mac, str)
    expected_mac = hmac.new(key, canonical_json(unsigned).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected_mac):
        raise AttestationFailure("EXTERNAL_ATTESTATION_AUTHENTICATION_FAILED")


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    if path.is_symlink():
        raise AttestationFailure("EXTERNAL_ATTESTATION_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="day15-attestation-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write((canonical_json(payload) + "\n").encode())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2, "BLOCKED": 3}.get(status, 1)


def _add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    for check_name in CHECK_NAMES:
        flags = [f"--confirm-{check_name.replace('_', '-')}"]
        if check_name == "nova_profile_access_ready":
            flags.append("--confirm-bedrock-access-ready")
        parser.add_argument(*flags, dest=f"confirm_{check_name}", action="store_true")
    # Parse the former coarse flag for a clear migration path, but never let one
    # assertion replace the separate create and read authority confirmations.
    parser.add_argument(
        "--confirm-artifact-bucket-ready",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--confirm-judge-secret-plan-ready",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--rendered-template", type=Path, default=DEFAULT_RENDERED_TEMPLATE)
    parser.add_argument("--configuration-sha256", required=True)
    parser.add_argument("--judge-token-not-after", required=True)
    parser.add_argument("--attestation-key-file", type=Path, required=True)
    parser.add_argument("--external-bindings-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    _add_confirmation_arguments(parser)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        missing = [name for name in CHECK_NAMES if not getattr(args, f"confirm_{name}")]
        if missing:
            raise AttestationFailure(
                "EXTERNAL_PREFLIGHT_CONFIRMATIONS_REQUIRED",
                status="BLOCKED",
            )
        expiry = validate_judge_token_not_after(
            args.judge_token_not_after,
            clock=lambda: datetime.now(UTC),
        )
        if expiry.status != "PASS":
            raise AttestationFailure(expiry.reasons[0], status=expiry.status)
        key = read_attestation_key(args.attestation_key_file)
        external_bindings = external_identity_bindings(args.external_bindings_file)
        bindings = candidate_bindings(
            artifact=args.artifact,
            manifest=args.manifest,
            template=args.template,
            rendered_template=args.rendered_template,
            configuration_sha256=args.configuration_sha256,
            judge_token_not_after=args.judge_token_not_after,
        )
        receipt = create_receipt(bindings, key, external_bindings)
        _atomic_write(args.output, receipt)
        payload: dict[str, object] = {
            "receipt_sha256": _sha256((canonical_json(receipt) + "\n").encode()),
            "status": "PASS",
        }
    except AttestationFailure as error:
        payload = {"reasons": [error.reason], "status": error.status}
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"DAY15_EXTERNAL_ATTESTATION {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
