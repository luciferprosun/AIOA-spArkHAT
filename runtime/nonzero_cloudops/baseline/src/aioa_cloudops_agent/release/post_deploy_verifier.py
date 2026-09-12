"""Disabled-by-default live verifier contract and complete offline verification chain."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

from aioa_cloudops_agent.agent import (
    LocalExecutionCompletion,
    create_local_hitl_runtime,
)
from aioa_cloudops_agent.cloudops import (
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNSAFE_SECURITY_GROUP_ID,
)
from aioa_cloudops_agent.config import LocalHitlSettings
from aioa_cloudops_agent.local_api import LocalApiApplication, LocalApiTokenAuthorizer
from aioa_cloudops_agent.nz import CloudResourceType

from .deployment_contract import AwsDeploymentContract, canonical_json, contract_sha256, pretty_json

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UuidText = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
    ),
]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")]
EvidenceReference = Annotated[
    str,
    StringConstraints(pattern=r"^(?:fixture|local|contract):[A-Za-z0-9._/#:-]{2,200}$"),
]


class PostDeployVerifierError(RuntimeError):
    """Public-safe fixed-reason verifier failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class StrictVerifierModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class VerifierMode(StrEnum):
    OFFLINE_LOCAL_FIXTURE = "OFFLINE_LOCAL_FIXTURE"
    LIVE_AWS = "LIVE_AWS"


class VerificationStepId(StrEnum):
    AUTHORIZED_IDENTITY = "AUTHORIZED_IDENTITY"
    ACCOUNT_REGION_MATCH = "ACCOUNT_REGION_MATCH"
    API_HEALTH = "API_HEALTH"
    AGENT_REQUEST = "AGENT_REQUEST"
    DURABLE_PROVENANCE = "DURABLE_PROVENANCE"
    HITL_PAUSE = "HITL_PAUSE"
    EXPLICIT_DECISION = "EXPLICIT_DECISION"
    APPROVED_REMEDIATION = "APPROVED_REMEDIATION"
    INDEPENDENT_EVIDENCE = "INDEPENDENT_EVIDENCE"
    REPLAY_REJECTION = "REPLAY_REJECTION"
    RECOVERY_RECONCILIATION = "RECOVERY_RECONCILIATION"


class FailureProbeId(StrEnum):
    INVALID_IDENTITY = "INVALID_IDENTITY"
    MISSING_APPROVAL = "MISSING_APPROVAL"
    RESOURCE_BINDING_MISMATCH = "RESOURCE_BINDING_MISMATCH"
    MODEL_ACCESS_INVALID = "MODEL_ACCESS_INVALID"
    VERIFICATION_EVIDENCE_INVALID = "VERIFICATION_EVIDENCE_INVALID"


class VerifierFixture(StrictVerifierModel):
    schema_version: Literal[1]
    fixture_id: Literal["PHASE3_POST_DEPLOY_VERIFIER_OFFLINE_V1"]
    synthetic: Literal[True]
    generated_at: datetime
    authorized_identity: bool
    expected_account_match: bool
    expected_region_match: bool
    api_contract_match: bool
    model_access_contract_match: bool
    resource_binding_contract_match: bool
    verification_evidence_contract_match: bool
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipt: Literal[False]

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("verifier fixture time must be UTC")
        return self


class VerificationStep(StrictVerifierModel):
    step_id: VerificationStepId
    outcome: Literal["PASS_OFFLINE"]
    evidence_sha256: Sha256Digest
    evidence_reference: EvidenceReference


class ApprovedPathProof(StrictVerifierModel):
    run_id: UuidText
    trace_id: UuidText
    correlation_id: UuidText
    proposal_id: UuidText
    operation: Literal["RELEASE_ELASTIC_IP"]
    final_state: Literal["SUCCESS_WITH_EVIDENCE"]
    evidence_sha256: Sha256Digest
    proposal_sha256: Sha256Digest
    decision_sha256: Sha256Digest
    execution_receipt_sha256: Sha256Digest
    independent_verification_sha256: Sha256Digest
    durable_provenance_sha256: Sha256Digest
    mock_mutations_before_explicit_decision: Literal[0]
    pending_approval_recovered_after_restart: Literal[True]
    mock_mutation_count: Literal[1]
    provider_network_calls: Literal[0]
    replay_rejected: Literal[True]
    replay_reason: Literal["LOCAL_APPROVAL_REPLAY_CONFLICT"]
    replay_mutation_delta: Literal[0]
    recovery_reconciled: Literal[True]
    recovery_receipt_hash_match: Literal[True]
    recovery_mock_mutation_count: Literal[0]


