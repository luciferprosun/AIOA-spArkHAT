"""Patch evidence and exact owner decisions on the existing Core ports.

Selective W7A execution/capsule and workspace/verifier contract adaptation.
Source: 392487849eddc7444f5159994b66b72e73f15934; MIT notice in
runtime/nonzero_cloudops/LICENSE-NONZERO.txt. No executable route is registered
here. The receipt signer is the existing Native Identity, injected by its host.
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field

from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.contracts import bounded_int, logical_id
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.liability import Reconciliation
from runtime.mission.patchset import BoundedPatchSetPolicy, SourceIdentity
from runtime.mission.repair import (
    TEST_STAGES,
    RepairLoopResult,
    digest,
    semantic_review,
)
from runtime.mission.warrant import require
from runtime.mission.worker import Task
from runtime.mobile_gateway.wire import Identity, verify

KIND = "aioa.patch-capsule.v1"


@dataclass(frozen=True, slots=True)
class ExecutionCapsule:
    task_id: str
    run_id: str
    workspace_id: str
    repository_id: str
    worker_session_id: str
    source_base_sha: str
    base_tree_sha256: str
    final_tree_sha256: str
    task_digest: str
    patchset_sha256: str
    loop_receipt_sha256: str
    test_profile_digest: str
    owner_scope_sha256: str
    validation_warrants: tuple[str, ...]
    validation_receipts: tuple[str, ...]
    issued_at: int
    expires_at: int
    target_fingerprint: str
    target_revision: str
    digest: str = field(init=False, default="")

    def __post_init__(self):
        for name in (
            "task_id",
            "run_id",
            "workspace_id",
            "repository_id",
            "worker_session_id",
            "target_revision",
        ):
            logical_id(getattr(self, name))
        require(
            type(self.source_base_sha) is str
            and re.fullmatch("[a-f0-9]{40}", self.source_base_sha),
            "CAPSULE_SOURCE",
        )
        for name in (
            "base_tree_sha256",
            "final_tree_sha256",
            "task_digest",
            "patchset_sha256",
            "loop_receipt_sha256",
            "test_profile_digest",
            "owner_scope_sha256",
        ):
            digest(getattr(self, name))
        require(
            type(self.target_fingerprint) is str
            and re.fullmatch("sha256:[a-f0-9]{64}", self.target_fingerprint),
            "CAPSULE_TARGET",
        )
        for proof, prefixed in (
            (self.validation_warrants, True),
            (self.validation_receipts, False),
        ):
            require(
                type(proof) is tuple and len(proof) == len(set(proof)) == 3,
                "CAPSULE_PROOFS",
            )
            for value in proof:
                require(type(value) is str, "CAPSULE_PROOFS")
                if prefixed:
                    require(value.startswith("sha256:"), "CAPSULE_PROOFS")
                digest(value.removeprefix("sha256:") if prefixed else value)
        bounded_int(self.issued_at, 1, 2**53 - 1)
        bounded_int(self.expires_at, self.issued_at + 1, self.issued_at + 300)
        object.__setattr__(self, "digest", canonical_sha256(self.payload()))

    def payload(self):
        data = asdict(self)
        data.pop("digest")
        return json.loads(canonical_json_bytes({"schema": KIND, **data}))

    def verify_digest(self):
        require(self.digest == canonical_sha256(self.payload()), "CAPSULE_TAMPERED")
        data = asdict(self)
        data.pop("digest")
        require(type(self)(**data).digest == self.digest, "CAPSULE_TAMPERED")

    @property
    def authority(self):
        return "NONE"


def capsule_operation(capsule):
    capsule.verify_digest()
    return {
        "operation_class": "PROJECT_PATCH_PROPOSAL_V1",
        "target_fingerprint": capsule.target_fingerprint,
        "expected_target_revision": capsule.target_revision,
        "payload": {
            "schema": "aioa.patch-proposal.v1",
            "capsule_digest": capsule.digest,
            "repository_id": capsule.repository_id,
            "source_base_sha": capsule.source_base_sha,
            "patchset_sha256": capsule.patchset_sha256,
            "postimage_tree_sha256": capsule.final_tree_sha256,
        },
    }


def capsule_dependencies(capsule):
    capsule.verify_digest()
    return DecisionDependencyRoot(
        (
            EvidenceRef("patch-capsule", "task", "sha256:" + capsule.digest, "v1"),
            EvidenceRef(
                "patch-base",
                "context",
                "sha256:" + capsule.base_tree_sha256,
                capsule.source_base_sha,
            ),
        )
    )


class CorePatchCapsules:
    def __init__(self, journal, identity, *, source_probe, target_guard=nullcontext):
        require(
            type(journal) is CoreIntentJournal
            and type(identity) is Identity
            and callable(source_probe)
            and callable(target_guard),
            "CORE_CAPSULE_BINDINGS",
        )
        self.journal, self.identity, self.source_probe, self.target_guard = (
            journal,
            identity,
            source_probe,
            target_guard,
        )

    @property
    def scope(self):
        return self.journal.ledger.scope

    def _fresh(self, capsule):
        capsule.verify_digest()
        now = int(self.journal.ledger.clock().timestamp())
        require(capsule.issued_at <= now < capsule.expires_at, "CAPSULE_EXPIRED")
        observed = self.source_probe()
        require(
            type(observed) is SourceIdentity
            and observed
            == SourceIdentity(
                capsule.repository_id,
                capsule.workspace_id,
                capsule.source_base_sha,
                capsule.base_tree_sha256,
            ),
            "CAPSULE_SOURCE_DRIFT",
        )

    def prepare(
        self,
        principal,
        *,
        task,
        source,
        base_root,
        final_root,
        result,
        target_fingerprint,
        target_revision,
        expires_at,
    ):
        self.journal.ledger.core.require(principal, Capability.COMMIT, scope=self.scope)
        require(
            type(task) is Task
            and type(source) is SourceIdentity
            and type(result) is RepairLoopResult
            and result.status == "PATCH_READY",
            "CAPSULE_VERIFIED_PATCH_REQUIRED",
        )
        loop = asdict(result)
        loop.pop("receipt_sha256")
        require(
            canonical_sha256(loop) == result.receipt_sha256, "CAPSULE_LOOP_TAMPERED"
        )
        patch = result.final_patchset
        require(
            (result.task_id, result.run_id) == (task.task_id, task.run_id),
            "CAPSULE_TASK_BINDING",
        )
        steps = result.attempts[-1].steps
        require(
            tuple(s.stage for s in steps) == TEST_STAGES
            and all(
                s.status == "PASS" and s.core_warrant_digest is not None for s in steps
            ),
            "CAPSULE_CORE_PROOFS_REQUIRED",
        )
        capsule = ExecutionCapsule(
            task.task_id,
            task.run_id,
            task.workspace_id,
            task.repository_id,
            patch.worker_session_id,
            patch.source_base_sha,
            patch.base_tree_sha256,
            patch.final_tree_sha256,
            task.digest,
            patch.patchset_sha256,
            result.receipt_sha256,
            steps[0].profile_digest,
            canonical_sha256(self.scope),
            tuple(s.core_warrant_digest for s in steps),
            tuple(s.evidence_digest for s in steps),
            int(self.journal.ledger.clock().timestamp()),
            expires_at,
            target_fingerprint,
            target_revision,
        )
        require(expires_at <= task.deadline_at, "CAPSULE_TASK_EXPIRED")
        with self.target_guard():
            self._fresh(capsule)
            BoundedPatchSetPolicy().recheck(
                patch,
                base_root=base_root,
                final_root=final_root,
                source=source,
                task=task,
                worker_session_id=patch.worker_session_id,
            )
            require(semantic_review(patch) is None, "CAPSULE_REVIEW_DENIED")
            receipt = {
                "schema": "aioa.patch-review-receipt.v1",
                "state": "REVIEW_REQUIRED",
                "capsule": capsule.payload(),
                "capsule_digest": capsule.digest,
                "authority": "NONE",
            }
            signature = self.identity.sign(receipt)
            record = {
                "receipt": receipt,
                "signature": signature,
                "signer_spki": self.identity.spki,
            }

            def save(tx):
                for step in steps:
                    key = canonical_sha256(
                        ["aioa.trusted-validation.v1", step.core_warrant_digest]
                    )
                    row = tx.get(RecordKind.OPERATION, key)
                    require(row is not None, "CAPSULE_CORE_PROOFS_REQUIRED")
                    data = json.loads(canonical_json_bytes(row.payload))
                    require(
                        data.get("schema") == "aioa.trusted-validation.v1"
                        and data["stage"] == step.stage
                        and data["status"] == "PASS"
                        and data["exit_code"] == 0
                        and data["patchset_sha256"] == patch.patchset_sha256
                        and data["profile_digest"] == capsule.test_profile_digest
                        and data["warrant_digest"] == step.core_warrant_digest
                        and data["evidence_digest"] == step.evidence_digest,
                        "CAPSULE_PROOF_BINDING",
                    )
                    warrant = EffectWarrant.from_dict(data["warrant"])
                    require(
                        warrant.digest() == step.core_warrant_digest,
                        "CAPSULE_PROOF_BINDING",
                    )
                    _, intent = self.journal._load(tx, warrant)
                    require(
                        intent is not None and intent["resolution"] is not None,
                        "CAPSULE_UNKNOWN_PROOF",
                    )
                    resolution = Reconciliation.from_dict(intent["resolution"])
                    require(
                        resolution.outcome.to_dict()["contract_type"] == "Applied"
                        and resolution.receipt.digest
                        == "sha256:" + step.evidence_digest
                        and resolution.operation_digest == data["operation_digest"],
                        "CAPSULE_UNKNOWN_PROOF",
                    )
                key = canonical_sha256([KIND, capsule.digest])
                prior = tx.get(RecordKind.OPERATION, key)
                if prior is not None:
                    # ECDSA signatures are randomized. Reuse the first durable
                    # signed record rather than replacing its evidence on retry.
                    self._decode(prior)
                    return json.loads(canonical_json_bytes(prior.payload))
                row = StoredRecord(RecordKind.OPERATION, key, self.scope, 1, record)
                tx.insert(row)
                binding = OperationBinding.bind(
                    "capsule-" + key,
                    "PATCH_REVIEW_READY",
                    {"capsule_digest": capsule.digest},
                )
                append_domain_event(
                    tx,
                    binding,
                    event_id="capsule-audit-" + key,
                    proof_id="capsule-outbox-" + key,
                    resource_id=key,
                    before=None,
                    after="REVIEW_REQUIRED",
                    content_digest=row.payload_digest,
                    at=self.journal.ledger.clock(),
                )
                return record

            return self.journal._run(principal, Capability.COMMIT, save)

    def _decode(self, row):
        data = json.loads(canonical_json_bytes(row.payload))
        require(
            set(data) == {"receipt", "signature", "signer_spki"}
            and data["signer_spki"] == self.identity.spki,
            "CAPSULE_SIGNER",
        )
        verify(self.identity.spki, data["signature"], data["receipt"])
        receipt = data["receipt"]
        require(
            set(receipt)
            == {"schema", "state", "capsule", "capsule_digest", "authority"}
            and receipt["schema"] == "aioa.patch-review-receipt.v1"
            and receipt["state"] == "REVIEW_REQUIRED"
            and receipt["authority"] == "NONE",
            "CAPSULE_RECEIPT",
        )
        payload = dict(receipt["capsule"])
        require(payload.pop("schema") == KIND, "CAPSULE_RECEIPT")
        payload["validation_warrants"] = tuple(payload["validation_warrants"])
        payload["validation_receipts"] = tuple(payload["validation_receipts"])
        capsule = ExecutionCapsule(**payload)
        require(
            capsule.digest == receipt["capsule_digest"]
            and capsule.owner_scope_sha256 == canonical_sha256(self.scope)
            and row.record_id == canonical_sha256([KIND, capsule.digest]),
            "CAPSULE_RECEIPT",
        )
        return capsule

    def read(self, principal, capsule_digest):
        digest(capsule_digest)

        def read(tx):
            row = tx.get(RecordKind.OPERATION, canonical_sha256([KIND, capsule_digest]))
            require(row is not None, "CAPSULE_REQUIRED")
            self._decode(row)
            return json.loads(canonical_json_bytes(row.payload))

        return self.journal._run(principal, Capability.READ, read)

    def _bound(self, tx, capsule_digest, warrant):
        row = tx.get(RecordKind.OPERATION, canonical_sha256([KIND, capsule_digest]))
        require(row is not None, "CAPSULE_REQUIRED")
        capsule = self._decode(row)
        require(
            type(warrant) is EffectWarrant
            and warrant.task_id == capsule.task_id
            and warrant.operation_hash
            == "sha256:" + canonical_sha256(capsule_operation(capsule))
            and warrant.operation_class == "PROJECT_PATCH_PROPOSAL_V1"
            and warrant.target_fingerprint == capsule.target_fingerprint
            and warrant.expected_target_revision == capsule.target_revision
            and warrant.decision_dependency_root == capsule_dependencies(capsule)
            and int(warrant.expires_at.timestamp()) <= capsule.expires_at,
            "CAPSULE_APPROVAL_SWAP",
        )
        return capsule

    def approve(self, principal, capsule_digest, warrant):
        self.journal.ledger.core.require(
            principal, Capability.OWNER_APPROVAL, scope=self.scope
        )
        digest(capsule_digest)
        with self.target_guard():
            capsule = self.journal._run(
                principal,
                Capability.OWNER_APPROVAL,
                lambda tx: self._bound(tx, capsule_digest, warrant),
            )
            self._fresh(capsule)
            # No second approval record. Lost ACK is inspected in this ledger;
            # neither this method nor the capsule can execute a patch.
            self.journal.ledger.approve(principal, warrant)
        return {
            "status": "OWNER_WARRANT_RECORDED",
            "warrant_digest": warrant.digest(),
            "authority": "NONE",
        }

    def require_approved(self, principal, capsule_digest, warrant):
        with self.target_guard():
            capsule = self.journal._run(
                principal,
                Capability.COMMIT,
                lambda tx: self._bound(tx, capsule_digest, warrant),
            )
            self._fresh(capsule)

            def read(tx):
                self._bound(tx, capsule_digest, warrant)
                self.journal.ledger.require_active_in_transaction(tx, warrant)
                return {
                    "status": "APPROVED",
                    "authority": "NONE",
                    "dispatch_registered": False,
                }

            return self.journal._run(principal, Capability.COMMIT, read)
