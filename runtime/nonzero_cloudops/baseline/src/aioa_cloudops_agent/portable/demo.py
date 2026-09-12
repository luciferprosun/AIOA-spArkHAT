"""One deterministic Strands-based judge sandbox with reusable Non-Zero proofs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from aioa_cloudops_agent.agent import (
    CURRENT_TOOL_NAMES,
    PRIMARY_AGENT_ID,
    BoundedInvestigationFlow,
    create_primary_agent,
)
from aioa_cloudops_agent.cloudops import (
    MOCK_CLEAN_INSTANCE_ID,
    InvestigationIdentity,
    MockAwsAdapter,
    SandboxTarget,
)
from aioa_cloudops_agent.config import (
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    ResultStatus,
    Run,
    WorkflowState,
    contains_sensitive_material,
    generate_event_id,
)
from aioa_cloudops_agent.persistence.local_integrity import (
    LocalIntegrityError,
    atomic_write_private_json,
    read_private_json,
    validate_local_path,
)
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.providers import MockModelProvider, MockToolCall
from aioa_cloudops_agent.release.deployment_contract import (
    canonical_json,
    load_deployment_contract,
)
from aioa_cloudops_agent.release.post_deploy_verifier import (
    PostDeployVerificationReceipt,
    VerifierMode,
    load_verifier_fixture,
    run_post_deploy_verifier,
)

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

_RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
_TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
_CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
_PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
_NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
_RESOURCE_ROOT = Path(__file__).with_name("resources")
_DEFAULT_CONTRACT = _RESOURCE_ROOT / "phase3-deployment-contract.json"
_DEFAULT_FIXTURE = _RESOURCE_ROOT / "post-deploy-verifier-pass.json"


class PortableDemoError(RuntimeError):
    """Public-safe fixed-reason portable demo failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class StrictPortableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class StrandsPortableProof(StrictPortableModel):
    """Evidence that the actual canonical Strands Agent ran without mutation authority."""

    schema_version: Literal[1]
    framework: Literal["strands-agents"]
    framework_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    agent_id: Literal["aioa-nonzero-cloudops-primary"]
    runtime_mode: Literal["portable"]
    provider: Literal["mock"]
    model_id: Literal["aioa.mock.deterministic-v1"]
    registered_tool_names: tuple[str, ...]
    run_id: UuidText
    trace_id: UuidText
    correlation_id: UuidText
    proposal_id: UuidText
    final_state: Literal["REMEDIATION_PROPOSED"]
    proposal_authorizes_execution: Literal[False]
    evidence_sha256: Sha256Digest
    model_calls: Literal[4]
    provider_network_calls: Literal[0]
    sandbox_read_calls: tuple[
        Literal["ec2:DescribeInstances", "cloudwatch:GetMetricStatistics"], ...
    ]
    external_network_connections: Literal[0]
    aws_calls: Literal[0]
    aws_mutations: Literal[0]
    sandbox_mutations: Literal[0]

    @model_validator(mode="after")
    def validate_agent_contract(self) -> Self:
        if self.registered_tool_names != CURRENT_TOOL_NAMES:
            raise ValueError("portable proof tool surface is not canonical")
        if self.sandbox_read_calls != (
            "ec2:DescribeInstances",
            "cloudwatch:GetMetricStatistics",
        ):
            raise ValueError("portable proof read sequence is not canonical")
        return self


