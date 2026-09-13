"""Reviewed pure domain semantics with native, inert dependencies."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from runtime.core_admission import Capability, CoreActor, CoreAdmission
from runtime.memory_patch.audit import (
    CoreLedgerPublication,
    append_domain_event,
    mark_published,
    require_record_audit,
)
from runtime.memory_patch.contracts.enums import (
    ActorType,
    ApprovalDecision,
    ApprovalRequirement,
    MemoryContentKind,
    MemoryTargetScope,
    PatchState,
    PersonalMemorySpaceState,
)
from runtime.memory_patch.contracts.records import (
    COMMIT_ACTOR_TYPES,
    MemoryPatchApproval,
    MemoryPatchCommit,
    MemoryPatchProposal,
    PersonalHatQuotaPolicy,
    PersonalHatQuotaUsage,
    _replace_memory_patch_lifecycle,
    enforce_quota,
    verify_approval_binding,
    verify_commit_binding,
    verify_memory_patch_proposal_hash,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
    require_enum_member,
    require_non_empty,
    require_sha256_hex,
    to_canonical_data,
)
from runtime.memory_patch.errors import (
    AuthorityViolation,
    ContractValidationError,
    ErrorCode,
    InvalidTransition,
    MemoryPatchError,
)
from runtime.memory_patch.hats import NativeHatAdmission
from runtime.memory_patch.persistence.idempotency import OperationBinding, execute_once
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
    TransactionRunner,
)
from runtime.memory_patch.personal.contracts import (
    PersonalEvidenceValidationPort,
    instant,
    proposal_from_record,
    stamp,
    validate_patch_record,
)

MEMORY_PATCH_TRANSITIONS = MappingProxyType(
    {
        PatchState.DETECTED: frozenset({PatchState.PROPOSED}),
        PatchState.PROPOSED: frozenset({PatchState.EVIDENCE_BOUND}),
        PatchState.EVIDENCE_BOUND: frozenset({PatchState.VALIDATED}),
        PatchState.VALIDATED: frozenset({PatchState.AWAITING_APPROVAL}),
        PatchState.AWAITING_APPROVAL: frozenset(
            {PatchState.APPROVED, PatchState.REJECTED}
        ),
        PatchState.APPROVED: frozenset({PatchState.COMMITTED}),
        PatchState.COMMITTED: frozenset({PatchState.ACTIVE}),
        PatchState.ACTIVE: frozenset({PatchState.SUPERSEDED, PatchState.REVOKED}),
        PatchState.SUPERSEDED: frozenset(),
        PatchState.REJECTED: frozenset(),
        PatchState.REVOKED: frozenset(),
    }
)
MEMORY_PATCH_TERMINAL_STATES = frozenset(
    {PatchState.SUPERSEDED, PatchState.REJECTED, PatchState.REVOKED}
)


@dataclass(frozen=True, slots=True)
class PatchTransitionRecord:
    """Appendable transition fact preserving proposal identity and history."""

    proposal_id: str
    proposal_content_hash: str
    state_before: PatchState
    state_after: PatchState
    actor_type: ActorType
    actor_id: str
    transitioned_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.proposal_id, "proposal_id")
        require_sha256_hex(self.proposal_content_hash, "proposal_content_hash")
        require_enum_member(self.state_before, PatchState, "state_before")
        require_enum_member(self.state_after, PatchState, "state_after")
        require_enum_member(self.actor_type, ActorType, "actor_type")
        if not memory_patch_transition_allowed(self.state_before, self.state_after):
            raise InvalidTransition(
                "PatchTransitionRecord contains a forbidden lifecycle edge"
            )
        require_non_empty(self.actor_id, "actor_id")
        object.__setattr__(
            self, "transitioned_at", ensure_utc(self.transitioned_at, "transitioned_at")
        )


def memory_patch_transition_allowed(current: PatchState, target: PatchState) -> bool:
    """Return whether the exact successful/side-path graph contains an edge."""
    require_enum_member(current, PatchState, "current")
    require_enum_member(target, PatchState, "target")
    return target in MEMORY_PATCH_TRANSITIONS[current]


def _validate_approval_for_target(
    proposal: MemoryPatchProposal, approval: MemoryPatchApproval
) -> None:
    verify_approval_binding(proposal, approval)
    if proposal.approval_requirement is ApprovalRequirement.OWNER and (
        approval.approver_type is not ActorType.USER
        or approval.approver_id != proposal.owner_user_id
    ):
        raise AuthorityViolation("owner approval must come from the exact owner")
    if (
        proposal.approval_requirement is ApprovalRequirement.DOMAIN_REVIEWER
        and approval.approver_type is not ActorType.HUMAN_REVIEWER
    ):
        raise AuthorityViolation(
            "shared Knowledge HAT patch requires domain reviewer approval"
        )
    if (
        proposal.approval_requirement is ApprovalRequirement.SYSTEM_MIGRATION_REVIEW
        and approval.approver_type is not ActorType.HUMAN_REVIEWER
    ):
        raise AuthorityViolation(
            "system migration patch requires independent human review"
        )
    if (
        proposal.content_kind is MemoryContentKind.PREFERENCE
        and proposal.target_scope is MemoryTargetScope.USER_PERSONAL_HAT
        and (
            approval.approver_type is not ActorType.USER
            or approval.approver_id != proposal.owner_user_id
        )
    ):
        raise AuthorityViolation(
            "a personal preference still requires exact owner approval"
        )


def transition_memory_patch(
    proposal: MemoryPatchProposal,
    *,
    target_state: PatchState,
    actor_type: ActorType,
    actor_id: str,
    transitioned_at: datetime,
    approval: MemoryPatchApproval | None = None,
    commit: MemoryPatchCommit | None = None,
) -> tuple[MemoryPatchProposal, PatchTransitionRecord]:
    """Apply one graph edge after evidence, approval, and authority invariants."""
    require_enum_member(target_state, PatchState, "target_state")
    require_enum_member(actor_type, ActorType, "actor_type")
    verify_memory_patch_proposal_hash(proposal)
    if not memory_patch_transition_allowed(proposal.lifecycle_state, target_state):
        raise InvalidTransition(
            f"Memory Patch transition {proposal.lifecycle_state.value} -> {target_state.value} is forbidden"
        )
    require_non_empty(actor_id, "actor_id")
    transitioned_at = ensure_utc(transitioned_at, "transitioned_at")
    if transitioned_at < proposal.created_at:
        raise ContractValidationError(
            "Memory Patch transition cannot precede proposal creation"
        )
    if (
        target_state is PatchState.EVIDENCE_BOUND
        and proposal.content_kind is MemoryContentKind.FACTUAL
        and (not proposal.evidence_references)
    ):
        raise ContractValidationError(
            "a factual patch cannot bind an empty evidence set"
        )
    if (
        target_state is PatchState.VALIDATED
        and proposal.content_kind is MemoryContentKind.FACTUAL
        and (not proposal.evidence_references)
    ):
        raise ContractValidationError(
            "a factual patch cannot reach VALIDATED without evidence"
        )
    if target_state in {PatchState.APPROVED, PatchState.REJECTED}:
        if approval is None:
            raise AuthorityViolation("approval transition requires an approval record")
        _validate_approval_for_target(proposal, approval)
        expected_decision = (
            ApprovalDecision.APPROVE
            if target_state is PatchState.APPROVED
            else ApprovalDecision.REJECT
        )
        if approval.decision is not expected_decision:
            raise ContractValidationError(
                "approval decision does not match target patch state"
            )
        if actor_type != approval.approver_type or actor_id != approval.approver_id:
            raise AuthorityViolation(
                "transition actor must be the bound approval actor"
            )
        if transitioned_at < approval.decided_at:
            raise ContractValidationError(
                "approval transition cannot precede the bound decision"
            )
    elif actor_type in {
        ActorType.KNOWLEDGE_HAT,
        ActorType.KNOWLEDGE_KERNEL,
        ActorType.KNOWLEDGE_HUB,
        ActorType.CRITIC_PROMPT_LOOP,
        ActorType.MODEL,
        ActorType.MODEL_VERIFIER,
    } and target_state in {
        PatchState.APPROVED,
        PatchState.COMMITTED,
        PatchState.ACTIVE,
    }:
        raise AuthorityViolation(
            f"{actor_type.value} may propose but cannot approve, commit, or activate"
        )
    if target_state is PatchState.COMMITTED:
        if commit is None:
            raise AuthorityViolation("COMMITTED requires a technical commit receipt")
        if approval is None:
            raise AuthorityViolation("COMMITTED requires the bound approval record")
        if actor_type not in COMMIT_ACTOR_TYPES:
            raise AuthorityViolation("actor lacks technical commit authority")
        if actor_type != commit.actor_type or actor_id != commit.actor_id:
            raise AuthorityViolation("transition actor does not match commit receipt")
        _validate_approval_for_target(proposal, approval)
        verify_commit_binding(proposal, approval, commit)
        if transitioned_at < commit.committed_at:
            raise ContractValidationError(
                "commit transition cannot precede the commit receipt"
            )
    if target_state is PatchState.ACTIVE:
        if actor_type is not ActorType.COMMIT_SERVICE:
            raise AuthorityViolation(
                "only the bounded technical commit service may activate"
            )
        if approval is None or commit is None:
            raise AuthorityViolation(
                "activation requires the approval and commitment bindings"
            )
        _validate_approval_for_target(proposal, approval)
        if approval.decision is not ApprovalDecision.APPROVE:
            raise AuthorityViolation("rejected content cannot activate")
        verify_commit_binding(proposal, approval, commit)
        if transitioned_at < commit.committed_at:
            raise ContractValidationError(
                "activation cannot precede the commit receipt"
            )
    if target_state in {PatchState.SUPERSEDED, PatchState.REVOKED}:
        if actor_type not in {
            ActorType.USER,
            ActorType.HUMAN_REVIEWER,
            ActorType.SYSTEM,
            ActorType.COMMIT_SERVICE,
        }:
            raise AuthorityViolation(
                f"{actor_type.value} cannot revoke or supersede active memory"
            )
        if actor_type is ActorType.USER and (
            proposal.owner_user_id is None or actor_id != proposal.owner_user_id
        ):
            raise AuthorityViolation(
                "only the exact owner may revoke or supersede a personal patch"
            )
    updated = _replace_memory_patch_lifecycle(proposal, lifecycle_state=target_state)
    if updated.content_hash != proposal.content_hash:
        raise ContractValidationError(
            "lifecycle transition changed immutable proposal identity"
        )
    transition = PatchTransitionRecord(
        proposal_id=proposal.proposal_id,
        proposal_content_hash=proposal.content_hash,
        state_before=proposal.lifecycle_state,
        state_after=target_state,
        actor_type=actor_type,
        actor_id=actor_id,
        transitioned_at=transitioned_at,
    )
    return (updated, transition)


PERSONAL_MEMORY_TRANSITIONS = MappingProxyType(
    {
        PersonalMemorySpaceState.EMPTY: frozenset(
            {
                PersonalMemorySpaceState.CONFIGURED,
                PersonalMemorySpaceState.DELETED_PENDING,
            }
        ),
        PersonalMemorySpaceState.CONFIGURED: frozenset(
            {
                PersonalMemorySpaceState.ACTIVE,
                PersonalMemorySpaceState.ARCHIVED,
                PersonalMemorySpaceState.DELETED_PENDING,
            }
        ),
        PersonalMemorySpaceState.ACTIVE: frozenset(
            {
                PersonalMemorySpaceState.SUSPENDED,
                PersonalMemorySpaceState.ARCHIVED,
                PersonalMemorySpaceState.DELETED_PENDING,
            }
        ),
        PersonalMemorySpaceState.SUSPENDED: frozenset(
            {
                PersonalMemorySpaceState.ACTIVE,
                PersonalMemorySpaceState.ARCHIVED,
                PersonalMemorySpaceState.DELETED_PENDING,
            }
        ),
        PersonalMemorySpaceState.ARCHIVED: frozenset(
            {
                PersonalMemorySpaceState.CONFIGURED,
                PersonalMemorySpaceState.DELETED_PENDING,
            }
        ),
        PersonalMemorySpaceState.DELETED_PENDING: frozenset(
            {PersonalMemorySpaceState.DELETED}
        ),
        PersonalMemorySpaceState.DELETED: frozenset(),
    }
)
PERSONAL_MEMORY_TERMINAL_STATES = frozenset({PersonalMemorySpaceState.DELETED})


def personal_memory_transition_allowed(
    current: PersonalMemorySpaceState, target: PersonalMemorySpaceState
) -> bool:
    """Return whether the explicit Personal Memory graph contains the edge."""
    require_enum_member(current, PersonalMemorySpaceState, "current")
    require_enum_member(target, PersonalMemorySpaceState, "target")
    return target in PERSONAL_MEMORY_TRANSITIONS[current]


class NativeMemoryLifecycle:
    def __init__(
        self,
        core: CoreAdmission,
        transactions: TransactionRunner,
        *,
        hats: NativeHatAdmission | None = None,
        evidence: PersonalEvidenceValidationPort | None = None,
        publication: CoreLedgerPublication | None = None,
        clock=None,
    ):
        self.core, self.transactions = core, transactions
        self.hats, self.evidence, self.publication = hats, evidence, publication
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def operation(self, principal, capability, key, kind, binding, mutation):
        self.core.require(principal, capability)
        operation = OperationBinding.bind(key, kind, binding)
        at = ensure_utc(self.clock(), "trusted_now")
        identities = {}

        def apply(tx):
            def save(record, previous=None):
                ident = (record.record_id, record.revision)
                if ident not in identities:
                    identities[ident] = (
                        "event_" + secrets.token_hex(16),
                        "proof_" + secrets.token_hex(16),
                    )
                if previous is None:
                    tx.insert(record)
                else:
                    tx.replace(record, expected_revision=previous.revision)
                event_id, proof_id = identities[ident]
                append_domain_event(
                    tx,
                    operation,
                    event_id=event_id,
                    proof_id=proof_id,
                    resource_id=record.record_id,
                    before=None if previous is None else previous.payload.get("state"),
                    after=record.payload.get("state", "RECORDED"),
                    content_digest=record.payload_digest,
                    at=at,
                )
                return proof_id

            return execute_once(tx, operation, lambda: mutation(tx, save, at))

        return self.transactions.run(TransactionContext(principal, capability), apply)

    def get(self, tx, kind, record_id):
        record = tx.get(kind, record_id)
        if record is None:
            raise MemoryPatchError(ErrorCode.NOT_FOUND)
        require_record_audit(tx, record)
        if kind is RecordKind.PATCH:
            validate_patch_record(record)
        return record

    def space(self, tx, *, active=True):
        record = self.get(tx, RecordKind.SPACE, "owner-memory-slot")
        state = PersonalMemorySpaceState(record.payload["state"])
        if state in {
            PersonalMemorySpaceState.DELETED_PENDING,
            PersonalMemorySpaceState.DELETED,
        } or (active and state is not PersonalMemorySpaceState.ACTIVE):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        return record

    def scoped_hat(self, principal, hat_id):
        if self.hats is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        return self.hats.selected(principal, hat_id)

    def require_configuration(self, tx, candidate, record=None):
        principal = tx.context.principal
        self.core.require(principal, principal.capability)
        space = self.space(tx)
        hat = self.scoped_hat(principal, candidate.hat_id)
        p = space.payload
        if (
            candidate.hat_id != p["hat_id"]
            or not set(candidate.model_binding_ids) <= set(p["model_binding_ids"])
            or not set(candidate.model_binding_ids) <= principal.model_binding_ids
        ):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if record is not None and (
            record.payload["slot_config_revision"] != p["config_revision"]
            or record.payload["hat_manifest_digest"] != hat.manifest_digest
        ):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        if record is not None and record.payload["logically_deleted"]:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        return space, hat

    def require_evidence(self, principal, candidate, record=None):
        if self.evidence is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        binding = self.evidence.validate(principal, candidate)
        if (
            binding.scope != principal.scope
            or binding.candidate_digest != candidate.content_digest
            or binding.references != candidate.evidence_references
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        if (
            candidate.content_kind is MemoryContentKind.FACTUAL
            and binding.verification_status != "VERIFIED"
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        if (
            record is not None
            and record.payload["evidence_binding"] is not None
            and canonical_sha256(binding)
            != canonical_sha256(record.payload["evidence_binding"])
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        return binding

    def require_current(self, tx, record, *, check_validity=True):
        candidate = validate_patch_record(record)
        self.require_configuration(tx, candidate, record)
        if check_validity:
            now = ensure_utc(self.clock(), "trusted_now")
            if (
                candidate.valid_from is not None
                and now < candidate.valid_from
                or candidate.valid_until is not None
                and now > candidate.valid_until
                or candidate.expires_at is not None
                and now >= candidate.expires_at
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        binding = self.require_evidence(tx.context.principal, candidate, record)
        return candidate, binding

    def enforce_space_quota(self, tx, *, extra=None, activate_id=None):
        space = self.space(tx)
        records = tx.scan(RecordKind.PATCH, limit=1024)
        if len(records) >= 1024:
            raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
        for record in records:
            require_record_audit(tx, record)
            validate_patch_record(record)
        live = [r for r in records if not r.payload["logically_deleted"]]
        contents = [r.payload["candidate"] for r in live] + (
            [] if extra is None else [extra.private_data()]
        )
        used_bytes = sum(len(canonical_json_bytes(c)) for c in contents)
        active = sum(
            r.payload["state"] == PatchState.ACTIVE.value or r.record_id == activate_id
            for r in live
        )
        quota = PersonalHatQuotaPolicy(**dict(space.payload["quota"]))
        usage = PersonalHatQuotaUsage(
            total_spaces=1,
            active_spaces=1,
            bytes_used=used_bytes,
            personal_sources=len(
                {ref for c in contents for ref in c["evidence_references"]}
            ),
            active_memory_patches=active,
        )
        enforce_quota(quota, usage)
        return usage

    def transition(
        self, tx, save, record, target, at, *, updates=None, approval=None, commit=None
    ):
        principal = tx.context.principal
        expected = {
            PatchState.PROPOSED: Capability.PROPOSE,
            PatchState.EVIDENCE_BOUND: Capability.PROPOSE,
            PatchState.VALIDATED: Capability.VALIDATE,
            PatchState.AWAITING_APPROVAL: Capability.VALIDATE,
            PatchState.APPROVED: Capability.OWNER_APPROVAL,
            PatchState.REJECTED: Capability.OWNER_APPROVAL,
            PatchState.COMMITTED: Capability.COMMIT,
            PatchState.ACTIVE: Capability.ACTIVATE,
            PatchState.SUPERSEDED: Capability.MANAGE,
            PatchState.REVOKED: Capability.MANAGE,
        }
        self.core.require(principal, expected[target], scope=record.scope)
        actor = (
            ActorType.COMMIT_SERVICE
            if principal.actor is CoreActor.COMMIT_SERVICE
            else ActorType.USER
        )
        actor_id = (
            principal.actor_session_id
            if actor is ActorType.COMMIT_SERVICE
            else principal.scope.owner_id
        )
        proposal, _ = transition_memory_patch(
            proposal_from_record(record),
            target_state=target,
            actor_type=actor,
            actor_id=actor_id,
            transitioned_at=at,
            approval=approval,
            commit=commit,
        )
        if at < instant(record.payload["updated_at"]):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        updated = StoredRecord(
            record.kind,
            record.record_id,
            record.scope,
            record.revision + 1,
            {
                **record.payload,
                **(updates or {}),
                "state": target.value,
                "proposal": to_canonical_data(proposal),
                "updated_at": stamp(at),
            },
        )
        validate_patch_record(updated)
        proof = save(updated, record)
        return updated, proof

    def read(self, principal, patch_id):
        self.core.require(principal, Capability.READ)
        return self.transactions.run(
            TransactionContext(principal, Capability.READ),
            lambda tx: self.get(tx, RecordKind.PATCH, patch_id),
        )

    def require_published(self, tx, record):
        if self.publication is None:
            raise MemoryPatchError(ErrorCode.PROVENANCE_PENDING)
        event = require_record_audit(tx, record)
        outboxes = tx.scan(RecordKind.OUTBOX, limit=1024)
        if len(outboxes) >= 1024:
            raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
        matches = [r for r in outboxes if r.payload["event_id"] == event.audit_event_id]
        if len(matches) != 1 or matches[0].payload["state"] != "PUBLISHED":
            raise MemoryPatchError(ErrorCode.PROVENANCE_PENDING)
        return self.publication.verify(tx.context.principal, matches[0], event)

    def publish_pending(self, principal):
        self.core.require(principal, principal.capability)
        if principal.capability is Capability.READ:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        if self.publication is None:
            raise MemoryPatchError(ErrorCode.PROVENANCE_PENDING)

        def collect(tx):
            values = tx.scan(RecordKind.OUTBOX, limit=1024)
            if len(values) >= 1024:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            from runtime.memory_patch.audit import domain_chain

            verified_events = {
                event.audit_event_id: event for event in domain_chain(tx)
            }
            result = []
            for outbox in values:
                event = verified_events.get(outbox.payload["event_id"])
                if event is None:
                    raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
                result.append((outbox, event))
            return tuple(sorted(result, key=lambda pair: pair[1].sequence_number))

        values = self.transactions.run(
            TransactionContext(principal, principal.capability), collect
        )
        proofs = []
        for outbox, event in values:
            receipt = self.publication.publish(principal, outbox, event)

            def acknowledge(tx):
                current = tx.get(RecordKind.OUTBOX, outbox.record_id)
                return mark_published(tx, current, receipt)

            self.transactions.run(
                TransactionContext(principal, principal.capability), acknowledge
            )
            proofs.append(receipt.proof_id)
        return tuple(proofs)