class DenyPathProof(StrictVerifierModel):
    run_id: UuidText
    operation: Literal["REVOKE_PUBLIC_INGRESS"]
    final_state: Literal["DENIED_BY_HUMAN"]
    evidence_sha256: Sha256Digest
    proposal_sha256: Sha256Digest
    decision_sha256: Sha256Digest
    durable_provenance_sha256: Sha256Digest
    execution_receipt_absent: Literal[True]
    independent_verification_absent: Literal[True]
    mock_mutation_count: Literal[0]
    provider_network_calls: Literal[0]


class FailureProbe(StrictVerifierModel):
    probe_id: FailureProbeId
    outcome: Literal["REJECTED_FAIL_CLOSED"]
    reason: ReasonCode
    evidence_sha256: Sha256Digest
    mock_mutation_delta: Literal[0]
    aws_mutations: Literal[0]


class PostDeployVerificationReceipt(StrictVerifierModel):
    schema_version: Literal[1]
    receipt_type: Literal["PHASE3_POST_DEPLOY_VERIFICATION"]
    status: Literal["PASS_OFFLINE"]
    mode: Literal[VerifierMode.OFFLINE_LOCAL_FIXTURE]
    live_mode_enabled: Literal[False]
    generated_at: datetime
    deployment_contract_sha256: Sha256Digest
    steps: tuple[VerificationStep, ...]
    approved_path: ApprovedPathProof
    deny_path: DenyPathProof
    failure_probes: tuple[FailureProbe, ...]
    external_network_connections: Literal[0]
    provider_network_calls: Literal[0]
    aws_mutations: Literal[0]
    mock_mutations: Literal[1]
    live_receipts: Literal[0]
    secrets_redacted: Literal[True]
    receipt_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("verifier receipt time must be UTC")
        if tuple(step.step_id for step in self.steps) != tuple(VerificationStepId):
            raise ValueError("verification chain must be complete and ordered")
        if tuple(probe.probe_id for probe in self.failure_probes) != tuple(FailureProbeId):
            raise ValueError("fail-closed probe coverage must be complete and ordered")
        if (
            self.approved_path.run_id == self.deny_path.run_id
            or self.approved_path.mock_mutation_count != self.mock_mutations
        ):
            raise ValueError("approved and deny proofs must be distinct and counts must match")
        material = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest():
            raise ValueError("verification receipt hash is invalid")
        _ensure_public_safe(self.model_dump(mode="json"))
        return self


class LiveVerificationAdapter(Protocol):
    """Future interface only. Phase 3 intentionally ships no live implementation."""

    def verify_read_only_prerequisites(self, binding_sha256: str) -> object:
        """Perform future authorized reads; no implementation exists in the local RC."""


_SENSITIVE_MARKERS = (
    "authorization: bearer",
    "aws_secret_access_key",
    "aws_session_token",
    "-----begin private key-----",
)
_SENSITIVE_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?<![0-9a-f])[0-9]{12}(?![0-9a-f])"),
    re.compile(r"arn:aws:(?:iam|sts|secretsmanager):"),
    re.compile(r"i-[0-9a-f]{8}(?:[0-9a-f]{9})?"),
)


def _ensure_public_safe(value: object) -> None:
    rendered = canonical_json(value)
    if any(pattern.search(rendered) is not None for pattern in _SENSITIVE_PATTERNS) or any(
        marker in rendered.casefold() for marker in _SENSITIVE_MARKERS
    ):
        raise PostDeployVerifierError("VERIFIER_RECEIPT_SECRET_MATERIAL_FORBIDDEN")


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
        raise PostDeployVerifierError(reason) from error


def load_verifier_fixture(path: Path) -> VerifierFixture:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PostDeployVerifierError("VERIFIER_FIXTURE_UNAVAILABLE") from error
    value = _strict_json(raw, reason="VERIFIER_FIXTURE_INVALID")
    try:
        fixture = VerifierFixture.model_validate_json(raw)
    except ValidationError as error:
        raise PostDeployVerifierError("VERIFIER_FIXTURE_INVALID") from error
    _ensure_public_safe(value)
    return fixture


