"""Integrity-bound local mock inventory and protected execution boundary."""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock, RLock

from pydantic import TypeAdapter, ValidationError

from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.nz import (
    ApprovalDecision,
    CloudResource,
    ElasticIpResource,
    LocalApprovalDecisionRecord,
    LocalExecutionIntent,
    LocalExecutionReceipt,
    LocalVerificationEvidence,
    RemediationOperation,
    RemediationProposal,
    ResourceEvidence,
    ResourceQuery,
    SecurityGroupResource,
    SecurityGroupRule,
)
from aioa_cloudops_agent.persistence import compute_evidence_digest
from aioa_cloudops_agent.persistence.local_integrity import (
    LocalIntegrityError,
    atomic_write_private_json,
    locked_private_file,
    open_local_payload,
    read_private_json,
    seal_local_payload,
    validate_local_path,
)

from .provider import (
    CloudAdapterUnavailableError,
    CloudProviderError,
    CloudResourceNotFoundError,
    default_mock_resources,
)

_RESOURCE_ADAPTER = TypeAdapter(CloudResource)
_INVENTORY_PAYLOAD_TYPE = "AIOA_SANDBOX_INVENTORY"


class LocalMockMutationError(CloudProviderError):
    """Base typed failure for the isolated local mutation boundary."""


class LocalMockPolicyError(LocalMockMutationError):
    """The exact approval, proposal, evidence, or target policy was not satisfied."""


class LocalMockConflictError(LocalMockMutationError):
    """Durable local state conflicts with the approved action or idempotency key."""