class PortableDemoReceipt(StrictPortableModel):
    """Machine-readable wrapper around Strands and existing Non-Zero evidence."""

    schema_version: Literal[1]
    receipt_type: Literal["AIOA_PORTABLE_JUDGE_SANDBOX"]
    status: Literal["PASS"]
    generated_at: datetime
    runtime_mode: Literal["portable"]
    provider: Literal["mock"]
    provider_selection_explicit: Literal[True]
    strands_agent: StrandsPortableProof
    nonzero_verification: PostDeployVerificationReceipt
    external_network_connections: Literal[0]
    provider_network_calls: Literal[0]
    aws_calls: Literal[0]
    aws_mutations: Literal[0]
    sandbox_mutations: Literal[1]
    secrets_required: Literal[False]
    deterministic: Literal[True]
    receipt_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("portable receipt time must be UTC")
        verification = self.nonzero_verification
        if (
            verification.status != "PASS_OFFLINE"
            or verification.approved_path.final_state != "SUCCESS_WITH_EVIDENCE"
            or verification.deny_path.final_state != "DENIED_BY_HUMAN"
            or not verification.approved_path.replay_rejected
            or verification.approved_path.replay_mutation_delta != 0
            or not verification.approved_path.recovery_reconciled
            or verification.approved_path.recovery_mock_mutation_count != 0
            or verification.aws_mutations != 0
            or verification.external_network_connections != 0
            or verification.mock_mutations != self.sandbox_mutations
        ):
            raise ValueError("portable receipt requires the complete Non-Zero proof chain")
        material = self.model_dump(mode="json", exclude={"receipt_sha256"})
        digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
        if self.receipt_sha256 != digest:
            raise ValueError("portable receipt hash is invalid")
        if contains_sensitive_material(self.model_dump(mode="json")):
            raise ValueError("portable receipt contains sensitive material")
        return self


def _strands_framework_version() -> str:
    try:
        return version("strands-agents")
    except PackageNotFoundError as error:
        raise PortableDemoError("PORTABLE_STRANDS_RUNTIME_UNAVAILABLE") from error


def _run_strands_agent(settings: RuntimeSettings) -> StrandsPortableProof:
    run = Run.new(
        run_id=_RUN_ID,
        trace_id=_TRACE_ID,
        correlation_id=_CORRELATION_ID,
        idempotency_key="portable/strands/judge-v1",
        created_at=_NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=8_192),
    )
    adapter = MockAwsAdapter()
    model = MockModelProvider(
        tool_plan=(
            MockToolCall("inspect_instance", {"instance_id": MOCK_CLEAN_INSTANCE_ID}),
            MockToolCall(
                "read_utilization_metrics",
                {"instance_id": MOCK_CLEAN_INSTANCE_ID},
            ),
            MockToolCall(
                "build_remediation_evidence",
                {"instance_id": MOCK_CLEAN_INSTANCE_ID},
            ),
        )
    )
    repository = InMemoryTestDurableTruthRepository()
    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=_CORRELATION_ID,
            idempotency_key="portable/strands/judge-v1",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=8_192),
        ),
        identity=InvestigationIdentity.from_run(run),
        target=SandboxTarget(instance_id=MOCK_CLEAN_INSTANCE_ID),
        ec2_client=adapter,
        cloudwatch_client=adapter,
        proposal_id=_PROPOSAL_ID,
        clock=lambda: _NOW,
        runtime_settings=settings,
        model=model,
        durable_repository=repository,
    )
    result = BoundedInvestigationFlow(
        runtime,
        repository,
        clock=lambda: _NOW,
        event_id_factory=generate_event_id,
    ).execute(run)
    if result.status is not ResultStatus.SUCCESS or result.value is None:
        raise PortableDemoError("PORTABLE_STRANDS_INVOCATION_FAILED")
    completion = result.value
    if (
        completion.final_state is not WorkflowState.REMEDIATION_PROPOSED
        or completion.proposal.authorizes_execution
        or completion.evidence is None
        or runtime.registered_tool_names != CURRENT_TOOL_NAMES
        or runtime.model_settings.provider_name is not ModelProviderName.MOCK
        or runtime.model_settings.model is not model
        or runtime.model_settings.aws_calls_allowed
        or model.calls != 4
        or model.network_calls != 0
        or adapter.sdk_compatible_calls
        != ["ec2:DescribeInstances", "cloudwatch:GetMetricStatistics"]
        or adapter.network_calls != 0
        or adapter.mutation_calls != 0
    ):
        raise PortableDemoError("PORTABLE_STRANDS_PROOF_INVALID")
    return StrandsPortableProof(
        schema_version=1,
        framework="strands-agents",
        framework_version=_strands_framework_version(),
        agent_id=PRIMARY_AGENT_ID,
        runtime_mode=settings.mode.value,
        provider=settings.model_provider.value,
        model_id=runtime.model_settings.model_id,
        registered_tool_names=runtime.registered_tool_names,
        run_id=str(run.run_id),
        trace_id=str(run.trace_id),
        correlation_id=str(run.correlation_id),
        proposal_id=str(completion.proposal.proposal_id),
        final_state=completion.final_state.value,
        proposal_authorizes_execution=completion.proposal.authorizes_execution,
        evidence_sha256=completion.evidence.evidence_hash,
        model_calls=model.calls,
        provider_network_calls=model.network_calls,
        sandbox_read_calls=tuple(adapter.sdk_compatible_calls),
        external_network_connections=adapter.network_calls,
        aws_calls=0,
        aws_mutations=0,
        sandbox_mutations=adapter.mutation_calls,
    )


