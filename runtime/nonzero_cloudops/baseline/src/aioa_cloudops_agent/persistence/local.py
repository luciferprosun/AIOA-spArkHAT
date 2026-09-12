"""Restart-safe, integrity-bound JSON implementation of durable truth."""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID

from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionResult,
    Approval,
    AuditEvent,
    BudgetCounters,
    Checkpoint,
    ExecutionAcknowledgement,
    IdempotencyRecord,
    IdempotencyStatus,
    ProposalState,
    Run,
    VerificationEvidence,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageDependencyError

from .local_integrity import (
    LocalIntegrityError,
    atomic_write_private_json,
    locked_private_file,
    open_local_payload,
    read_private_json,
    seal_local_payload,
    validate_local_path,
)
from .memory import InMemoryTestDurableTruthRepository

_DURABLE_PAYLOAD_TYPE = "AIOA_DURABLE_TRUTH"


@dataclass(frozen=True, slots=True)
class LocalRunSnapshot:
    """One internally consistent, integrity-verified judge read."""

    run: Run | None
    checkpoint: Checkpoint | None
    audit_events: tuple[AuditEvent, ...]
    audit_event_count: int
    integrity_status: Literal["VERIFIED"]
    snapshot_sha256: str


class LocalFileDurableTruthRepository:
    """Atomic local state with process locking, typed reconstruction, and a digest."""

    def __init__(self, path: str | Path) -> None:
        if isinstance(path, str):
            if not path.strip():
                raise ValueError("local state path must not be empty")
            resolved = Path(path)
        elif isinstance(path, Path):
            resolved = path
        else:
            raise TypeError("local state path must be str or Path")
        try:
            validate_local_path(resolved)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            validate_local_path(resolved)
        except (OSError, LocalIntegrityError) as error:
            raise StorageDependencyError("local state directory is unavailable") from error
        self._path = resolved
        self._lock_path = resolved.with_name(f"{resolved.name}.lock")
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
                raise StorageDependencyError("local state lock is unavailable") from error

    def _load(self) -> InMemoryTestDurableTruthRepository:
        repository, _ = self._load_with_digest()
        return repository

    def _load_with_digest(
        self,
    ) -> tuple[InMemoryTestDurableTruthRepository, str | None]:
        if not self._path.exists():
            return InMemoryTestDurableTruthRepository(), None
        try:
            envelope = read_private_json(self._path)
            payload, digest = open_local_payload(
                envelope,
                payload_type=_DURABLE_PAYLOAD_TYPE,
            )
            repository = InMemoryTestDurableTruthRepository.from_snapshot(payload)
        except StorageDependencyError:
            raise
        except (OSError, LocalIntegrityError) as error:
            raise StorageDependencyError("local durable state is corrupt or unreadable") from error
        return repository, digest

    def _write(self, repository: InMemoryTestDurableTruthRepository) -> None:
        try:
            envelope = seal_local_payload(
                repository.export_snapshot(),
                payload_type=_DURABLE_PAYLOAD_TYPE,
            )
            atomic_write_private_json(self._path, envelope)
        except (OSError, TypeError, ValueError) as error:
            raise StorageDependencyError("local durable state write failed") from error

    def _read[Result](
        self,
        operation: Callable[[InMemoryTestDurableTruthRepository], Result],
    ) -> Result:
        with self._lock(exclusive=False):
            return operation(self._load())

    def _mutate[Result](
        self,
        operation: Callable[[InMemoryTestDurableTruthRepository], Result],
    ) -> Result:
        with self._lock(exclusive=True):
            repository = self._load()
            result = operation(repository)
            self._write(repository)
            return result

    def create_run(self, run: Run) -> Run:
        return self._mutate(lambda repository: repository.create_run(run))

    def get_run(self, run_id: UUID) -> Run | None:
        return self._read(lambda repository: repository.get_run(run_id))

    def assert_ready(self) -> None:
        """Verify that the complete local snapshot is readable without changing truth."""

        self._read(lambda _repository: None)

    def transition_run(
        self,
        run_id: UUID,
        next_state: WorkflowState,
        *,
        expected_state: WorkflowState,
        expected_version: int,
        updated_at: datetime,
        approval_proposal_id: UUID | None = None,
        verification_proposal_id: UUID | None = None,
    ) -> Run:
        return self._mutate(
            lambda repository: repository.transition_run(
                run_id,
                next_state,
                expected_state=expected_state,
                expected_version=expected_version,
                updated_at=updated_at,
                approval_proposal_id=approval_proposal_id,
                verification_proposal_id=verification_proposal_id,
            )
        )

    def update_run_budget(
        self,
        run_id: UUID,
        budget: BudgetCounters,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> Run:
        return self._mutate(
            lambda repository: repository.update_run_budget(
                run_id,
                budget,
                expected_version=expected_version,
                updated_at=updated_at,
            )
        )

    def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        return self._mutate(lambda repository: repository.create_proposal(proposal))

    def get_proposal(self, proposal_id: UUID) -> ActionProposal | None:
        return self._read(lambda repository: repository.get_proposal(proposal_id))

    def transition_proposal(
        self,
        proposal_id: UUID,
        next_state: ProposalState,
        *,
        expected_state: ProposalState,
    ) -> ActionProposal:
        return self._mutate(
            lambda repository: repository.transition_proposal(
                proposal_id,
                next_state,
                expected_state=expected_state,
            )
        )

    def create_approval(self, approval: Approval) -> Approval:
        return self._mutate(lambda repository: repository.create_approval(approval))

    def get_approval(self, proposal_id: UUID) -> Approval | None:
        return self._read(lambda repository: repository.get_approval(proposal_id))

    def register_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        return self._mutate(lambda repository: repository.register_idempotency(record))

    def get_idempotency(self, idempotency_key: str) -> IdempotencyRecord | None:
        return self._read(lambda repository: repository.get_idempotency(idempotency_key))

    def complete_idempotency(
        self,
        idempotency_key: str,
        result: ActionResult,
        *,
        completed_at: datetime,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        return self._mutate(
            lambda repository: repository.complete_idempotency(
                idempotency_key,
                result,
                completed_at=completed_at,
                expected_status=expected_status,
            )
        )

    def record_execution_acknowledgement(
        self,
        idempotency_key: str,
        acknowledgement: ExecutionAcknowledgement,
        *,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        return self._mutate(
            lambda repository: repository.record_execution_acknowledgement(
                idempotency_key,
                acknowledgement,
                expected_status=expected_status,
            )
        )

    def save_checkpoint(
        self,
        checkpoint: Checkpoint,
        *,
        expected_version: int | None,
    ) -> Checkpoint:
        return self._mutate(
            lambda repository: repository.save_checkpoint(
                checkpoint,
                expected_version=expected_version,
            )
        )

    def get_checkpoint(self, run_id: UUID) -> Checkpoint | None:
        return self._read(lambda repository: repository.get_checkpoint(run_id))

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        return self._mutate(lambda repository: repository.append_audit_event(event))

    def get_audit_event(self, run_id: UUID, event_id: UUID) -> AuditEvent | None:
        return self._read(lambda repository: repository.get_audit_event(run_id, event_id))

    def list_audit_events(self, run_id: UUID, *, limit: int = 128) -> tuple[AuditEvent, ...]:
        """Read a bounded audit timeline for one exact run without scanning other state."""

        return self._read(
            lambda repository: repository.list_audit_events(run_id, limit=limit)
        )

    def read_run_snapshot(self, run_id: UUID, *, limit: int = 128) -> LocalRunSnapshot:
        """Read run, checkpoint, timeline, and digest under one shared file lock."""

        with self._lock(exclusive=False):
            repository, digest = self._load_with_digest()
            if digest is None:
                raise StorageDependencyError(
                    "local durable state has no integrity-bound snapshot"
                )
            return LocalRunSnapshot(
                run=repository.get_run(run_id),
                checkpoint=repository.get_checkpoint(run_id),
                audit_events=repository.list_audit_events(run_id, limit=limit),
                audit_event_count=repository.count_audit_events(run_id),
                integrity_status="VERIFIED",
                snapshot_sha256=digest,
            )

    def create_verification_evidence(
        self,
        evidence: VerificationEvidence,
    ) -> VerificationEvidence:
        return self._mutate(
            lambda repository: repository.create_verification_evidence(evidence)
        )

    def get_verification_evidence(
        self,
        run_id: UUID,
        proposal_id: UUID,
    ) -> VerificationEvidence | None:
        return self._read(
            lambda repository: repository.get_verification_evidence(run_id, proposal_id)
        )
