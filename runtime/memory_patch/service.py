"""One lazy native service, composed only from explicitly injected Core ports."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from runtime.core_admission import CoreAdmission
from runtime.evidence_admission import CoreEvidenceAdmission, EvidenceAdmissionError
from runtime.memory_patch.audit import CoreLedgerPublication
from runtime.memory_patch.contract import (
    module_descriptor,
    operation_capability,
    snapshot_config,
)
from runtime.memory_patch.contracts.enums import (
    ApprovalDecision,
    MemoryContentKind,
    PatchState,
    PersonalMemorySpaceState,
)
from runtime.memory_patch.contracts.records import PersonalHatQuotaPolicy
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.correction.answers import NativeAnswerAssembler
from runtime.memory_patch.correction.claims import NativeClaims, NativeDraft
from runtime.memory_patch.correction.packets import NativePacketIntegrity
from runtime.memory_patch.correction.verification import NativeVerifier
from runtime.memory_patch.critic_adapter import NativeCriticAdapter
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.hats import NativeHatAdmission
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    TransactionContext,
    TransactionRunner,
)
from runtime.memory_patch.personal.approval import NativeOwnerApproval
from runtime.memory_patch.personal.candidates import NativeCandidates
from runtime.memory_patch.personal.commit import (
    NativeCommit,
    require_active,
    require_commit,
)
from runtime.memory_patch.personal.contracts import (
    CandidateDraft,
    SlotConfiguration,
    instant,
)
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle
from runtime.memory_patch.personal.management import NativeMemoryManagement
from runtime.memory_patch.personal.proposals import (
    CorePersonalEvidence,
    NativeProposals,
)
from runtime.memory_patch.personal.retrieval import NativeMemoryRetrieval
from runtime.memory_patch.provider_adapter import NativeProviderAdapter
from runtime.memory_patch.retrieval.contracts import (
    HybridRetrievalRequest,
    bounded_text,
)
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.memory_patch.retrieval.temporal import TemporalQueryMode
from runtime.memory_patch.review import NativeReview, ReviewDecision
from runtime.memory_patch.views import (
    ProjectionContext,
    approval_challenge_view,
    approval_decision_view,
    commit_activation_view,
    envelope,
    error_response,
    migration_plan_view,
    opaque_id,
    owner_memory_space_view,
    patch_view,
    review_case_view,
    verified_answer_view,
)


@dataclass(frozen=True, slots=True, repr=False)
class CoreMemoryPatchDependencies:
    """Only the trusted Core composition root may supply ports or credentials.

    This is never parsed from JSON or environment variables. Constructors do not
    call a port. The provider, HAT selection, catalog and provenance store already
    belong to the existing Core; close never disposes those borrowed resources.
    """

    transaction_factory: object | None = None
    owns_transaction_factory: bool = False
    evidence_catalog: object | None = None
    sources: object | None = None
    bundle_resolver: object | None = None
    provenance_store: object | None = None
    hat_manifests: tuple = ()
    quota: PersonalHatQuotaPolicy | None = None
    freshness: object | None = None
    provider_binding: object | None = None
    packet_key: bytes | None = None
    packet_key_id: str = "core-memory-patch-ephemeral"
    migration_plans: tuple = ()
    private_values: tuple[str, ...] = ()
    clock: object | None = None

    def __post_init__(self):
        if (
            type(self.owns_transaction_factory) is not bool
            or type(self.hat_manifests) is not tuple
            or type(self.migration_plans) is not tuple
            or type(self.private_values) is not tuple
            or len(self.private_values) > 1024
            or any(
                not isinstance(value, str) or not 1 <= len(value) <= 4096
                for value in self.private_values
            )
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)


_PATCH_INPUT = frozenset({"patch_id", "expected_revision", "operation_key"})
_SHAPES = {
    "status": (set(), set()),
    "read": ({"patch_id"}, set()),
    "trace": ({"patch_id"}, set()),
    "recover": ({"patch_id"}, set()),
    "list": (set(), set()),
    "export": ({"operation_key"}, set()),
    "publish": (set(), set()),
    "initialize-publication": (set(), set()),
    "slot-create": ({"operation_key"}, set()),
    "slot-configure": ({"hat_id", "expected_revision", "operation_key"}, set()),
    "slot-state": ({"state", "expected_revision", "operation_key"}, set()),
    "candidate": (
        {"title", "summary", "body", "content_kind", "hat_id", "operation_key"},
        {
            "evidence_references",
            "valid_from",
            "valid_until",
            "expires_at",
            "supersedes_patch_id",
        },
    ),
    "critic-candidate": ({"run_id", "hat_id", "operation_key"}, set()),
    **{
        name: (_PATCH_INPUT, set())
        for name in (
            "propose",
            "bind-evidence",
            "validate",
            "await-approval",
            "challenge",
            "commit",
            "activate",
            "revoke",
            "review-open",
        )
    },
    "decision": (
        {
            "challenge_id",
            "expected_revision",
            "decision",
            "decision_nonce",
            "operation_key",
        },
        set(),
    ),
    "supersede": (
        {"old_patch_id", "new_patch_id", "expected_revision", "operation_key"},
        set(),
    ),
    "sharing": (_PATCH_INPUT | {"consent", "deidentified_summary"}, set()),
    "review-queue": (set(), set()),
    "review-claim": ({"case_id", "expected_revision", "operation_key"}, set()),
    "review-decision": (
        {"case_id", "expected_revision", "decision", "operation_key"},
        set(),
    ),
    "retrieve": ({"hat_id", "query"}, {"temporal_mode", "as_of"}),
    "answer": (
        {"hat_id", "query", "draft", "operation_key"},
        {"temporal_mode", "as_of"},
    ),
    "migration-plan": ({"plan_id"}, set()),
    "migrate": ({"plan_id"}, set()),
}


def validate_request(operation, payload):
    if (
        type(operation) is not str
        or operation not in _SHAPES
        or type(payload) is not dict
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    required, optional = _SHAPES[operation]
    if (
        not required <= set(payload)
        or set(payload) - required - optional
        or len(canonical_json_bytes(payload)) > 24000
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    if "operation_key" in payload:
        bounded_text(payload["operation_key"], 128)
    if "expected_revision" in payload and (
        type(payload["expected_revision"]) is not int
        or not 1 <= payload["expected_revision"] <= 2147483647
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    for field, prefix in (
        ("patch_id", "patch"),
        ("old_patch_id", "patch"),
        ("new_patch_id", "patch"),
        ("supersedes_patch_id", "patch"),
        ("case_id", "case"),
        ("challenge_id", "challenge"),
    ):
        if field in payload and payload[field] is not None:
            opaque_id(payload[field], prefix)


class MemoryPatchService:
    def __init__(
        self,
        core: CoreAdmission,
        *,
        config=None,
        dependencies=None,
        existing_provider_manager=None,
        existing_hat_selection=None,
        existing_critic=None,
    ):
        self.core, self.config = core, snapshot_config(config)
        self.dependencies = (
            dependencies if dependencies is not None else CoreMemoryPatchDependencies()
        )
        if type(self.dependencies) is not CoreMemoryPatchDependencies:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        d = self.dependencies
        self._closed = False
        self._lock = threading.RLock()
        self._answer_packets = {}
        self.transactions = TransactionRunner(
            core, d.transaction_factory, owns_factory=d.owns_transaction_factory
        )
        self.evidence = CoreEvidenceAdmission(core, d.evidence_catalog, clock=d.clock)
        self.retrieval = NativeRetrieval(
            core, self.evidence, d.sources, freshness=d.freshness, clock=d.clock
        )
        self.claims = NativeClaims(core, self.retrieval)
        self.hats = (
            None
            if not d.hat_manifests or d.quota is None or existing_hat_selection is None
            else NativeHatAdmission(
                core, existing_hat_selection, d.hat_manifests, quota=d.quota
            )
        )
        self.publication = (
            None
            if d.provenance_store is None
            else CoreLedgerPublication(core, d.provenance_store)
        )
        self.lifecycle = NativeMemoryLifecycle(
            core,
            self.transactions,
            hats=self.hats,
            evidence=CorePersonalEvidence(self.claims, d.bundle_resolver),
            publication=self.publication,
            clock=d.clock,
        )
        self.candidates = NativeCandidates(self.lifecycle)
        self.proposals = NativeProposals(self.lifecycle)
        self.approval = NativeOwnerApproval(self.lifecycle)
        self.commit = NativeCommit(self.lifecycle)
        self.management = NativeMemoryManagement(self.lifecycle)
        self.personal = NativeMemoryRetrieval(self.lifecycle, self.claims)
        self.retrieval.personal = self.personal
        self.review = NativeReview(self.lifecycle, self.evidence)
        self.critic = NativeCriticAdapter(core, self.candidates, existing_critic)
        self.provider = NativeProviderAdapter(
            core, existing_provider_manager, d.provider_binding
        )
        self.integrity = (
            None
            if d.packet_key is None
            else NativePacketIntegrity(
                core,
                self.claims,
                key_id=d.packet_key_id,
                key_material=d.packet_key,
                clock=d.clock,
            )
        )
        self.answers = (
            None
            if self.integrity is None
            else NativeAnswerAssembler(
                NativeVerifier(self.claims, self.integrity), self.provider
            )
        )

    def status(self):
        return module_descriptor(
            self.config, configured=self.transactions.configured, closed=self._closed
        )

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self.integrity is not None:
                self.integrity.close()
            if self.answers is not None:
                self.answers.close()
            self._answer_packets.clear()
            self.transactions.close()

    def request(self, principal, operation, payload):
        try:
            with self._lock:
                validate_request(operation, payload)
                if self._closed:
                    raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
                if operation == "status":
                    return 200, envelope(operation, result=self.status())
                if not self.config.enabled:
                    raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
                self.core.require(principal, operation_capability(operation))
                result = self._dispatch(principal, operation, payload)
                self.core.require(principal, operation_capability(operation))
                return 200, envelope(operation, result=result)
        except Exception as error:
            return error_response(operation, error)

    def _context(self, principal, *, extra=()):
        return ProjectionContext(
            self.core, principal, (*self.dependencies.private_values, *extra)
        )

    def _read(self, principal, function):
        return self.transactions.run(
            TransactionContext(principal, principal.capability), function
        )

    def _published(self, principal):
        self.lifecycle.publish_pending(principal)

    def _patch(self, tx, patch, *, commitment=False):
        principal = tx.context.principal
        ctx = self._context(principal)
        candidate = CandidateDraft.from_private(patch.payload["candidate"])
        if candidate.hat_id not in principal.hat_ids:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        refs = []
        source_private = []
        verification = "UNVERIFIED"
        proof = None
        for reference in candidate.evidence_references:
            try:
                captured = self.evidence.require_evidence(principal, reference)
                source_private.extend(
                    (
                        captured.source.source_id,
                        captured.source.source_version_id,
                        captured.record_digest,
                        captured.capture_intent_id,
                    )
                )
                refs.append(reference)
            except EvidenceAdmissionError:
                pass
        try:
            if patch.payload["state"] == "ACTIVE":
                proof = require_active(self.lifecycle, tx, patch).proof_id
                verification = patch.payload["evidence_binding"]["verification_status"]
            elif patch.payload["state"] == "COMMITTED":
                require_commit(self.lifecycle, tx, patch)
                proof = self.lifecycle.require_published(tx, patch).proof_id
            else:
                self.lifecycle.require_published(tx, patch)
        except MemoryPatchError as error:
            if error.code is ErrorCode.PROVENANCE_PENDING:
                verification = "PROVENANCE_PENDING"
            elif error.code in {
                ErrorCode.EVIDENCE_DENIED,
                ErrorCode.STATE_CONFLICT,
                ErrorCode.CHALLENGE_DENIED,
            }:
                verification = "REVIEW_REQUIRED"
            else:
                raise
        except EvidenceAdmissionError:
            verification = "REVIEW_REQUIRED"
        if commitment:
            return commit_activation_view(
                ctx, patch, proof_id=proof, verification=verification
            )
        return patch_view(
            self._context(principal, extra=tuple(source_private)),
            patch,
            sources=tuple(refs),
            verification=verification,
        )

    def _patch_by_id(self, principal, patch_id, *, commitment=False):
        return self._read(
            principal,
            lambda tx: self._patch(
                tx,
                self.lifecycle.get(tx, RecordKind.PATCH, patch_id),
                commitment=commitment,
            ),
        )

    def _space(self, principal, *, selected=None, export=False):
        def read(tx):
            space = self.lifecycle.get(tx, RecordKind.SPACE, "owner-memory-slot")
            records = tx.scan(RecordKind.PATCH, limit=129)
            if len(records) > 128:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            patches = []
            active_count, bytes_used = 0, 0
            for record in records:
                record = self.lifecycle.get(tx, RecordKind.PATCH, record.record_id)
                active_count += (
                    record.payload["state"] == "ACTIVE"
                    and not record.payload["logically_deleted"]
                )
                if not record.payload["logically_deleted"]:
                    bytes_used += len(canonical_json_bytes(record.payload["candidate"]))
                if (
                    record.payload["logically_deleted"]
                    or selected is not None
                    and record.record_id not in selected
                ):
                    continue
                if export and record.payload["state"] not in {
                    "APPROVED",
                    "COMMITTED",
                    "ACTIVE",
                    "REVOKED",
                    "SUPERSEDED",
                }:
                    continue
                patches.append(self._patch(tx, record))
            return owner_memory_space_view(
                self._context(principal),
                space,
                patches,
                active_count=active_count,
                bytes_used=bytes_used,
            )

        return self._read(principal, read)

    def _dispatch(self, p, op, b):
        ctx = self._context(p)
        if op in {"migration-plan", "migrate"}:
            plan = next(
                (
                    plan
                    for plan in self.dependencies.migration_plans
                    if plan.plan_id == b["plan_id"]
                ),
                None,
            )
            if plan is None:
                raise MemoryPatchError(ErrorCode.NOT_FOUND)
            if op == "migrate":
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            return migration_plan_view(ctx, plan)
        if op == "initialize-publication":
            if self.publication is None:
                raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
            self.publication.initialize(p)
            return self.status()
        if not self.transactions.configured:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        if op in {"read", "trace", "recover"}:
            return self._patch_by_id(p, b["patch_id"], commitment=op == "recover")
        if op == "list":
            return self._space(p)
        if op == "publish":
            self._published(p)
            return self._space(p)
        if op == "export":
            self.management.export_snapshot(p, operation_key=b["operation_key"])
            self._published(p)
            return self._space(p, export=True)
        if op == "slot-create":
            self.management.create_slot(p, operation_key=b["operation_key"])
            self._published(p)
            return self._space(p)
        if op == "slot-configure":
            if self.hats is None:
                raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
            binding = self.hats.selected(p, b["hat_id"])
            self.management.configure_slot(
                p,
                SlotConfiguration(
                    binding.hat_id,
                    tuple(sorted(binding.model_binding_ids)),
                    binding.quota,
                ),
                expected_revision=b["expected_revision"],
                operation_key=b["operation_key"],
            )
            self._published(p)
            return self._space(p)
        if op == "slot-state":
            self.management.change_slot_state(
                p,
                target=PersonalMemorySpaceState(b["state"]),
                expected_revision=b["expected_revision"],
                operation_key=b["operation_key"],
            )
            self._published(p)
            return self._space(p)
        if op == "candidate":
            references = b.get("evidence_references", [])
            if type(references) is not list or len(references) > 32:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            for reference in references:
                opaque_id(reference, "evidence")
                self.evidence.require_evidence(p, reference)
            candidate = CandidateDraft(
                b["title"],
                b["summary"],
                b["body"],
                MemoryContentKind(b["content_kind"]),
                b["hat_id"],
                tuple(sorted(p.model_binding_ids)),
                tuple(references),
                instant(b.get("valid_from")),
                instant(b.get("valid_until")),
                instant(b.get("expires_at")),
                b.get("supersedes_patch_id"),
            )
            outcome = self.candidates.intake(
                p, candidate, operation_key=b["operation_key"]
            )
        elif op == "critic-candidate":
            outcome = self.critic.candidate_from_run(
                p, b["run_id"], hat_id=b["hat_id"], operation_key=b["operation_key"]
            )
        elif op in {"propose", "bind-evidence", "validate", "await-approval"}:
            targets = {
                "propose": PatchState.PROPOSED,
                "bind-evidence": PatchState.EVIDENCE_BOUND,
                "validate": PatchState.VALIDATED,
                "await-approval": PatchState.AWAITING_APPROVAL,
            }
            outcome = self.proposals.advance(p, target=targets[op], **b)
        elif op == "challenge":
            challenge = self.approval.challenge(p, **b)
            self._published(p)
            return approval_challenge_view(ctx, challenge)
        elif op == "decision":
            self.approval.decide(
                p, **{**b, "decision": ApprovalDecision(b["decision"])}
            )
            self._published(p)

            def read_decision(tx):
                challenge = self.lifecycle.get(
                    tx, RecordKind.CHALLENGE, b["challenge_id"]
                )
                patch = self.lifecycle.get(
                    tx, RecordKind.PATCH, challenge.payload["patch_id"]
                )
                return approval_decision_view(ctx, challenge, patch)

            return self._read(p, read_decision)
        elif op in {"commit", "activate"}:
            outcome = (self.commit.commit if op == "commit" else self.commit.activate)(
                p, **b
            )
        elif op == "revoke":
            outcome = self.management.revoke(p, **b)
        elif op == "supersede":
            outcome = self.management.supersede(p, **b)
        elif op in {"sharing", "review-open", "review-claim", "review-decision"}:
            if op == "sharing":
                outcome = self.management.propose_sharing(p, **b)
            elif op == "review-open":
                outcome = self.review.open_case(p, **b)
            elif op == "review-claim":
                outcome = self.review.claim(p, **b)
            else:
                outcome = self.review.decide(
                    p, **{**b, "decision": ReviewDecision(b["decision"])}
                )
            self._published(p)
            kind = RecordKind.SHARING if op == "sharing" else RecordKind.REVIEW
            return self._read(
                p,
                lambda tx: review_case_view(
                    ctx, self.lifecycle.get(tx, kind, outcome.outcome["case_id"])
                ),
            )
        elif op == "review-queue":
            return [review_case_view(ctx, case) for case in self.review.queue(p)]
        elif op in {"retrieve", "answer"}:
            request = HybridRetrievalRequest.admitted(
                self.core, p, hat_id=b["hat_id"], query=b["query"]
            )
            mode = TemporalQueryMode(b.get("temporal_mode", "CURRENT"))
            lanes = self.retrieval.retrieve(
                p, request, mode=mode, as_of=instant(b.get("as_of"))
            )
            if op == "retrieve":
                return self._space(
                    p, selected={item.patch_id for item in lanes.personal_context}
                )
            if self.answers is None:
                raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
            draft = NativeDraft(p.scope, b["hat_id"], "operator-draft", b["draft"])
            key = (p.scope.binding(), b["operation_key"])
            request_binding = canonical_sha256(
                {"request": b, "bundle": lanes.canonical_evidence.bundle_hash}
            )
            prior = self._answer_packets.get(key)
            if prior is not None:
                if prior[0] != request_binding:
                    raise MemoryPatchError(ErrorCode.IDEMPOTENCY_CONFLICT)
                packet, receipt = prior[1:]
            else:
                if len(self._answer_packets) >= 1024:
                    raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
                packet, receipt = self.integrity.build(
                    p,
                    draft,
                    lanes.canonical_evidence,
                    mode=mode,
                    as_of=instant(b.get("as_of")),
                )
                self._answer_packets[key] = (request_binding, packet, receipt)
            answer = self.answers.answer(
                p,
                packet,
                receipt,
                lanes.canonical_evidence,
                operation_id=b["operation_key"],
            )
            self.retrieval.require_bundle(p, lanes.canonical_evidence)
            bindings = dict(lanes.canonical_evidence.core_evidence_bindings)
            citations = tuple(
                dict.fromkeys(bindings[item] for item in answer.citations)
            )
            source_private = []
            for reference in citations:
                captured = self.evidence.require_evidence(p, reference)
                source_private.extend(
                    (
                        captured.source.source_id,
                        captured.source.source_version_id,
                        captured.capture_intent_id,
                        captured.record_digest,
                    )
                )
            return verified_answer_view(
                self._context(p, extra=tuple(source_private)),
                answer,
                citations=citations,
            )
        else:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self._published(p)
        # Operation history is never a current lifecycle read model. In particular,
        # replay of an old activation after revocation must return REVOKED now.
        return self._patch_by_id(
            p, outcome.outcome["patch_id"], commitment=op in {"commit", "activate"}
        )