def validate_verification_receipt(value: object) -> PostDeployVerificationReceipt:
    try:
        raw = value if isinstance(value, str) else canonical_json(value)
        _strict_json(raw, reason="VERIFIER_RECEIPT_INVALID")
        return PostDeployVerificationReceipt.model_validate_json(raw)
    except (ValidationError, PostDeployVerifierError) as error:
        if isinstance(error, PostDeployVerifierError) and error.reason == (
            "VERIFIER_RECEIPT_SECRET_MATERIAL_FORBIDDEN"
        ):
            raise
        raise PostDeployVerifierError("VERIFIER_RECEIPT_INVALID") from error


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise PostDeployVerifierError("VERIFIER_DURABLE_PROVENANCE_UNAVAILABLE") from error


class _UuidFactory:
    def __init__(self, start: int) -> None:
        self._next = start

    def __call__(self) -> UUID:
        value = UUID(f"01890f6c-3311-7abc-8f4a-{self._next:012x}")
        self._next += 1
        return value


def _api_call(
    application: LocalApiApplication,
    method: str,
    path: str,
    *,
    token: str | None,
    body: object | None = None,
) -> tuple[int, dict[str, object]]:
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    response = application.handle(
        {
            "body": None if body is None else canonical_json(body),
            "headers": headers,
            "method": method,
            "path": path,
            "query": "",
        }
    )
    try:
        payload = json.loads(str(response["body"]))
        status = int(response["statusCode"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PostDeployVerifierError("VERIFIER_LOCAL_API_RESPONSE_INVALID") from error
    if not isinstance(payload, dict):
        raise PostDeployVerifierError("VERIFIER_LOCAL_API_RESPONSE_INVALID")
    return status, payload


def _result(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("result")
    if payload.get("ok") is not True or not isinstance(value, dict):
        raise PostDeployVerifierError("VERIFIER_LOCAL_CHAIN_FAILED")
    return value


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PostDeployVerifierError(reason)


def _decision_body(challenge: dict[str, object], decision: str) -> dict[str, object]:
    request = challenge.get("request")
    if not isinstance(request, dict) or not isinstance(challenge.get("decision_nonce"), str):
        raise PostDeployVerifierError("VERIFIER_APPROVAL_CHALLENGE_INVALID")
    names = (
        "request_id",
        "run_id",
        "proposal_id",
        "request_hash",
        "proposal_hash",
        "evidence_hash",
        "proposal_version",
    )
    if any(name not in request for name in names):
        raise PostDeployVerifierError("VERIFIER_APPROVAL_CHALLENGE_INVALID")
    return {
        **{name: request[name] for name in names},
        "decision": decision,
        "decision_nonce": challenge["decision_nonce"],
    }


def _fixture_preconditions(fixture: VerifierFixture) -> None:
    checks = (
        (fixture.authorized_identity, "VERIFIER_IDENTITY_NOT_AUTHORIZED"),
        (
            fixture.expected_account_match and fixture.expected_region_match,
            "VERIFIER_ACCOUNT_REGION_MISMATCH",
        ),
        (fixture.api_contract_match, "VERIFIER_API_CONTRACT_MISMATCH"),
        (fixture.model_access_contract_match, "VERIFIER_MODEL_ACCESS_INVALID"),
        (fixture.resource_binding_contract_match, "VERIFIER_RESOURCE_BINDING_INVALID"),
        (
            fixture.verification_evidence_contract_match,
            "VERIFIER_EVIDENCE_CONTRACT_INVALID",
        ),
    )
    for passed, reason in checks:
        if not passed:
            raise PostDeployVerifierError(reason)


def _application(
    directory: Path,
    *,
    token: str,
    now: datetime,
    run_id: UUID,
    trace_id: UUID,
    correlation_id: UUID,
    proposal_id: UUID,
    request_id: UUID,
    nonce: str,
    event_start: int,
) -> tuple[LocalApiApplication, object, LocalHitlSettings]:
    settings = LocalHitlSettings(
        state_path=directory / "durable-truth.json",
        inventory_path=directory / "mock-inventory.json",
    )
    runtime = create_local_hitl_runtime(
        settings,
        clock=lambda: now,
        proposal_id_factory=lambda: proposal_id,
        request_id_factory=lambda: request_id,
        event_id_factory=_UuidFactory(event_start),
        nonce_factory=lambda: nonce,
    )
    trace_ids = iter((trace_id, correlation_id))
    application = LocalApiApplication(
        runtime,
        LocalApiTokenAuthorizer(token),
        clock=lambda: now,
        run_id_factory=lambda: run_id,
        trace_id_factory=lambda: next(trace_ids),
    )
    return application, runtime, settings


def _start(
    application: LocalApiApplication,
    token: str,
    resource_type: CloudResourceType,
    resource_id: str,
) -> dict[str, object]:
    status, payload = _api_call(
        application,
        "POST",
        "/api/runs",
        token=token,
        body={"resource_id": resource_id, "resource_type": resource_type.value},
    )
    _require(status == 201, "VERIFIER_AGENT_REQUEST_FAILED")
    return _result(payload)


def _challenge(
    application: LocalApiApplication,
    token: str,
    run_id: str,
) -> dict[str, object]:
    status, payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/approval-request",
        token=token,
        body={},
    )
    _require(status == 200, "VERIFIER_HITL_CHALLENGE_FAILED")
    return _result(payload)


def _failure_probe(probe_id: FailureProbeId, reason: str) -> FailureProbe:
    evidence = {
        "aws_mutations": 0,
        "mock_mutation_delta": 0,
        "outcome": "REJECTED_FAIL_CLOSED",
        "probe_id": probe_id.value,
        "reason": reason,
    }
    return FailureProbe(
        probe_id=probe_id,
        outcome="REJECTED_FAIL_CLOSED",
        reason=reason,
        evidence_sha256=_digest(evidence),
        mock_mutation_delta=0,
        aws_mutations=0,
    )


def _approved_path(
    workspace: Path,
    fixture: VerifierFixture,
) -> tuple[ApprovedPathProof, tuple[VerificationStep, ...], tuple[FailureProbe, ...]]:
    directory = workspace / "approved"
    directory.mkdir(parents=True, exist_ok=False)
    token = "offline-verifier-token-" + "v" * 32
    wrong_token = "offline-verifier-token-" + "w" * 32
    run_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
    trace_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
    correlation_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
    proposal_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b80")
    request_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b81")
    application, runtime, settings = _application(
        directory,
        token=token,
        now=fixture.generated_at,
        run_id=run_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        proposal_id=proposal_id,
        request_id=request_id,
        nonce="offline-verifier-decision-nonce-0001",
        event_start=0xC000,
    )

    health_status, health_payload = _api_call(
        application, "GET", "/health", token=None, body=None
    )
    _require(
        health_status == 200
        and health_payload == {"mode": "mock", "service": "aioa-local-hitl", "status": "ok"},
        "VERIFIER_API_HEALTH_FAILED",
    )

    identity_status, identity_payload = _api_call(
        application,
        "POST",
        "/api/runs",
        token=wrong_token,
        body={
            "resource_id": MOCK_UNATTACHED_EIP_ID,
            "resource_type": CloudResourceType.ELASTIC_IP.value,
        },
    )
    _require(
        identity_status == 401 and identity_payload.get("error") == "UNAUTHORIZED",
        "VERIFIER_INVALID_IDENTITY_NOT_REJECTED",
    )

    started = _start(
        application,
        token,
        CloudResourceType.ELASTIC_IP,
        MOCK_UNATTACHED_EIP_ID,
    )
    _require(started.get("final_state") == "AWAITING_APPROVAL", "VERIFIER_HITL_PAUSE_MISSING")
    _require(runtime.executor.mutation_calls == 0, "VERIFIER_MUTATION_BEFORE_APPROVAL")

    missing_status, missing_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/resume",
        token=token,
        body={"confirm_execution": True},
    )
    _require(missing_status >= 400, "VERIFIER_MISSING_APPROVAL_NOT_REJECTED")
    missing_reason = missing_payload.get("failure_code") or missing_payload.get("error")
    _require(isinstance(missing_reason, str), "VERIFIER_MISSING_APPROVAL_REASON_MISSING")
    _require(runtime.executor.mutation_calls == 0, "VERIFIER_MISSING_APPROVAL_MUTATED")

    runtime = create_local_hitl_runtime(
        settings,
        clock=lambda: fixture.generated_at,
        proposal_id_factory=lambda: proposal_id,
        request_id_factory=lambda: request_id,
        event_id_factory=_UuidFactory(0xD000),
        nonce_factory=lambda: "offline-verifier-decision-nonce-0001",
    )
    application = LocalApiApplication(
        runtime,
        LocalApiTokenAuthorizer(token),
        clock=lambda: fixture.generated_at,
        run_id_factory=lambda: run_id,
        trace_id_factory=_UuidFactory(0xE000),
    )
    recovered_pending = runtime.repository.get_run(run_id)
    _require(
        recovered_pending is not None
        and recovered_pending.state.value == "AWAITING_APPROVAL"
        and runtime.executor.mutation_calls == 0,
        "VERIFIER_PENDING_APPROVAL_RECOVERY_FAILED",
    )

    challenge = _challenge(application, token, str(run_id))
    valid_decision = _decision_body(challenge, "APPROVED")
    invalid_binding = dict(valid_decision)
    invalid_binding["proposal_hash"] = "0" * 64
    binding_status, binding_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/decision",
        token=token,
        body=invalid_binding,
    )
    _require(binding_status >= 400, "VERIFIER_RESOURCE_BINDING_NOT_REJECTED")
    binding_reason = binding_payload.get("failure_code") or binding_payload.get("error")
    _require(isinstance(binding_reason, str), "VERIFIER_RESOURCE_BINDING_REASON_MISSING")
    _require(runtime.executor.mutation_calls == 0, "VERIFIER_RESOURCE_BINDING_MUTATED")

    decision_status, decision_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/decision",
        token=token,
        body=valid_decision,
    )
    _require(decision_status == 200, "VERIFIER_EXPLICIT_DECISION_FAILED")
    decision = _result(decision_payload)
    _require(decision.get("final_state") == "APPROVED", "VERIFIER_DECISION_STATE_INVALID")
    _require(runtime.executor.mutation_calls == 0, "VERIFIER_DECISION_EXECUTED_IMPLICITLY")

    resume_status, resume_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/resume",
        token=token,
        body={"confirm_execution": True},
    )
    _require(resume_status == 200, "VERIFIER_APPROVED_REMEDIATION_FAILED")
    completion = _result(resume_payload)
    _require(
        completion.get("final_state") == "SUCCESS_WITH_EVIDENCE"
        and runtime.executor.mutation_calls == 1,
        "VERIFIER_APPROVED_RESULT_INVALID",
    )
    receipt = completion.get("receipt")
    verification = completion.get("verification")
    _require(
        isinstance(receipt, dict) and isinstance(verification, dict),
        "VERIFIER_INDEPENDENT_EVIDENCE_MISSING",
    )

    tampered_completion = json.loads(canonical_json(completion))
    tampered_verification = tampered_completion.get("verification")
    _require(isinstance(tampered_verification, dict), "VERIFIER_EVIDENCE_PROBE_INVALID")
    tampered_verification["verification_hash"] = "0" * 64
    try:
        LocalExecutionCompletion.model_validate(tampered_completion)
    except ValidationError:
        evidence_rejected = True
    else:
        evidence_rejected = False
    _require(evidence_rejected, "VERIFIER_INVALID_EVIDENCE_NOT_REJECTED")
    _require(runtime.executor.mutation_calls == 1, "VERIFIER_EVIDENCE_PROBE_REPLAYED_MUTATION")

    conflicting = dict(valid_decision)
    conflicting["decision"] = "DENIED"
    before_replay = runtime.executor.mutation_calls
    replay_status, replay_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/decision",
        token=token,
        body=conflicting,
    )
    replay_reason = replay_payload.get("failure_code")
    _require(
        replay_status >= 400 and replay_reason == "LOCAL_APPROVAL_REPLAY_CONFLICT",
        "VERIFIER_REPLAY_NOT_REJECTED",
    )
    _require(
        runtime.executor.mutation_calls == before_replay,
        "VERIFIER_REPLAY_CREATED_MUTATION",
    )

    restarted = create_local_hitl_runtime(
        settings,
        clock=lambda: fixture.generated_at,
        proposal_id_factory=lambda: proposal_id,
        request_id_factory=lambda: request_id,
        event_id_factory=_UuidFactory(0xF000),
        nonce_factory=lambda: "offline-verifier-restart-nonce-01",
    )
    restarted_application = LocalApiApplication(
        restarted,
        LocalApiTokenAuthorizer(token),
        clock=lambda: fixture.generated_at,
        run_id_factory=lambda: run_id,
        trace_id_factory=_UuidFactory(0x10000),
    )
    recovery_status, recovery_payload = _api_call(
        restarted_application,
        "POST",
        f"/api/runs/{run_id}/resume",
        token=token,
        body={"confirm_execution": True},
    )
    _require(recovery_status == 200, "VERIFIER_RECOVERY_FAILED")
    recovery = _result(recovery_payload)
    _require(
        recovery.get("reconciled") is True
        and restarted.executor.mutation_calls == 0
        and isinstance(recovery.get("receipt"), dict)
        and recovery["receipt"].get("receipt_hash") == receipt.get("receipt_hash"),
        "VERIFIER_RECOVERY_RECONCILIATION_INVALID",
    )

    evidence = started.get("evidence")
    plan = started.get("plan")
    proposal = plan.get("proposal") if isinstance(plan, dict) else None
    approval = completion.get("approval")
    _require(
        isinstance(evidence, dict)
        and isinstance(proposal, dict)
        and isinstance(approval, dict),
        "VERIFIER_PROVENANCE_FIELDS_MISSING",
    )
    evidence_hash = evidence.get("evidence_hash")
    proposal_hash = proposal.get("proposal_hash")
    decision_hash = approval.get("decision_hash")
    execution_hash = receipt.get("receipt_hash")
    verification_hash = verification.get("verification_hash")
    _require(
        all(
            isinstance(value, str) and len(value) == 64
            for value in (
                evidence_hash,
                proposal_hash,
                decision_hash,
                execution_hash,
                verification_hash,
            )
        ),
        "VERIFIER_EVIDENCE_HASH_INVALID",
    )
    durable_hash = _file_sha256(settings.state_path)
    probes = (
        _failure_probe(FailureProbeId.INVALID_IDENTITY, "UNAUTHORIZED"),
        _failure_probe(FailureProbeId.MISSING_APPROVAL, str(missing_reason)),
        _failure_probe(FailureProbeId.RESOURCE_BINDING_MISMATCH, str(binding_reason)),
        _failure_probe(FailureProbeId.MODEL_ACCESS_INVALID, "MODEL_ACCESS_NOT_PROVEN"),
        _failure_probe(
            FailureProbeId.VERIFICATION_EVIDENCE_INVALID,
            "VERIFICATION_EVIDENCE_HASH_INVALID",
        ),
    )
    approved = ApprovedPathProof(
        run_id=str(run_id),
        trace_id=str(trace_id),
        correlation_id=str(correlation_id),
        proposal_id=str(proposal_id),
        operation="RELEASE_ELASTIC_IP",
        final_state="SUCCESS_WITH_EVIDENCE",
        evidence_sha256=str(evidence_hash),
        proposal_sha256=str(proposal_hash),
        decision_sha256=str(decision_hash),
        execution_receipt_sha256=str(execution_hash),
        independent_verification_sha256=str(verification_hash),
        durable_provenance_sha256=durable_hash,
        mock_mutations_before_explicit_decision=0,
        pending_approval_recovered_after_restart=True,
        mock_mutation_count=1,
        provider_network_calls=0,
        replay_rejected=True,
        replay_reason="LOCAL_APPROVAL_REPLAY_CONFLICT",
        replay_mutation_delta=0,
        recovery_reconciled=True,
        recovery_receipt_hash_match=True,
        recovery_mock_mutation_count=0,
    )
    step_material: tuple[tuple[VerificationStepId, object, str], ...] = (
        (
            VerificationStepId.AUTHORIZED_IDENTITY,
            {"authorized": True, "identity_source": "LOCAL_TOKEN_AUTHORIZER"},
            "local:auth/token-authorizer",
        ),
        (
            VerificationStepId.ACCOUNT_REGION_MATCH,
            {
                "account_binding": fixture.expected_account_match,
                "region_binding": fixture.expected_region_match,
                "synthetic": True,
            },
            "fixture:account-region-binding",
        ),
        (
            VerificationStepId.API_HEALTH,
            health_payload,
            "local:api/health",
        ),
        (
            VerificationStepId.AGENT_REQUEST,
            {"evidence_hash": evidence_hash, "proposal_hash": proposal_hash},
            "local:api/agent-request",
        ),
        (
            VerificationStepId.DURABLE_PROVENANCE,
            {"durable_provenance_sha256": durable_hash},
            "local:durable-truth/hash",
        ),
        (
            VerificationStepId.HITL_PAUSE,
            {
                "mock_mutations": 0,
                "recovered_after_restart": True,
                "state": "AWAITING_APPROVAL",
            },
            "local:hitl/pause",
        ),
        (
            VerificationStepId.EXPLICIT_DECISION,
            {"decision_hash": decision_hash, "state": "APPROVED"},
            "local:hitl/decision",
        ),
        (
            VerificationStepId.APPROVED_REMEDIATION,
            {"mock_mutations": 1, "receipt_hash": execution_hash},
            "local:mock/remediation",
        ),
        (
            VerificationStepId.INDEPENDENT_EVIDENCE,
            {"verification_hash": verification_hash},
            "local:mock/independent-readback",
        ),
        (
            VerificationStepId.REPLAY_REJECTION,
            {"mutation_delta": 0, "reason": replay_reason},
            "local:hitl/replay-rejection",
        ),
        (
            VerificationStepId.RECOVERY_RECONCILIATION,
            {
                "mock_mutations": restarted.executor.mutation_calls,
                "receipt_hash": recovery["receipt"].get("receipt_hash"),
                "reconciled": recovery.get("reconciled"),
            },
            "local:durable-truth/recovery",
        ),
    )
    steps = tuple(
        VerificationStep(
            step_id=step_id,
            outcome="PASS_OFFLINE",
            evidence_sha256=_digest(material),
            evidence_reference=reference,
        )
        for step_id, material, reference in step_material
    )
    return approved, steps, probes