class LocalMockStateStore:
    """Atomically persist mock inventory and receipts in one crash-safe file."""

    def __init__(
        self,
        path: str | Path,
        *,
        initial_resources: tuple[CloudResource, ...] | None = None,
    ) -> None:
        resolved = Path(path) if isinstance(path, (str, Path)) else None
        if resolved is None or not str(resolved).strip():
            raise ValueError("local mock state path must be a non-empty path")
        selected = initial_resources or default_mock_resources()
        identities = {
            (item.resource_type, item.resource_id, item.region) for item in selected
        }
        if len(identities) != len(selected):
            raise ValueError("local mock resources must have unique identities")
        try:
            validate_local_path(resolved)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            validate_local_path(resolved)
        except (OSError, LocalIntegrityError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state directory is unavailable"
            ) from error
        self._path = resolved
        self._lock_path = resolved.with_name(f"{resolved.name}.lock")
        self._initial_resources = tuple(selected)
        self._thread_lock = RLock()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _lock(self, *, exclusive: bool) -> object:
        with self._thread_lock:
            try:
                with locked_private_file(self._lock_path, exclusive=exclusive):
                    yield
            except (OSError, LocalIntegrityError) as error:
                raise CloudAdapterUnavailableError(
                    "local mock state lock is unavailable"
                ) from error

    def _initial_snapshot(
        self,
    ) -> tuple[dict[tuple[object, str, str], CloudResource], dict[str, LocalExecutionReceipt]]:
        resources = {
            (item.resource_type, item.resource_id, item.region): item
            for item in self._initial_resources
        }
        return resources, {}

    def _load(
        self,
    ) -> tuple[dict[tuple[object, str, str], CloudResource], dict[str, LocalExecutionReceipt]]:
        if not self._path.exists():
            return self._initial_snapshot()
        try:
            envelope = read_private_json(self._path)
            payload, _ = open_local_payload(
                envelope,
                payload_type=_INVENTORY_PAYLOAD_TYPE,
            )
        except (OSError, LocalIntegrityError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state is corrupt or unreadable"
            ) from error
        if not isinstance(payload, Mapping) or set(payload) != {
            "format_version",
            "receipts",
            "resources",
        }:
            raise CloudAdapterUnavailableError("local mock state shape is invalid")
        if payload.get("format_version") != 1:
            raise CloudAdapterUnavailableError("local mock state version is unsupported")
        raw_resources = payload.get("resources")
        raw_receipts = payload.get("receipts")
        if not isinstance(raw_resources, list) or not isinstance(raw_receipts, list):
            raise CloudAdapterUnavailableError("local mock state collections are invalid")
        try:
            resource_values = [_RESOURCE_ADAPTER.validate_python(item) for item in raw_resources]
            receipt_values = [LocalExecutionReceipt.model_validate(item) for item in raw_receipts]
        except (TypeError, ValueError, ValidationError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state violates typed contracts"
            ) from error
        resources = {
            (item.resource_type, item.resource_id, item.region): item
            for item in resource_values
        }
        receipts = {item.idempotency_key: item for item in receipt_values}
        if len(resources) != len(resource_values) or len(receipts) != len(receipt_values):
            raise CloudAdapterUnavailableError(
                "local mock state contains duplicate identities"
            )
        return resources, receipts

    def _write(
        self,
        resources: Mapping[tuple[object, str, str], CloudResource],
        receipts: Mapping[str, LocalExecutionReceipt],
    ) -> None:
        payload = {
            "format_version": 1,
            "receipts": [
                receipts[key].model_dump(mode="json") for key in sorted(receipts)
            ],
            "resources": [
                resources[key].model_dump(mode="json")
                for key in sorted(resources, key=lambda item: (str(item[0]), item[1], item[2]))
            ],
        }
        try:
            envelope = seal_local_payload(
                payload,
                payload_type=_INVENTORY_PAYLOAD_TYPE,
            )
            atomic_write_private_json(self._path, envelope)
        except (OSError, TypeError, ValueError) as error:
            raise CloudAdapterUnavailableError("local mock state write failed") from error

    def get_resource(self, query: ResourceQuery) -> CloudResource:
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        with self._lock(exclusive=False):
            resources, _ = self._load()
            resource = resources.get((query.resource_type, query.resource_id, query.region))
        if resource is None:
            raise CloudResourceNotFoundError(
                "resource was not found in the persistent local inventory"
            )
        return resource

    def assert_ready(self) -> None:
        """Verify that the sandbox inventory is readable without applying a mutation."""

        with self._lock(exclusive=False):
            self._load()

    def get_receipt(self, idempotency_key: str) -> LocalExecutionReceipt | None:
        with self._lock(exclusive=False):
            _, receipts = self._load()
            return receipts.get(idempotency_key)

    def execute(
        self,
        *,
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
        executed_at: datetime,
    ) -> tuple[LocalExecutionReceipt, bool]:
        """Apply and receipt one exact approved mutation in a single atomic replace."""

        self._validate_execution_binding(proposal, evidence, approval, intent)
        with self._lock(exclusive=True):
            resources, receipts = self._load()
            existing = receipts.get(intent.idempotency_key)
            if existing is not None:
                if (
                    existing.intent_hash != intent.intent_hash
                    or existing.proposal_hash != proposal.proposal_hash
                    or existing.decision_hash != approval.decision_hash
                ):
                    raise LocalMockConflictError(
                        "local idempotency key has conflicting ownership"
                    )
                return existing, False
            key = (
                proposal.target_resource_type,
                proposal.target_resource_id,
                evidence.resource.region,
            )
            current = resources.get(key)
            if current is None or current != evidence.resource:
                raise LocalMockConflictError(
                    "local target changed after evidence was approved"
                )
            after: CloudResource | None
            if proposal.operation_type is RemediationOperation.RELEASE_ELASTIC_IP:
                if (
                    not isinstance(current, ElasticIpResource)
                    or current.association_id is not None
                    or proposal.normalized_parameters
                    != {"allocation_id": proposal.target_resource_id}
                ):
                    raise LocalMockPolicyError("local release policy did not match exact state")
                del resources[key]
                after = None
            elif proposal.operation_type is RemediationOperation.REVOKE_PUBLIC_INGRESS:
                if not isinstance(current, SecurityGroupResource):
                    raise LocalMockPolicyError("local ingress target is not a Security Group")
                raw_rules = proposal.normalized_parameters.get("ingress_rules")
                if (
                    set(proposal.normalized_parameters) != {
                        "ingress_rules",
                        "security_group_id",
                    }
                    or proposal.normalized_parameters.get("security_group_id")
                    != proposal.target_resource_id
                    or not isinstance(raw_rules, list)
                    or not raw_rules
                ):
                    raise LocalMockPolicyError("local ingress parameters are not exact")
                try:
                    approved_rules = tuple(
                        SecurityGroupRule.model_validate(rule) for rule in raw_rules
                    )
                except (TypeError, ValueError, ValidationError) as error:
                    raise LocalMockPolicyError(
                        "local ingress approval contains malformed rules"
                    ) from error
                if any(rule not in current.inbound_rules for rule in approved_rules):
                    raise LocalMockConflictError(
                        "approved ingress rule no longer exists on the target"
                    )
                remaining = tuple(
                    rule for rule in current.inbound_rules if rule not in approved_rules
                )
                if len(remaining) != len(current.inbound_rules) - len(set(approved_rules)):
                    raise LocalMockPolicyError("approved ingress rules are ambiguous")
                after = current.model_copy(update={"inbound_rules": remaining})
                resources[key] = after
            else:
                raise LocalMockPolicyError("local operation is NEVER_AUTONOMOUS")
            values: dict[str, object] = {
                "run_id": proposal.run_id,
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal.proposal_hash,
                "evidence_hash": proposal.evidence_hash,
                "decision_hash": approval.decision_hash,
                "intent_hash": intent.intent_hash,
                "idempotency_key": intent.idempotency_key,
                "operation_type": proposal.operation_type,
                "target_resource_type": proposal.target_resource_type,
                "target_resource_id": proposal.target_resource_id,
                "before_resource": current,
                "after_resource": after,
                "executed_at": executed_at,
            }
            provisional = LocalExecutionReceipt.model_construct(
                **values,
                receipt_hash="0" * 64,
            )
            receipt = LocalExecutionReceipt(
                **values,
                receipt_hash=compute_evidence_digest(provisional.receipt_payload()),
            )
            receipts[intent.idempotency_key] = receipt
            self._write(resources, receipts)
            return receipt, True

    @staticmethod
    def _validate_execution_binding(
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
    ) -> None:
        if (
            proposal.authority_class is not AuthorityGate.PLAN_AND_CONFIRM
            or proposal.authorizes_execution
            or approval.decision is not ApprovalDecision.APPROVED
            or proposal.run_id != evidence.run_id
            or proposal.correlation_id != evidence.correlation_id
            or proposal.evidence_hash != evidence.evidence_hash
            or proposal.evidence_fingerprint != evidence.stable_fingerprint()
            or approval.proposal_id != proposal.proposal_id
            or approval.run_id != proposal.run_id
            or approval.proposal_hash != proposal.proposal_hash
            or approval.evidence_hash != proposal.evidence_hash
            or approval.proposal_version != proposal.version
            or intent.run_id != proposal.run_id
            or intent.proposal_id != proposal.proposal_id
            or intent.proposal_hash != proposal.proposal_hash
            or intent.evidence_hash != proposal.evidence_hash
            or intent.decision_hash != approval.decision_hash
            or intent.operation_type is not proposal.operation_type
            or intent.target_resource_type is not proposal.target_resource_type
            or intent.target_resource_id != proposal.target_resource_id
            or intent.idempotency_key != f"local-exec:{proposal.proposal_hash}"
        ):
            raise LocalMockPolicyError(
                "local executor prerequisites are not exactly approval-bound"
            )

    def verify(
        self,
        receipt: LocalExecutionReceipt,
        *,
        verified_at: datetime,
    ) -> LocalVerificationEvidence:
        """Read the persisted inventory independently and bind exact post-action proof."""

        with self._lock(exclusive=False):
            resources, receipts = self._load()
            durable_receipt = receipts.get(receipt.idempotency_key)
            if durable_receipt != receipt:
                raise LocalMockConflictError("local execution receipt is not durable")
            key = (
                receipt.target_resource_type,
                receipt.target_resource_id,
                receipt.before_resource.region,
            )
            observed = resources.get(key)
        if receipt.operation_type is RemediationOperation.RELEASE_ELASTIC_IP:
            if observed is not None:
                raise LocalMockConflictError("released local address is still present")
            observed_absent = True
        elif receipt.operation_type is RemediationOperation.REVOKE_PUBLIC_INGRESS:
            if observed != receipt.after_resource:
                raise LocalMockConflictError(
                    "local Security Group read-back differs from the receipt"
                )
            observed_absent = False
        else:
            raise LocalMockPolicyError("local verification operation is non-executable")
        values: dict[str, object] = {
            "run_id": receipt.run_id,
            "proposal_id": receipt.proposal_id,
            "receipt_hash": receipt.receipt_hash,
            "operation_type": receipt.operation_type,
            "target_resource_type": receipt.target_resource_type,
            "target_resource_id": receipt.target_resource_id,
            "observed_absent": observed_absent,
            "observed_resource": observed,
            "verified_at": verified_at,
        }
        provisional = LocalVerificationEvidence.model_construct(
            **values,
            verification_hash="0" * 64,
        )
        return LocalVerificationEvidence(
            **values,
            verification_hash=compute_evidence_digest(
                provisional.verification_payload()
            ),
        )


