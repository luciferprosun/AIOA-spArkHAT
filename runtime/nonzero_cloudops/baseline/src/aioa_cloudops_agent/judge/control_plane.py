"""Dormant private coordinators behind fail-closed public Judge adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aioa_cloudops_agent.cloudops import InspectInstanceService, SandboxTarget
from aioa_cloudops_agent.config import VerificationSettings
from aioa_cloudops_agent.nz import ControlResult, FailureDetail, FailureKind
from aioa_cloudops_agent.persistence import DurableTruthRepository
from aioa_cloudops_agent.recovery import RecoveryCoordinator
from aioa_cloudops_agent.remediation import (
    LambdaPrivateRemediationExecutor,
    StopSandboxInstanceCoordinator,
)
from aioa_cloudops_agent.safety import (
    BoundedReadRetry,
    CircuitDependency,
    DependencyCircuitBreaker,
)
from aioa_cloudops_agent.verification import (
    BoundedVerificationCoordinator,
    VerifyInstanceStateService,
)

_DORMANT_VERIFICATION_SETTINGS = VerificationSettings(
    max_attempts=1,
    interval_seconds=0,
)


@dataclass(frozen=True, slots=True)
class JudgePrivateControlPlane:
    """Composed private controls that have no route or callable public delegation."""

    remediation: StopSandboxInstanceCoordinator
    verification: BoundedVerificationCoordinator
    recovery: RecoveryCoordinator

    def public_stop_request(self, proposal_id: UUID) -> dict[str, object]:
        """Deny public mutation even if the model requests the registered tool."""

        del proposal_id
        return _public_control_denial(
            FailureKind.POLICY_DENIAL,
            "PUBLIC_MUTATION_UNAVAILABLE",
            "Mutation is unavailable on the public Judge surface",
        )

    def public_verification_request(self, proposal_id: UUID) -> dict[str, object]:
        """Deny in-request verification; recovery remains a future private route."""

        del proposal_id
        return _public_control_denial(
            FailureKind.RECOVERY_REQUIREMENT,
            "PUBLIC_VERIFICATION_UNAVAILABLE",
            "Verification requires a bounded private recovery request",
        )


def _public_control_denial(
    kind: FailureKind,
    code: str,
    message: str,
) -> dict[str, object]:
    return ControlResult[str].failed(
        FailureDetail(
            kind=kind,
            code=code,
            message=message,
            retryable=False,
        )
    ).model_dump(mode="json")


def build_judge_private_control_plane(
    *,
    repository: DurableTruthRepository,
    lambda_client: object,
    private_executor_alias_arn: str,
    ec2_client: object,
    target: SandboxTarget,
    dependency_circuit: DependencyCircuitBreaker,
    clock: Callable[[], datetime],
    event_id_factory: Callable[[], UUID],
    evidence_id_factory: Callable[[], UUID],
    recovery_id_factory: Callable[[], UUID],
) -> JudgePrivateControlPlane:
    """Compose private-only controls without authorizing or scheduling execution."""

    if not isinstance(target, SandboxTarget):
        raise TypeError("target must be SandboxTarget")
    if not isinstance(dependency_circuit, DependencyCircuitBreaker):
        raise TypeError("dependency_circuit must be DependencyCircuitBreaker")
    if not all(
        callable(value)
        for value in (clock, event_id_factory, evidence_id_factory, recovery_id_factory)
    ):
        raise TypeError("private control factories must be callable")
    executor = LambdaPrivateRemediationExecutor(
        lambda_client,
        private_executor_alias_arn,
    )
    remediation = StopSandboxInstanceCoordinator(
        repository,
        executor,
        clock=clock,
        event_id_factory=event_id_factory,
    )
    verification_service = VerifyInstanceStateService(
        InspectInstanceService(
            ec2_client,
            target,
            retry=BoundedReadRetry(
                max_attempts=1,
                circuit_breaker=dependency_circuit,
                dependency=CircuitDependency.VERIFICATION_READ,
            ),
        ),
        target,
    )
    verification = BoundedVerificationCoordinator(
        repository,
        verification_service,
        settings=_DORMANT_VERIFICATION_SETTINGS,
        clock=clock,
        sleeper=lambda _seconds: None,
        event_id_factory=event_id_factory,
        evidence_id_factory=evidence_id_factory,
    )
    recovery = RecoveryCoordinator(
        repository,
        clock=clock,
        sleeper=lambda _seconds: None,
        event_id_factory=event_id_factory,
        recovery_id_factory=recovery_id_factory,
        evidence_id_factory=evidence_id_factory,
        verification_reconciler=verification.verify,
        readback_service=verification_service,
        verification_settings=_DORMANT_VERIFICATION_SETTINGS,
    )
    return JudgePrivateControlPlane(
        remediation=remediation,
        verification=verification,
        recovery=recovery,
    )