def _deny_path(workspace: Path, fixture: VerifierFixture) -> DenyPathProof:
    directory = workspace / "denied"
    directory.mkdir(parents=True, exist_ok=False)
    token = "offline-verifier-deny-" + "d" * 32
    run_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4a")
    application, runtime, settings = _application(
        directory,
        token=token,
        now=fixture.generated_at,
        run_id=run_id,
        trace_id=UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4b"),
        correlation_id=UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4c"),
        proposal_id=UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b8a"),
        request_id=UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b8b"),
        nonce="offline-verifier-deny-nonce-000001",
        event_start=0xF000,
    )
    started = _start(
        application,
        token,
        CloudResourceType.SECURITY_GROUP,
        MOCK_UNSAFE_SECURITY_GROUP_ID,
    )
    challenge = _challenge(application, token, str(run_id))
    decision_status, decision_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/decision",
        token=token,
        body=_decision_body(challenge, "DENIED"),
    )
    _require(decision_status == 200, "VERIFIER_DENY_DECISION_FAILED")
    decision = _result(decision_payload)
    resume_status, resume_payload = _api_call(
        application,
        "POST",
        f"/api/runs/{run_id}/resume",
        token=token,
        body={"confirm_execution": True},
    )
    _require(resume_status == 200, "VERIFIER_DENY_RESUME_FAILED")
    completion = _result(resume_payload)
    _require(
        decision.get("final_state") == "DENIED_BY_HUMAN"
        and completion.get("final_state") == "DENIED_BY_HUMAN"
        and "receipt" not in completion
        and "verification" not in completion
        and runtime.executor.mutation_calls == 0,
        "VERIFIER_DENY_PATH_INVALID",
    )
    evidence = started.get("evidence")
    plan = started.get("plan")
    proposal = plan.get("proposal") if isinstance(plan, dict) else None
    _require(
        isinstance(evidence, dict) and isinstance(proposal, dict),
        "VERIFIER_DENY_PROVENANCE_MISSING",
    )
    return DenyPathProof(
        run_id=str(run_id),
        operation="REVOKE_PUBLIC_INGRESS",
        final_state="DENIED_BY_HUMAN",
        evidence_sha256=str(evidence["evidence_hash"]),
        proposal_sha256=str(proposal["proposal_hash"]),
        decision_sha256=str(decision["decision_hash"]),
        durable_provenance_sha256=_file_sha256(settings.state_path),
        execution_receipt_absent=True,
        independent_verification_absent=True,
        mock_mutation_count=0,
        provider_network_calls=0,
    )