class PersistentMockAwsAdapter:
    """Read-only CloudProvider view over the separately protected local state store."""

    def __init__(self, state: LocalMockStateStore) -> None:
        if not isinstance(state, LocalMockStateStore):
            raise TypeError("state must be LocalMockStateStore")
        self._state = state
        self.read_calls: list[ResourceQuery] = []
        self.network_calls = 0

    @property
    def adapter_name(self) -> str:
        return "persistent-local-mock-aws"

    def get_resource(self, query: ResourceQuery) -> CloudResource:
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        self.read_calls.append(query)
        return self._state.get_resource(query)


class LocalMockRemediationExecutor:
    """Only component allowed to call the persistent local mutation boundary."""

    def __init__(
        self,
        state: LocalMockStateStore,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(state, LocalMockStateStore) or not callable(clock):
            raise TypeError("state and clock are required")
        self._state = state
        self._clock = clock
        self._counter_lock = Lock()
        self.execute_calls = 0
        self.mutation_calls = 0
        self.reconciled_calls = 0

    def execute(
        self,
        *,
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
    ) -> LocalExecutionReceipt:
        with self._counter_lock:
            self.execute_calls += 1
        receipt, applied = self._state.execute(
            proposal=proposal,
            evidence=evidence,
            approval=approval,
            intent=intent,
            executed_at=self._clock(),
        )
        with self._counter_lock:
            if applied:
                self.mutation_calls += 1
            else:
                self.reconciled_calls += 1
        return receipt

    def counters(self) -> tuple[int, int, int]:
        """Return execution, mutation, and reconciliation counters atomically."""

        with self._counter_lock:
            return self.execute_calls, self.mutation_calls, self.reconciled_calls

    def get_receipt(self, idempotency_key: str) -> LocalExecutionReceipt | None:
        return self._state.get_receipt(idempotency_key)

    def verify(self, receipt: LocalExecutionReceipt) -> LocalVerificationEvidence:
        return self._state.verify(receipt, verified_at=self._clock())
