#!/usr/bin/env python3
"""Run the candidate-bound Day 15 G10 AWS preflight without mutation.

The command first freezes and validates the exact local candidate. It calls AWS only
when a protected private contract supplies explicit operator authority. AWS results
are written to a mode-0600 private receipt; stdout and the optional sanitized receipt
contain hashes, booleans, operation names, and public-safe reason codes only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.g10_aws_preflight import (  # noqa: E402
    PRIVATE_CHECK_KEYS,
    READ_OPERATION_ALLOWLIST,
    ContractValidationError,
    PrivateObservationReceipt,
    observe_aws_preflight,
    validate_private_observation_receipt,
)
from scripts.day15.g10_candidate import (  # noqa: E402
    COMPONENT_KEYS,
    DEFAULT_P0_RESULT,
    DEFAULT_P1_RESULT,
    DEPLOYMENT_PROFILE,
    REGION,
    CandidateFailure,
    PrivateContractFailure,
    build_candidate_descriptor,
    derive_candidate_digest,
    load_private_contract,
)
from scripts.day15.validate_template import canonical_json  # noqa: E402

DEFAULT_PRIVATE_CONTRACT: Final = ROOT / ".aioa-private" / "day15-deployment-contract.json"
DEFAULT_PRIVATE_RECEIPT: Final = ROOT / ".aioa-private" / "day15-external-preflight.json"
DEFAULT_SANITIZED_RECEIPT: Final = ROOT / ".aioa-private" / "day15-g10-readiness.json"
EXPECTED_PROJECT_PROFILE: Final = DEPLOYMENT_PROFILE
SELECTION_SOURCES: Final = frozenset(
    {"PRIVATE_CONTRACT", "EXPLICIT_AWS_PROFILE", "UNIQUE_EXPLICIT_PROJECT_PROFILE"}
)
CHECK_KEYS: Final = PRIVATE_CHECK_KEYS
PREREQUISITE_FIELDS: Final = (
    ("AUTHORIZED_AWS_PROFILE_AND_ROLE", "authenticated_identity_match"),
    ("CORRECT_HACKATHON_AWS_ACCOUNT", "correct_account_binding"),
    ("EU_CENTRAL_1_DEPLOYMENT_REGION", "region_ready"),
    ("PACKAGING_BUCKET_AND_PATH", "packaging_bucket_ready"),
    ("JUDGE_TOKEN_SECRET", "judge_secret_ready"),
    ("PREEXISTING_SANDBOX_EC2", "sandbox_explicit_id_present"),
    ("EXACT_SANDBOX_TAG", "sandbox_read_only_verified"),
    ("SANDBOX_REGION", "sandbox_read_only_verified"),
    ("CLOUDWATCH_DATA", "cloudwatch_evidence_ready"),
    ("NOVA2_PROFILE_ACCESS", "nova2_profile_access"),
    ("BUDGET_NOTIFICATION_OWNERSHIP", "budget_notification_owner_ready"),
)
PUBLIC_BOOLEAN_FIELDS: Final = frozenset(
    {
        "authenticated_identity_match",
        "aws_calls_performed",
        "aws_state_changed",
        "budget_notification_owner_ready",
        "change_set_created",
        "cloudwatch_evidence_ready",
        "correct_account_binding",
        "deployment_authorized",
        "deployment_contract_selected",
        "external_prerequisites_pass",
        "judge_secret_ready",
        "multiple_ambiguous_profiles",
        "nova2_profile_access",
        "packaging_bucket_ready",
        "ready_for_change_set",
        "ready_for_deployment",
        "region_ready",
        "sandbox_explicit_id_present",
        "sandbox_read_only_verified",
        "sanitized",
    }
)
SANITIZED_KEYS: Final = frozenset(
    {
        "api_operations",
        "authenticated_identity_match",
        "aws_calls_performed",
        "aws_state_changed",
        "budget_notification_owner_ready",
        "candidate",
        "change_set_created",
        "cloudwatch_evidence_ready",
        "correct_account_binding",
        "deployment_authorized",
        "deployment_contract_selected",
        "external_prerequisites_pass",
        "judge_secret_ready",
        "missing_prerequisites",
        "multiple_ambiguous_profiles",
        "nova2_profile_access",
        "observed_at",
        "packaging_bucket_ready",
        "private_contract_sha256",
        "private_receipt_created",
        "private_receipt_sha256",
        "ready_for_change_set",
        "ready_for_deployment",
        "region_ready",
        "reasons",
        "region",
        "sandbox_explicit_id_present",
        "sandbox_read_only_verified",
        "sanitized",
        "schema_version",
        "selection_source",
        "status",
        "write_operations",
    }
)
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
ACCOUNT_PATTERN: Final = re.compile(r"(?<!\d)\d{12}(?!\d)")
ARN_PATTERN: Final = re.compile(r"\barn:aws(?:-[a-z]+)*:", re.IGNORECASE)
INSTANCE_PATTERN: Final = re.compile(r"\bi-[0-9a-f]{8,17}\b", re.IGNORECASE)
EMAIL_PATTERN: Final = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
IP_PATTERN: Final = re.compile(
    r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\."
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
)
ACCESS_KEY_PATTERN: Final = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


class SessionFactory(Protocol):
    def __call__(self, profile_name: str): ...


class ClosureFailure(RuntimeError):
    """A public-safe orchestration failure."""

    def __init__(
        self,
        reason: str,
        *,
        status: str = "FAIL",
        aws_calls_performed: bool = False,
    ) -> None:
        self.reason = reason
        self.status = status
        self.aws_calls_performed = aws_calls_performed
        super().__init__(reason)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _available_profiles() -> tuple[str, ...]:
    """Read local profile names only; this performs no authentication or network call."""

    try:
        import botocore.session

        profiles = botocore.session.get_session().available_profiles
    except Exception:
        return ()
    return tuple(sorted({item for item in profiles if isinstance(item, str) and item}))


def _environment_profiles(environment: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value.strip()
                for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")
                if (value := environment.get(name)) and value.strip()
            }
        )
    )


def selection_without_contract(
    *,
    environment: Mapping[str, str],
    configured_profiles: Sequence[str],
) -> tuple[str, bool]:
    """Classify non-secret selection evidence without selecting arbitrary authority."""

    explicit = _environment_profiles(environment)
    if len(explicit) > 1:
        return "NONE", True
    if len(explicit) == 1:
        return "EXPLICIT_AWS_PROFILE", False
    project_profiles = {
        profile for profile in configured_profiles if profile == EXPECTED_PROJECT_PROFILE
    }
    if len(project_profiles) == 1:
        return "UNIQUE_EXPLICIT_PROJECT_PROFILE", False
    return "NONE", len(project_profiles) > 1


def validate_contract_selection(
    contract: Mapping[str, object],
    *,
    environment: Mapping[str, str],
    configured_profiles: Sequence[str],
) -> str:
    profile = contract.get("selected_profile")
    source = contract.get("selection_source")
    if not isinstance(profile, str) or source not in SELECTION_SOURCES:
        raise ClosureFailure("OPERATOR_SELECTION_INVALID")
    explicit = _environment_profiles(environment)
    if source == "PRIVATE_CONTRACT":
        return source
    if source == "EXPLICIT_AWS_PROFILE":
        if len(explicit) != 1 or explicit[0] != profile:
            raise ClosureFailure("EXPLICIT_PROFILE_SELECTION_MISMATCH", status="BLOCKED")
        return source
    if explicit or profile != EXPECTED_PROJECT_PROFILE:
        raise ClosureFailure("PROJECT_PROFILE_SELECTION_AMBIGUOUS", status="BLOCKED")
    project_profiles = [item for item in configured_profiles if item == profile]
    if len(project_profiles) != 1:
        raise ClosureFailure("PROJECT_PROFILE_SELECTION_AMBIGUOUS", status="BLOCKED")
    return source


def _private_output_allowed(path: Path, *, root: Path) -> None:
    lexical = Path(os.path.abspath(path))
    lexical_root = Path(os.path.abspath(root))
    try:
        relative = lexical.relative_to(lexical_root)
    except ValueError:
        relative = None
    if relative is not None:
        if not relative.parts or relative.parts[0] != ".aioa-private":
            raise ClosureFailure("PRIVATE_RECEIPT_REPOSITORY_PATH_FORBIDDEN")
        try:
            tracked = subprocess.run(
                ("git", "ls-files", "--error-unmatch", "--", relative.as_posix()),
                cwd=lexical_root,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            ignored = subprocess.run(
                ("git", "check-ignore", "--quiet", "--no-index", "--", relative.as_posix()),
                cwd=lexical_root,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ClosureFailure("PRIVATE_RECEIPT_GIT_CHECK_FAILED") from error
        if tracked.returncode == 0 or ignored.returncode != 0:
            raise ClosureFailure("PRIVATE_RECEIPT_IGNORED_PATH_REQUIRED")
    current = lexical_root if relative is not None else Path(lexical.anchor)
    parts = relative.parts[:-1] if relative is not None else lexical.parts[1:-1]
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ClosureFailure("PRIVATE_RECEIPT_SYMLINK_FORBIDDEN")
    if lexical.is_symlink():
        raise ClosureFailure("PRIVATE_RECEIPT_SYMLINK_FORBIDDEN")


def _atomic_write(path: Path, payload: Mapping[str, object], *, mode: int) -> bytes:
    if path.is_symlink():
        raise ClosureFailure("RECEIPT_OUTPUT_SYMLINK_FORBIDDEN")
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == 0o600 and not parent_existed:
        os.chmod(path.parent, 0o700)
    raw = _canonical_bytes(payload)
    with tempfile.NamedTemporaryFile(
        prefix="day15-g10-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), mode)
        handle.write(raw)
    try:
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if temporary.exists():
            temporary.unlink()
    return raw


def _public_output_allowed(path: Path) -> None:
    lexical = Path(os.path.abspath(path))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ClosureFailure("SANITIZED_RECEIPT_SYMLINK_FORBIDDEN")


def _candidate_is_valid(candidate: object) -> bool:
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidate_digest",
        "components",
        "region",
        "schema_version",
        "source_commit",
    }:
        return False
    components = candidate.get("components")
    structurally_valid = (
        candidate.get("schema_version") == 1
        and candidate.get("region") == REGION
        and isinstance(candidate.get("source_commit"), str)
        and COMMIT_PATTERN.fullmatch(str(candidate["source_commit"])) is not None
        and isinstance(candidate.get("candidate_digest"), str)
        and SHA256_PATTERN.fullmatch(str(candidate["candidate_digest"])) is not None
        and isinstance(components, Mapping)
        and set(components) == COMPONENT_KEYS
        and all(
            isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None
            for value in components.values()
        )
    )
    if not structurally_valid:
        return False
    assert isinstance(components, Mapping)
    component_values = {str(key): str(value) for key, value in components.items()}
    try:
        expected = derive_candidate_digest(
            source_commit=str(candidate["source_commit"]),
            region=str(candidate["region"]),
            components=component_values,
        )
    except CandidateFailure:
        return False
    return candidate.get("candidate_digest") == expected


def _missing_prerequisites(payload: Mapping[str, object]) -> list[str]:
    return [name for name, field in PREREQUISITE_FIELDS if payload.get(field) is not True]


def _base_payload(
    candidate: Mapping[str, object],
    *,
    selection_source: str,
    multiple_ambiguous_profiles: bool,
) -> dict[str, object]:
    return {
        "api_operations": [],
        "authenticated_identity_match": False,
        "aws_calls_performed": False,
        "aws_state_changed": False,
        "budget_notification_owner_ready": False,
        "candidate": dict(candidate),
        "change_set_created": False,
        "cloudwatch_evidence_ready": False,
        "correct_account_binding": False,
        "deployment_authorized": False,
        "deployment_contract_selected": False,
        "external_prerequisites_pass": False,
        "judge_secret_ready": False,
        "missing_prerequisites": [],
        "multiple_ambiguous_profiles": multiple_ambiguous_profiles,
        "nova2_profile_access": False,
        "observed_at": None,
        "packaging_bucket_ready": False,
        "private_contract_sha256": None,
        "private_receipt_created": False,
        "private_receipt_sha256": None,
        "ready_for_change_set": False,
        "ready_for_deployment": False,
        "region_ready": False,
        "reasons": [],
        "region": REGION,
        "sandbox_explicit_id_present": False,
        "sandbox_read_only_verified": False,
        "sanitized": True,
        "schema_version": 1,
        "selection_source": selection_source,
        "status": "BLOCKED",
        "write_operations": [],
    }


def blocked_receipt(
    candidate: Mapping[str, object],
    *,
    reason: str,
    selection_source: str,
    multiple_ambiguous_profiles: bool,
) -> dict[str, object]:
    payload = _base_payload(
        candidate,
        selection_source=selection_source,
        multiple_ambiguous_profiles=multiple_ambiguous_profiles,
    )
    payload["reasons"] = [reason]
    payload["missing_prerequisites"] = _missing_prerequisites(payload)
    return payload


def sanitized_receipt(
    candidate: Mapping[str, object],
    contract: Mapping[str, object],
    private_receipt: PrivateObservationReceipt,
    *,
    selection_source: str,
) -> dict[str, object]:
    private = private_receipt.private_mapping()
    try:
        validate_private_observation_receipt(private, expected_candidate=candidate)
    except ContractValidationError as error:
        raise ClosureFailure(error.reason) from error
    checks = private.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != CHECK_KEYS:
        raise ClosureFailure("PRIVATE_RECEIPT_CHECKS_INVALID")
    private_raw = _canonical_bytes(private)
    contract_raw = _canonical_bytes(contract)
    operations = [
        item.get("operation")
        for item in private.get("call_ledger", [])
        if isinstance(item, Mapping)
    ]
    if any(operation not in READ_OPERATION_ALLOWLIST for operation in operations):
        raise ClosureFailure("PRIVATE_RECEIPT_OPERATION_INVALID")
    payload = _base_payload(
        candidate,
        selection_source=selection_source,
        multiple_ambiguous_profiles=False,
    )
    payload.update(
        {
            **{name: checks[name] for name in CHECK_KEYS},
            "api_operations": operations,
            "authenticated_identity_match": checks["authenticated_identity_match"],
            "aws_calls_performed": bool(operations),
            "correct_account_binding": checks["authenticated_identity_match"],
            "deployment_contract_selected": True,
            "external_prerequisites_pass": private.get("external_prerequisites_pass") is True,
            "observed_at": private.get("observed_at"),
            "private_contract_sha256": _sha256(contract_raw),
            "private_receipt_created": True,
            "private_receipt_sha256": _sha256(private_raw),
            "reasons": list(private_receipt.reasons),
            "region_ready": True,
            "sandbox_explicit_id_present": True,
            "status": private_receipt.status,
        }
    )
    payload["missing_prerequisites"] = _missing_prerequisites(payload)
    passed = (
        payload["external_prerequisites_pass"] is True
        and not payload["missing_prerequisites"]
        and not payload["reasons"]
        and payload["status"] == "PASS"
    )
    payload["ready_for_change_set"] = passed
    if not passed:
        payload["external_prerequisites_pass"] = False
        payload["status"] = "BLOCKED"
    return payload


def _contains_sensitive_value(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_sensitive_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_sensitive_value(item) for item in value)
    if not isinstance(value, str):
        return False
    if SHA256_PATTERN.fullmatch(value) or COMMIT_PATTERN.fullmatch(value):
        return False
    return any(
        pattern.search(value)
        for pattern in (
            ACCOUNT_PATTERN,
            ARN_PATTERN,
            INSTANCE_PATTERN,
            EMAIL_PATTERN,
            IP_PATTERN,
            ACCESS_KEY_PATTERN,
        )
    )


def validate_sanitized_receipt(
    receipt: object,
    *,
    expected_candidate: Mapping[str, object],
    private_receipt: Mapping[str, object] | None,
    validation_time: datetime | None = None,
) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != SANITIZED_KEYS:
        raise ClosureFailure("SANITIZED_RECEIPT_SCHEMA_INVALID")
    if receipt.get("schema_version") != 1 or receipt.get("sanitized") is not True:
        raise ClosureFailure("SANITIZED_RECEIPT_SCHEMA_INVALID")
    if (
        not _candidate_is_valid(expected_candidate)
        or receipt.get("candidate") != expected_candidate
    ):
        raise ClosureFailure("SANITIZED_RECEIPT_CANDIDATE_MISMATCH")
    if receipt.get("region") != REGION or any(
        type(receipt.get(name)) is not bool for name in PUBLIC_BOOLEAN_FIELDS
    ):
        raise ClosureFailure("SANITIZED_RECEIPT_SCHEMA_INVALID")
    if receipt.get("selection_source") not in {*SELECTION_SOURCES, "NONE"}:
        raise ClosureFailure("SANITIZED_RECEIPT_SELECTION_INVALID")
    observed_at = receipt.get("observed_at")
    if observed_at is not None and (
        not isinstance(observed_at, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", observed_at) is None
    ):
        raise ClosureFailure("SANITIZED_RECEIPT_OBSERVATION_TIME_INVALID")
    operations = receipt.get("api_operations")
    if (
        not isinstance(operations, list)
        or any(operation not in READ_OPERATION_ALLOWLIST for operation in operations)
        or receipt.get("write_operations") != []
        or receipt.get("aws_state_changed") is not False
        or receipt.get("change_set_created") is not False
        or receipt.get("deployment_authorized") is not False
        or receipt.get("ready_for_deployment") is not False
    ):
        raise ClosureFailure("SANITIZED_RECEIPT_OPERATION_BOUNDARY_INVALID")
    if _contains_sensitive_value(receipt):
        raise ClosureFailure("SANITIZED_RECEIPT_SENSITIVE_VALUE_FORBIDDEN")
    expected_missing = _missing_prerequisites(receipt)
    if receipt.get("missing_prerequisites") != expected_missing:
        raise ClosureFailure("SANITIZED_RECEIPT_PREREQUISITES_INVALID")
    reasons = receipt.get("reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) or not reason or len(reason) > 160 for reason in reasons
    ):
        raise ClosureFailure("SANITIZED_RECEIPT_REASONS_INVALID")
    if private_receipt is None:
        if (
            receipt.get("private_receipt_created") is not False
            or receipt.get("private_receipt_sha256") is not None
            or receipt.get("private_contract_sha256") is not None
            or receipt.get("status") != "BLOCKED"
            or receipt.get("external_prerequisites_pass") is not False
            or receipt.get("ready_for_change_set") is not False
            or operations
        ):
            raise ClosureFailure("SANITIZED_RECEIPT_PRIVATE_BINDING_INVALID")
        return
    try:
        validate_private_observation_receipt(
            private_receipt,
            expected_candidate=expected_candidate,
            validation_time=validation_time,
        )
    except ContractValidationError as error:
        raise ClosureFailure(error.reason) from error
    if receipt.get("private_receipt_created") is not True:
        raise ClosureFailure("SANITIZED_RECEIPT_PRIVATE_BINDING_INVALID")
    if receipt.get("private_receipt_sha256") != _sha256(_canonical_bytes(private_receipt)):
        raise ClosureFailure("SANITIZED_RECEIPT_PRIVATE_BINDING_INVALID")
    private_contract = private_receipt.get("private_contract")
    if not isinstance(private_contract, Mapping) or receipt.get(
        "private_contract_sha256"
    ) != _sha256(_canonical_bytes(private_contract)):
        raise ClosureFailure("SANITIZED_RECEIPT_PRIVATE_BINDING_INVALID")
    private_candidate = private_receipt.get("candidate")
    descriptor = (
        private_candidate.get("descriptor") if isinstance(private_candidate, Mapping) else None
    )
    if descriptor != expected_candidate:
        raise ClosureFailure("SANITIZED_RECEIPT_CANDIDATE_MISMATCH")
    checks = private_receipt.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != CHECK_KEYS:
        raise ClosureFailure("SANITIZED_RECEIPT_PRIVATE_BINDING_INVALID")
    for name in CHECK_KEYS:
        if receipt.get(name) is not checks.get(name):
            raise ClosureFailure("SANITIZED_RECEIPT_CHECK_BINDING_INVALID")
    private_operations = [
        item.get("operation")
        for item in private_receipt.get("call_ledger", [])
        if isinstance(item, Mapping)
    ]
    if operations != private_operations or private_receipt.get("write_operations") != []:
        raise ClosureFailure("SANITIZED_RECEIPT_OPERATION_BOUNDARY_INVALID")
    passed = (
        private_receipt.get("status") == "PASS"
        and private_receipt.get("external_prerequisites_pass") is True
        and all(checks.values())
        and not reasons
        and not expected_missing
    )
    if (
        receipt.get("status") != ("PASS" if passed else "BLOCKED")
        or receipt.get("external_prerequisites_pass") is not passed
        or receipt.get("ready_for_change_set") is not passed
    ):
        raise ClosureFailure("SANITIZED_RECEIPT_STATUS_INVALID")


def _default_session_factory(profile_name: str):
    import boto3

    return boto3.Session(profile_name=profile_name, region_name=REGION)


def refresh_full_gate_results(
    *,
    p0_result_path: Path = DEFAULT_P0_RESULT,
    p1_result_path: Path = DEFAULT_P1_RESULT,
) -> None:
    """Execute the full P0/P1 matrices and persist canonical private result documents."""

    environment = dict(os.environ)
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
    ):
        environment.pop(name, None)
    environment["AWS_EC2_METADATA_DISABLED"] = "true"
    for script, output, expected_count in (
        (ROOT / "scripts" / "run_p0_gate.py", p0_result_path, 15),
        (ROOT / "scripts" / "run_p1_gate.py", p1_result_path, 6),
    ):
        try:
            completed = subprocess.run(
                (sys.executable, str(script), "--json"),
                cwd=ROOT,
                env=environment,
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1_800,
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            raise ClosureFailure("FULL_LOCAL_GATE_EXECUTION_FAILED") from error
        if (
            completed.returncode != 0
            or not isinstance(payload, dict)
            or payload.get("status") != "PASS"
            or payload.get("gate_count") != expected_count
            or payload.get("gates_pass") != expected_count
            or payload.get("gates_fail") != 0
            or payload.get("gates_skipped") != 0
        ):
            raise ClosureFailure("FULL_LOCAL_GATE_EXECUTION_FAILED")
        _private_output_allowed(output, root=ROOT)
        _atomic_write(output, payload, mode=0o600)


def run_closure(
    *,
    private_contract_path: Path = DEFAULT_PRIVATE_CONTRACT,
    private_receipt_path: Path = DEFAULT_PRIVATE_RECEIPT,
    sanitized_receipt_path: Path | None = DEFAULT_SANITIZED_RECEIPT,
    environment: Mapping[str, str] = os.environ,
    configured_profiles: Sequence[str] | None = None,
    session_factory: SessionFactory = _default_session_factory,
    candidate_factory: Callable[[], dict[str, object]] = build_candidate_descriptor,
) -> dict[str, object]:
    """Run G10 once, returning only a validated public-safe receipt."""

    try:
        candidate = candidate_factory()
    except CandidateFailure as error:
        raise ClosureFailure(error.reason) from error
    profiles = (
        tuple(configured_profiles) if configured_profiles is not None else _available_profiles()
    )
    _private_output_allowed(private_receipt_path, root=ROOT)
    if sanitized_receipt_path is not None:
        _public_output_allowed(sanitized_receipt_path)
    fallback_source, ambiguous = selection_without_contract(
        environment=environment,
        configured_profiles=profiles,
    )
    try:
        contract = load_private_contract(
            private_contract_path,
            expected_candidate_digest=str(candidate["candidate_digest"]),
            root=ROOT,
        )
    except PrivateContractFailure as error:
        status = "BLOCKED" if error.reason == "PRIVATE_CONTRACT_UNAVAILABLE" else "FAIL"
        if status == "FAIL":
            raise ClosureFailure(error.reason) from error
        reason = (
            "MULTIPLE_AMBIGUOUS_PROFILES" if ambiguous else "PRIVATE_DEPLOYMENT_CONTRACT_REQUIRED"
        )
        payload = blocked_receipt(
            candidate,
            reason=reason,
            selection_source=fallback_source,
            multiple_ambiguous_profiles=ambiguous,
        )
        validate_sanitized_receipt(payload, expected_candidate=candidate, private_receipt=None)
        if sanitized_receipt_path is not None:
            _atomic_write(sanitized_receipt_path, payload, mode=0o644)
        return payload

    source = validate_contract_selection(
        contract,
        environment=environment,
        configured_profiles=profiles,
    )
    try:
        session = session_factory(str(contract["selected_profile"]))
    except Exception as error:
        raise ClosureFailure("SELECTED_AWS_PROFILE_UNAVAILABLE", status="BLOCKED") from error
    try:
        observed = observe_aws_preflight(
            session=session,
            private_contract=contract,
            candidate_descriptor=candidate,
            candidate_digest=str(candidate["candidate_digest"]),
        )
    except ContractValidationError as error:
        raise ClosureFailure(error.reason) from error
    aws_calls_performed = bool(observed.call_ledger)
    try:
        private_mapping = observed.private_mapping()
        private_raw = _atomic_write(private_receipt_path, private_mapping, mode=0o600)
        if stat.S_IMODE(private_receipt_path.stat().st_mode) != 0o600:
            raise ClosureFailure("PRIVATE_RECEIPT_MODE_INVALID")
        payload = sanitized_receipt(candidate, contract, observed, selection_source=source)
        if payload["private_receipt_sha256"] != _sha256(private_raw):
            raise ClosureFailure("PRIVATE_RECEIPT_WRITE_BINDING_INVALID")
        validate_sanitized_receipt(
            payload,
            expected_candidate=candidate,
            private_receipt=private_mapping,
        )
        if sanitized_receipt_path is not None:
            _atomic_write(sanitized_receipt_path, payload, mode=0o644)
    except ClosureFailure as error:
        raise ClosureFailure(
            error.reason,
            status=error.status,
            aws_calls_performed=aws_calls_performed,
        ) from error
    except OSError as error:
        raise ClosureFailure(
            "RECEIPT_WRITE_FAILED",
            aws_calls_performed=aws_calls_performed,
        ) from error
    return payload


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-contract", type=Path, default=DEFAULT_PRIVATE_CONTRACT)
    parser.add_argument("--private-receipt", type=Path, default=DEFAULT_PRIVATE_RECEIPT)
    parser.add_argument("--sanitized-receipt", type=Path, default=DEFAULT_SANITIZED_RECEIPT)
    parser.add_argument(
        "--use-existing-gate-results",
        action="store_true",
        help="Use already-reviewed canonical P0/P1 result files instead of rerunning them.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if not args.use_existing_gate_results:
            refresh_full_gate_results()
        payload = run_closure(
            private_contract_path=args.private_contract,
            private_receipt_path=args.private_receipt,
            sanitized_receipt_path=args.sanitized_receipt,
        )
    except ClosureFailure as error:
        payload = {
            "aws_calls_performed": error.aws_calls_performed,
            "aws_state_changed": False,
            "reasons": [error.reason],
            "status": error.status,
        }
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"DAY15_G10_CLOSURE {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