def run_portable_demo(
    *,
    settings: RuntimeSettings,
    workspace: Path,
    contract_path: Path = _DEFAULT_CONTRACT,
    fixture_path: Path = _DEFAULT_FIXTURE,
) -> PortableDemoReceipt:
    """Run Strands, approve, deny, replay, and recovery with no live boundary."""

    if not isinstance(settings, RuntimeSettings):
        raise PortableDemoError("PORTABLE_RUNTIME_SETTINGS_INVALID")
    if (
        settings.mode is not RuntimeMode.PORTABLE
        or settings.model_provider is not ModelProviderName.MOCK
        or settings.aws_calls_allowed
    ):
        raise PortableDemoError("PORTABLE_DEMO_REQUIRES_PORTABLE_MOCK_RUNTIME")
    if not isinstance(workspace, Path):
        raise PortableDemoError("PORTABLE_WORKSPACE_INVALID")
    strands_proof = _run_strands_agent(settings)
    verification = run_post_deploy_verifier(
        mode=VerifierMode.OFFLINE_LOCAL_FIXTURE,
        fixture=load_verifier_fixture(fixture_path),
        deployment_contract=load_deployment_contract(contract_path),
        workspace=workspace,
        live_adapter=None,
        enable_live=False,
    )
    material: dict[str, object] = {
        "aws_calls": 0,
        "aws_mutations": 0,
        "deterministic": True,
        "external_network_connections": 0,
        "generated_at": _NOW.isoformat().replace("+00:00", "Z"),
        "nonzero_verification": verification.model_dump(mode="json"),
        "provider": ModelProviderName.MOCK.value,
        "provider_network_calls": 0,
        "provider_selection_explicit": True,
        "receipt_type": "AIOA_PORTABLE_JUDGE_SANDBOX",
        "runtime_mode": RuntimeMode.PORTABLE.value,
        "sandbox_mutations": verification.mock_mutations,
        "schema_version": 1,
        "secrets_required": False,
        "status": "PASS",
        "strands_agent": strands_proof.model_dump(mode="json"),
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return PortableDemoReceipt.model_validate_json(
        canonical_json({**material, "receipt_sha256": digest})
    )


def render_portable_receipt(receipt: PortableDemoReceipt) -> str:
    """Render one stable, human-readable evidence document."""

    if not isinstance(receipt, PortableDemoReceipt):
        raise PortableDemoError("PORTABLE_RECEIPT_INVALID")
    return (
        json.dumps(
            receipt.model_dump(mode="json"),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def write_portable_receipt(path: Path, receipt: PortableDemoReceipt) -> None:
    """Atomically persist owner-only evidence without following an output symlink."""

    if (
        not isinstance(path, Path)
        or not str(path).strip()
        or ".." in path.parts
        or len(str(path).encode()) > 4_096
    ):
        raise PortableDemoError("PORTABLE_OUTPUT_PATH_INVALID")
    if path.is_symlink() or any(
        parent.is_symlink() for parent in path.parents if parent.exists()
    ):
        raise PortableDemoError("PORTABLE_OUTPUT_SYMLINK_FORBIDDEN")
    if path.exists():
        metadata = path.stat()
        if (
            not path.is_file()
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise PortableDemoError("PORTABLE_OUTPUT_EXISTING_FILE_UNSAFE")
        try:
            PortableDemoReceipt.model_validate(read_private_json(path))
        except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
            raise PortableDemoError("PORTABLE_OUTPUT_EXISTING_FILE_UNSAFE") from error
    try:
        validate_local_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_local_path(path)
        atomic_write_private_json(path, receipt.model_dump(mode="json"))
    except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
        raise PortableDemoError("PORTABLE_OUTPUT_UNAVAILABLE") from error