def run_post_deploy_verifier(
    *,
    mode: VerifierMode,
    fixture: VerifierFixture | None,
    deployment_contract: AwsDeploymentContract,
    workspace: Path,
    live_adapter: LiveVerificationAdapter | None = None,
    enable_live: bool = False,
) -> PostDeployVerificationReceipt:
    """Run the full local chain or stop before the unavailable live boundary."""

    if mode is VerifierMode.LIVE_AWS:
        if not enable_live:
            raise PostDeployVerifierError("LIVE_POST_DEPLOY_VERIFIER_DISABLED")
        if live_adapter is None:
            raise PostDeployVerifierError("LIVE_POST_DEPLOY_ADAPTER_UNAVAILABLE")
        raise PostDeployVerifierError("LIVE_POST_DEPLOY_IMPLEMENTATION_NOT_SHIPPED")
    if enable_live or live_adapter is not None:
        raise PostDeployVerifierError("LIVE_POST_DEPLOY_OPTIONS_FORBIDDEN_OFFLINE")
    if fixture is None:
        raise PostDeployVerifierError("VERIFIER_FIXTURE_REQUIRED")
    _fixture_preconditions(fixture)
    if workspace.exists():
        try:
            if any(workspace.iterdir()):
                raise PostDeployVerifierError("VERIFIER_WORKSPACE_NOT_EMPTY")
        except OSError as error:
            raise PostDeployVerifierError("VERIFIER_WORKSPACE_UNAVAILABLE") from error
    else:
        try:
            workspace.mkdir(parents=True, mode=0o700)
        except OSError as error:
            raise PostDeployVerifierError("VERIFIER_WORKSPACE_UNAVAILABLE") from error
    approved, steps, probes = _approved_path(workspace, fixture)
    deny = _deny_path(workspace, fixture)
    material: dict[str, object] = {
        "approved_path": approved.model_dump(mode="json"),
        "aws_mutations": 0,
        "deny_path": deny.model_dump(mode="json"),
        "deployment_contract_sha256": contract_sha256(deployment_contract),
        "external_network_connections": 0,
        "failure_probes": [item.model_dump(mode="json") for item in probes],
        "generated_at": fixture.generated_at.isoformat().replace("+00:00", "Z"),
        "live_mode_enabled": False,
        "live_receipts": 0,
        "mock_mutations": 1,
        "mode": VerifierMode.OFFLINE_LOCAL_FIXTURE.value,
        "provider_network_calls": 0,
        "receipt_type": "PHASE3_POST_DEPLOY_VERIFICATION",
        "schema_version": 1,
        "secrets_redacted": True,
        "status": "PASS_OFFLINE",
        "steps": [item.model_dump(mode="json") for item in steps],
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return PostDeployVerificationReceipt.model_validate_json(
        canonical_json({**material, "receipt_sha256": digest})
    )


def render_verifier_receipt_schema() -> str:
    return pretty_json(PostDeployVerificationReceipt.model_json_schema(mode="validation"))


def render_verifier_fixture_schema() -> str:
    return pretty_json(VerifierFixture.model_json_schema(mode="validation"))


def render_verifier_markdown() -> str:
    chain = [f"{index}. `{step.value}`" for index, step in enumerate(VerificationStepId, 1)]
    probes = [f"- `{probe.value}`" for probe in FailureProbeId]
    return "\n".join(
        [
            "# Phase 3 Post-Deployment Verification Contract",
            "",
            "Status: complete offline fixture verifier; future live mode is disabled by default and "
            "has no shipped AWS adapter.",
            "",
            "## Ordered chain",
            "",
            *chain,
            "",
            "The offline chain invokes the loopback application's handler directly, so it exercises "
            "the strict API boundary without opening a socket. Durable local JSON stands in for the "
            "same repository contract intended for DynamoDB; the receipt labels it local and does not "
            "claim a deployed table. One approved protected mock mutation is independently read back, "
            "a conflicting replay is rejected, and a fresh runtime reconciles the persisted result "
            "without another mutation.",
            "",
            "## Required fail-closed probes",
            "",
            *probes,
            "",
            "The deny path is separate and must end `DENIED_BY_HUMAN` with no receipt, no independent "
            "verification claim, and zero mutation. Every probe records zero AWS mutations and zero "
            "additional mock mutations.",
            "",
            "## Live boundary",
            "",
            "Selecting `LIVE_AWS` returns `LIVE_POST_DEPLOY_VERIFIER_DISABLED` before adapter use. A "
            "future authorized implementation must preserve the same order, bind identity/account/"
            "region and deployment provenance, use separate explicit approval for remediation, and "
            "emit actual live evidence. A local PASS can never set `live_receipts` above zero.",
            "",
        ]
    )
