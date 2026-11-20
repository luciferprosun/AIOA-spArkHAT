"""Opt-in coding intake on the existing Core transaction and receipt ports.

No server, model credential, executor, default database or automatic principal.
Pending tasks are advisory; only existing Core-signed capsules can reach review.
Execution/STOP remain on the existing registered Native routes.
"""

import json
import hmac
from contextlib import contextmanager
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from runtime.core_admission import Capability, CoreActor, OwnerScope
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.contracts import logical_id
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.patch_capsule import KIND as CAPSULE_KIND
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.warrant import WarrantError, require
from runtime.mission.worker import Task
from runtime.mobile_gateway.wire import verify
from runtime.providers.coding_contracts import (
    CodingBackendBindingV1,
    CodingBackendChoiceV1,
    CodingBackendRegistry,
    CodingRunPolicyV1,
)

KIND = "aioa.coding-task.v1"
HISTORY_LIMIT = 1024
STATES = (
    "QUEUED",
    "RUNNING",
    "VALIDATING",
    "PLANNED",
    "PATCH_READY",
    "TESTING",
    "REPAIRING",
    "REVIEW_REQUIRED",
    "APPROVED",
    "APPLYING",
    "VERIFIED",
    "DENIED",
    "UNKNOWN",
    "FAILED",
    "CANCELLED",
)


@dataclass(frozen=True, slots=True)
class CodingRun:
    """Host-injected run binding; never accepted from model/HTTP JSON."""

    producer: object
    validator: object
    base_root: Path
    source: object
    target_fingerprint: str
    target_revision: str
    expires_at: int

    def __post_init__(self):
        from runtime.mission.patchset import SourceIdentity
        from runtime.mission.repair import SandboxedCandidateProducer
        from runtime.mission.repair_validation import CoreSandboxValidation

        require(
            type(self.producer) is SandboxedCandidateProducer
            and type(self.validator) is CoreSandboxValidation
            and type(self.source) is SourceIdentity
            and isinstance(self.base_root, Path)
            and self.base_root.is_absolute(),
            "CODING_RUN_BINDING",
        )
        materializer = self.producer.materializer
        snapshot = materializer.source_snapshot
        require(
            self.validator.journal is materializer.journal
            and self.validator.profile is not None
            and self.validator.profile.digest == materializer.profile.digest
            and self.base_root == materializer.base_root
            and self.source
            == SourceIdentity(
                snapshot.repository_id,
                snapshot.workspace_id,
                snapshot.source_base_sha,
                snapshot.export_tree_sha256,
            ),
            "CODING_RUN_BINDING",
        )
        require(
            type(self.expires_at) is int
            and 1 <= self.expires_at <= self.producer.task.deadline_at,
            "CODING_RUN_EXPIRY",
        )
        logical_id(self.target_revision)


def decode_coding_task_row(row, task_id, signer_spki):
    """One pure receipt-chain decoder shared by controller and registered Git."""
    require(row is not None, "CODING_TASK_REQUIRED")
    data = json.loads(canonical_json_bytes(row.payload))
    require(
        set(data) == {"schema", "task", "task_digest", "receipts"}
        and data["schema"] == KIND,
        "CODING_TASK_INTEGRITY",
    )
    task = Task(**data["task"])
    require(
        task.task_id == task_id
        and task.digest == data["task_digest"]
        and type(data["receipts"]) is list
        and 1 <= len(data["receipts"]) <= 64,
        "CODING_TASK_INTEGRITY",
    )
    previous = "0" * 64
    for sequence, signed in enumerate(data["receipts"], 1):
        require(set(signed) == {"receipt", "signature"}, "CODING_TASK_INTEGRITY")
        proof = signed["receipt"]
        verify(signer_spki, signed["signature"], proof)
        require(
            set(proof)
            == {
                "schema",
                "task_digest",
                "sequence",
                "state",
                "previous",
                "capsule_digest",
            }
            and proof["schema"] == "aioa.coding-intake-receipt.v1"
            and proof["task_digest"] == task.digest
            and type(proof["sequence"]) is int
            and proof["sequence"] == sequence
            and proof["previous"] == previous
            and proof["state"] in STATES,
            "CODING_TASK_INTEGRITY",
        )
        previous = canonical_sha256(signed)
    return row, data, task


def decode_coding_backend_binding_row(row, task, scope):
    """Pure strict historical decoder; a malformed present row never means absent."""
    try:
        require(type(row) is StoredRecord and type(task) is Task and type(scope) is OwnerScope,
                "CODING_BACKEND_BINDING_INTEGRITY")
        row.verify()
        require(row.kind is RecordKind.OPERATION and row.scope == scope
                and row.record_id == "coding-backend-" + task.digest
                and type(row.revision) is int and row.revision == 1,
                "CODING_BACKEND_BINDING_INTEGRITY")
        binding = CodingBackendBindingV1.from_json(canonical_json_bytes(row.payload))
        require(binding.to_dict()["task_digest"] == task.digest,
                "CODING_BACKEND_BINDING_INTEGRITY")
        return binding
    except (ValueError, TypeError, MemoryPatchError, OverflowError, RecursionError):
        raise WarrantError("CODING_BACKEND_BINDING_INTEGRITY") from None


@dataclass(frozen=True, slots=True)
class CodingWorkSnapshot:
    task_id: str
    kind: str
    thread_alive: bool
    done: bool
    cancel_requested: bool
    quarantined: bool


@dataclass(frozen=True, slots=True)
class CodingLifecycleSnapshot:
    closed: bool
    work: tuple[CodingWorkSnapshot, ...]


@dataclass(frozen=True, slots=True)
class CodingDrainReport:
    drained: bool
    quarantined: bool
    work: tuple[CodingWorkSnapshot, ...]


class CoreCodingTasks:
    def __init__(
        self,
        journal,
        capsules,
        *,
        run_factory=None,
        run_principal=None,
        effect_factory=None,
        clock=time.time,
        coding_backend_registry=None,
        coding_access=None,
        native_access=None,
    ):
        require(
            type(journal) is CoreIntentJournal
            and type(capsules) is CorePatchCapsules
            and capsules.journal is journal,
            "EXISTING_CORE_REQUIRED",
        )
        self.journal, self.capsules = journal, capsules
        self.native_access = native_access
        self.scope = journal.ledger.scope
        require((coding_backend_registry is None) == (coding_access is None),
                "CODING_BACKEND_HOST_BINDING")
        self.coding_backend_registry, self.coding_access = coding_backend_registry, coding_access
        if native_access is not None:
            self._require_native_binding()
            require(coding_access is None or coding_access is native_access, "CODING_NATIVE_ACCESS_BINDING")
        if coding_backend_registry is not None:
            self._require_coding_backend_host()
        require(
            callable(clock)
            and (run_factory is None or callable(run_factory))
            and (effect_factory is None or callable(effect_factory)),
            "CODING_HOST_BINDING",
        )
        require((run_factory is None) == (run_principal is None) if native_access is None
                else run_principal is None, "CODING_HOST_BINDING")
        if run_principal is not None:
            journal.ledger.core.require(
                run_principal, Capability.COMMIT, scope=self.scope
            )
        self.run_factory, self.run_principal, self.effect_factory, self.clock = (
            run_factory,
            run_principal,
            effect_factory,
            clock,
        )
        self._active_lock = threading.RLock()
        self._active, self._effects, self._effect_ownership = {}, {}, {}
        self.closed = False

    def _require_native_binding(self):
        from runtime.meta_hackathon.native_authority import NativeAuthorityFoundation, NativeCoreAccess
        access = self.native_access
        require(type(access) is NativeCoreAccess and type(access.foundation) is NativeAuthorityFoundation,
                "CODING_NATIVE_ACCESS_BINDING")
        f = access.foundation
        require(f.owner.foundation is f and f.access is access and self.journal is f.intent_journal
                and self.journal.ledger is f.ledger and self.capsules.identity is f.owner.identity,
                "CODING_NATIVE_ACCESS_BINDING")
        f.require_bindings()

    def _require_principal(self, principal, purpose, *, scope=None):
        core = self.journal.ledger.core
        if self.native_access is None:
            return core.require(principal, purpose, scope=scope or self.scope)
        # A stale genuine same-Core handle is only a caller identity. The next
        # boundary captures a NEW five-minute principal through original Native
        # qualification; this does not extend or reuse the expired principal.
        self._require_native_binding()
        if principal is not None:
            from runtime.core_admission import CorePrincipal
            require(type(principal) is CorePrincipal and principal.capability is purpose
                    and principal.scope == self.scope and principal.actor_session_id == core._session
                    and principal.assignment_revision == core._assignment.revision
                    and hmac.compare_digest(principal._seal, core._signature(principal)),
                    "CODING_NATIVE_PRINCIPAL_BINDING")
        return self.scope

    @contextmanager
    def _authority(self, purpose):
        if self.native_access is None:
            yield self.run_principal
            return
        from runtime.meta_hackathon.native_authority import NativeAccessUse, NativePhase
        self._require_native_binding()
        lifecycle = self.native_access.foundation.lifecycle
        use = (NativeAccessUse.READ if purpose is Capability.READ else
               NativeAccessUse.EXECUTION if lifecycle.phase is NativePhase.ACTIVE else NativeAccessUse.CONTROL)
        if (getattr(lifecycle._boundary, 'settlement_handle', None) is not None
                or lifecycle.phase in (NativePhase.DRAINING, NativePhase.QUARANTINED)
                and getattr(lifecycle._boundary, 'work_handle', None) is not None):
            use = NativeAccessUse.SETTLEMENT
        capture = self.native_access.capture(purpose, use=use)
        try:
            self.native_access.require_capture(capture, purpose)
            yield capture.principal
            self.native_access.require_capture(capture, purpose)
        finally:
            capture.close()

    def _run(self, principal, purpose, callback):
        if self.native_access is None:
            return self.journal._run(principal, purpose, callback)
        from runtime.meta_hackathon.native_authority import NativeAccessUse, NativePhase
        self._require_principal(principal, purpose)
        lifecycle = self.native_access.foundation.lifecycle
        use = (NativeAccessUse.READ if purpose is Capability.READ else
               NativeAccessUse.EXECUTION if lifecycle.phase is NativePhase.ACTIVE else NativeAccessUse.CONTROL)
        if (getattr(lifecycle._boundary, 'settlement_handle', None) is not None
                or lifecycle.phase in (NativePhase.DRAINING, NativePhase.QUARANTINED)
                and getattr(lifecycle._boundary, 'work_handle', None) is not None):
            use = NativeAccessUse.SETTLEMENT
        owned = getattr(lifecycle._boundary, 'coding_effect', None)
        if owned is not None:
            self._native_git_effect_check(owned['route'], owned['warrant'], purpose)
        capture = self.native_access.capture(purpose, use=use)
        try:
            def pure(tx):
                self.native_access.require_capture(capture, purpose, tx=tx)
                if owned is not None:
                    self._native_git_effect_check(owned['route'], owned['warrant'], purpose)
                try:
                    return callback(tx)
                finally:
                    if owned is not None:
                        self._native_git_effect_check(owned['route'], owned['warrant'], purpose)
                    self.native_access.require_capture(capture, purpose, tx=tx)
            return self.journal._run(capture.principal, purpose, pure)
        finally:
            capture.close()

    def _retire_finished(self):
        with self._active_lock:
            candidates = tuple((task_id, active) for task_id, active in self._active.items()
                               if active['done'].is_set() and not active['thread'].is_alive()
                               and not active.get('quarantined'))
        for task_id, active in candidates:
            handle = active.get('native_handle')
            if handle is not None and not self.native_access.foundation.lifecycle.retire_work(handle):
                continue
            with self._active_lock:
                if self._active.get(task_id) is active:
                    self._active.pop(task_id)

    def lifecycle_snapshot(self):
        self._retire_finished()
        with self._active_lock:
            retained = tuple((task_id, kind, (item,) + tuple(item.get('readbacks', ())))
                             for kind, mapping in (('RUN', self._active), ('EFFECT', self._effect_ownership))
                             for task_id, item in sorted(mapping.items()))
        # EFFECT is the retained family, not the identity of its old thread.
        work = tuple(CodingWorkSnapshot(task_id, kind,
                     any(item['thread'].is_alive() for item in family),
                     all(item['done'].is_set() and (kind == 'RUN' or item.get('returned')) for item in family),
                     all(item['cancel'].cancelled for item in family),
                     any(bool(item.get('quarantined')) for item in family))
                     for task_id, kind, family in retained)
        with self._active_lock:
            require(len(work) <= 4, "CODING_OWNERSHIP_LIMIT")
            return CodingLifecycleSnapshot(self.closed, work)

    def drain(self, timeout_seconds):
        require(type(timeout_seconds) in (int, float) and 0 <= timeout_seconds <= 30, "CODING_DRAIN_BOUND")
        with self._active_lock:
            self.closed = True
            work = (tuple(self._active.values()) + tuple(self._effect_ownership.values())
                    + tuple(child for item in self._effect_ownership.values()
                            for child in item.get('readbacks', ())))
            for item in work:
                item['cancel'].cancel()
        # Port cancellation and joins happen outside the controller/global lock.
        deadline = time.monotonic() + timeout_seconds
        for item in work:
            producer = item.get('producer')
            if producer is not None:
                try:
                    producer.stop()
                except Exception:
                    item['quarantined'] = True
            thread = item['thread']
            if thread is not threading.current_thread() and thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        snapshot = self.lifecycle_snapshot()
        return CodingDrainReport(not snapshot.work, bool(snapshot.work), snapshot.work)

    def _require_coding_backend_host(self):
        from runtime.meta_hackathon.native_authority import (
            NativeAuthorityFoundation,
            NativeCoreAccess,
        )

        access, registry = self.coding_access, self.coding_backend_registry
        require(type(access) is NativeCoreAccess and type(registry) is CodingBackendRegistry,
                "CODING_BACKEND_HOST_BINDING")
        foundation = access.foundation
        require(type(foundation) is NativeAuthorityFoundation
                and foundation.access is access
                and foundation.intent_journal is self.journal
                and foundation.owner.intent_journal is self.journal
                and foundation.ledger is self.journal.ledger
                and foundation.core is self.journal.ledger.core
                and foundation.runner is self.journal.ledger.runner
                and foundation.owner.core is foundation.core
                and foundation.owner.runner is foundation.runner
                and foundation.owner.ledger is foundation.ledger
                and self.capsules.identity is foundation.owner.identity,
                "CODING_BACKEND_HOST_BINDING")
        require(all(source == foundation.owner.source for source in registry._host_sources()),
                "CODING_BACKEND_SOURCE_BINDING")
        foundation.require_bindings()

    def bind_coding_backend(self, principal, task_id, choice, run_policy):
        """Publish once through the original Native capture and canonical journal."""
        from runtime.meta_hackathon.native_authority import NativeAccessUse

        require(not self.closed, "CODING_CONTROLLER_CLOSED")
        self._require_principal(principal, Capability.MANAGE, scope=self.scope)
        require(principal.actor is CoreActor.OWNER_HUMAN, "CODING_BACKEND_OWNER_REQUIRED")
        require(type(choice) is CodingBackendChoiceV1 and type(run_policy) is CodingRunPolicyV1,
                "CODING_BACKEND_DATA_REQUIRED")
        logical_id(task_id)
        self._require_coding_backend_host()
        access = self.coding_access
        capture = access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
        try:
            access.require_capture(capture, Capability.MANAGE)
            require(capture.use is NativeAccessUse.CONTROL
                    and capture.principal.actor_session_id == principal.actor_session_id
                    and capture.assignment_revision == principal.assignment_revision,
                    "CODING_BACKEND_CALLER_BINDING")
            profile = self.coding_backend_registry.resolve(choice)
            selection = profile.to_dict()
            require((selection["host_source"]["source_sha"],
                     selection["host_source"]["capsule_digest"]) == capture.source,
                    "CODING_BACKEND_SOURCE_BINDING")
            # Capture caller data once. Retryable, proven rollbacks cannot retarget
            # the choice, policy, session or initial timestamp.
            policy = CodingRunPolicyV1.from_dict(run_policy.to_dict()).to_dict()
            selected_at = int(time.time())
            session = canonical_sha256(principal.actor_session_id)

            def publish(tx):
                require(not self.closed, "CODING_CONTROLLER_CLOSED")
                self._require_coding_backend_host()
                access.require_capture(capture, Capability.MANAGE, tx=tx)
                self._require_principal(principal, Capability.MANAGE, scope=self.scope)
                _, data, task = self._load(tx, task_id)
                require(data["receipts"][-1]["receipt"]["state"] == "QUEUED",
                        "CODING_BACKEND_TASK_NOT_QUEUED")
                now, monotonic_now = time.time(), time.monotonic()
                require(policy["task_digest"] == task.digest
                        and policy["selection_digest"] == profile.selection_digest,
                        "CODING_BACKEND_POLICY_BINDING")
                require(policy["issued_at"] <= selected_at <= now < policy["expires_at"]
                        and policy["expires_at"] <= task.deadline_at
                        and policy["expires_at"] <= principal.expires_at.timestamp()
                        and policy["expires_at"] <= capture.principal.expires_at.timestamp()
                        and policy["expires_at"] <= capture.tls_expires
                        and policy["expires_at"] <= now + (capture.auth_deadline - monotonic_now),
                        "CODING_BACKEND_POLICY_EXPIRED")
                row = tx.get(RecordKind.OPERATION, "coding-backend-" + task.digest)
                if row is not None:
                    retained = decode_coding_backend_binding_row(row, task, self.scope)
                    body = retained.to_dict()
                    require(body["selection"] == selection and body["run_policy"] == policy
                            and body["selected_by_session_digest"] == session,
                            "CODING_BACKEND_BINDING_CONFLICT")
                    return retained
                binding = CodingBackendBindingV1({
                    "schema": "aioa.coding-backend-binding.v1", "task_digest": task.digest,
                    "selection": selection, "selection_digest": profile.selection_digest,
                    "run_policy": policy, "run_policy_digest": canonical_sha256(policy),
                    "selected_by_session_digest": session, "selected_at": selected_at,
                })
                tx.insert(StoredRecord(RecordKind.OPERATION, "coding-backend-" + task.digest,
                                       self.scope, 1, binding.to_dict()))
                return binding

            with self._active_lock:
                # The existing runner retries proven rollback 40001 only. An
                # unknown commit acknowledgment propagates without caller replay.
                return self._run(capture.principal, Capability.MANAGE, publish)
        finally:
            capture.close()

    def read_coding_backend(self, principal, task_id):
        """Read retained canonical data without current chooser/source/capture I/O."""
        self._require_principal(principal, Capability.READ, scope=self.scope)
        logical_id(task_id)

        def read(tx):
            task = self._load(tx, task_id)[2]
            row = tx.get(RecordKind.OPERATION, "coding-backend-" + task.digest)
            return None if row is None else decode_coding_backend_binding_row(row, task, self.scope)

        return self._run(principal, Capability.READ, read)

    def _require_legacy_coding_task(self, tx, task_id):
        task = self._load(tx, task_id)[2]
        row = tx.get(RecordKind.OPERATION, "coding-backend-" + task.digest)
        if row is not None:
            decode_coding_backend_binding_row(row, task, self.scope)
            require(False, "CODING_MODEL_WORKER_NOT_READY")
        require(self.coding_backend_registry is None, "CODING_BACKEND_BINDING_REQUIRED")
        return task

    def runtime_view(self, principal):
        """Read real signed records; never infer model certification or progress."""
        self._require_principal(principal, Capability.READ, scope=self.scope)
        with self._active_lock:
            def read(tx):
                rows = self._complete_history(tx)
                counts = dict.fromkeys(STATES, 0)
                for row in rows:
                    if row.payload.get('schema') == KIND:
                        task_id = row.payload.get('task', {}).get('task_id')
                        _, data, _ = decode_coding_task_row(row, task_id, self.capsules.identity.spki)
                        require(row.record_id == self._key(task_id), 'CODING_TASK_INTEGRITY')
                        counts[data['receipts'][-1]['receipt']['state']] += 1
                return {
                    'schema': 'aioa.coding-runtime-view.v1', 'authority': 'NONE',
                    'read_only': True, 'automatic_retry': False,
                    'snapshot_semantics': 'ONE_CORE_READ_TRANSACTION',
                    'owner_scope_sha256': canonical_sha256(self.scope),
                    'controller_state': ('CLOSED' if self.closed else
                                         'CONFIGURED' if self.run_factory is not None else 'UNBOUND'),
                    'effect_route_configured': self.effect_factory is not None,
                    'worker_certification': 'NOT_CHECKED_BY_READ',
                    'unresolved_effects': self._unresolved_intents(rows),
                    'task_counts': counts,
                }
            return self._run(principal, Capability.READ, read)

    def _key(self, task_id):
        logical_id(task_id)
        return canonical_sha256([KIND, task_id])

    def _load(self, tx, task_id):
        row = tx.get(RecordKind.OPERATION, self._key(task_id))
        return decode_coding_task_row(row, task_id, self.capsules.identity.spki)

    def _signed(self, task, state, receipts, capsule_digest=None):
        require(state in STATES, "CODING_STATE")
        proof = {
            "schema": "aioa.coding-intake-receipt.v1",
            "task_digest": task.digest,
            "sequence": len(receipts) + 1,
            "state": state,
            "previous": canonical_sha256(receipts[-1]) if receipts else "0" * 64,
            "capsule_digest": capsule_digest,
        }
        return {"receipt": proof, "signature": self.capsules.identity.sign(proof)}

    def _save(self, tx, prior, data):
        key = self._key(data["task"]["task_id"])
        row = StoredRecord(
            RecordKind.OPERATION,
            key,
            self.scope,
            1 if prior is None else prior.revision + 1,
            data,
        )
        if prior is None:
            tx.insert(row)
        else:
            tx.replace(row, expected_revision=prior.revision)
        identity = canonical_sha256([key, row.revision])
        event = OperationBinding.bind(
            "coding-" + identity, "CODING_INTAKE", {"record_digest": row.payload_digest}
        )
        append_domain_event(
            tx,
            event,
            event_id="coding-audit-" + identity,
            proof_id="coding-proof-" + identity,
            resource_id=key,
            before=None
            if prior is None
            else prior.payload["receipts"][-1]["receipt"]["state"],
            after=data["receipts"][-1]["receipt"]["state"],
            content_digest=row.payload_digest,
            at=self.journal.ledger.clock(),
        )

    @staticmethod
    def _view(data):
        return {
            "task_id": data["task"]["task_id"],
            "run_id": data["task"]["run_id"],
            "task_digest": data["task_digest"],
            "state": data["receipts"][-1]["receipt"]["state"],
            "capsule_digest": data["receipts"][-1]["receipt"]["capsule_digest"],
            "receipt_count": len(data["receipts"]),
            "authority": "NONE",
            "effects_registered": any(
                item["receipt"]["state"] == "APPROVED" for item in data["receipts"]
            ),
            "effect_verified": data["receipts"][-1]["receipt"]["state"] == "VERIFIED",
        }

    def _transition(
        self,
        principal,
        task_id,
        expected,
        state,
        *,
        capsule_digest=None,
        purpose=Capability.COMMIT,
        idempotent=True,
        admission=False,
        owned_active=None,
    ):
        def change(tx):
            if owned_active is not None:
                require(self._active.get(task_id) is owned_active and not self.closed
                        and not owned_active['cancel'].cancelled, "CODING_CANCELLED")
            if admission:
                self._require_legacy_coding_task(tx, task_id)
                # This is the SAME Core transaction as QUEUED -> RUNNING.
                # A restart must inspect prior claims, not reset local capacity.
                rows = self._complete_history(tx)
                for row in rows:
                    if row.payload.get("schema") != KIND:
                        continue
                    _, stored, stored_task = decode_coding_task_row(
                        row, row.payload["task"]["task_id"], self.capsules.identity.spki
                    )
                    retained = stored["receipts"][-1]["receipt"]["state"]
                    require(retained != "UNKNOWN", "CODING_UNRESOLVED_RUN")
                    require(
                        retained
                        not in ("RUNNING", "VALIDATING", "REPAIRING", "APPLYING")
                        or stored_task.task_id in self._active
                        or stored_task.task_id in self._effects,
                        "CODING_RECOVERY_REQUIRED",
                    )
                require(not self._unresolved_intents(rows), "CODING_UNRESOLVED_INTENT")
            return self._append_transition(
                tx,
                task_id,
                expected,
                state,
                capsule_digest=capsule_digest,
                idempotent=idempotent,
            )

        return self._run(principal, purpose, change)

    def _append_transition(
        self, tx, task_id, expected, state, *, capsule_digest=None, idempotent=True
    ):
        """Append on the existing transaction, including atomic owner approval."""
        prior, data, task = self._load(tx, task_id)
        last = data["receipts"][-1]["receipt"]
        if (
            idempotent
            and last["state"] == state
            and (capsule_digest is None or last["capsule_digest"] == capsule_digest)
        ):
            return self._view(data)
        require(last["state"] in expected, "CODING_TRANSITION_DENIED")
        require(len(data["receipts"]) < 64, "CODING_RECEIPT_LIMIT")
        data["receipts"].append(
            self._signed(
                task,
                state,
                data["receipts"],
                capsule_digest
                if capsule_digest is not None
                else last["capsule_digest"],
            )
        )
        self._save(tx, prior, data)
        return self._view(data)

    @staticmethod
    def _complete_history(tx):
        # The existing port's maximum is 1024. A full prefix cannot prove
        # completeness, including when the actual store contains exactly 1024.
        rows = tx.scan(RecordKind.OPERATION, limit=HISTORY_LIMIT)
        require(len(rows) < HISTORY_LIMIT, "CODING_HISTORY_LIMIT")
        return rows

    @staticmethod
    def _unresolved_intents(rows):
        from runtime.mission.intent import INTENT_KINDS

        return any(
            row.payload.get("schema") in INTENT_KINDS
            and row.payload.get("resolution") is None
            for row in rows
        )

    def _start(self, principal, task_id):
        from runtime.providers.exact import CancellationToken
        self._require_principal(principal, Capability.MANAGE, scope=self.scope)
        require(self.run_factory is not None and (self.native_access is not None or self.run_principal is not None)
                and not self.closed, "CODING_CONTROLLER_NOT_CONFIGURED")
        self._retire_finished()
        with self._active_lock:
            require(not self.closed, "CODING_CONTROLLER_CLOSED")
            existing = self._active.get(task_id)
            if existing is None:
                def require_ready(tx):
                    view = self._view(self._load(tx, task_id)[1])
                    require(view["state"] == "QUEUED", "CODING_TRANSITION_DENIED")
                    self._require_legacy_coding_task(tx, task_id)

                # A definite admission refusal requires no worker or recovery slot.
                # The durable transition repeats its own checks.
                self._run(principal, Capability.MANAGE, require_ready)
                require(len(self._active) < 2, "CODING_ACTIVE_LIMIT")
                active = {'cancel': CancellationToken(), 'producer': None, 'done': threading.Event()}
                active['thread'] = threading.Thread(target=self._execute, args=(task_id, active),
                    name='aioa-coding-' + task_id, daemon=True)
                self._active[task_id] = active
            else:
                active = existing
        if existing is not None:
            return self._run(principal, Capability.MANAGE, lambda tx: self._view(self._load(tx, task_id)[1]))
        try:
            if self.native_access is not None:
                lifecycle = self.native_access.foundation.lifecycle
                active['native_handle'] = lifecycle.begin_work(self, 'CODING_WORKER', task_id,
                    active['cancel'], active['thread'], active['done'])
            with self._authority(Capability.COMMIT) as fresh:
                require(not active['cancel'].cancelled and not self.closed, "CODING_CANCELLED")
                self._transition(fresh, task_id, ('QUEUED',), 'RUNNING', idempotent=False,
                                 admission=True, owned_active=active)
            if self.native_access is not None:
                lifecycle.before_start(active['native_handle'])
            with self._active_lock:
                require(not active['cancel'].cancelled and not self.closed, "CODING_CANCELLED")
                active['thread'].start()
        except BaseException:
            active['cancel'].cancel()
            active['done'].set()
            # A lost durable claim ACK is unresolved and never starts a thread.
            # Keep the published ownership until canonical recovery proves idle.
            active['quarantined'] = True
            if self.native_access is not None and active.get('native_handle') is not None:
                self.native_access.foundation.lifecycle.quarantine(active['native_handle'])
            raise
        return self._run(principal, Capability.MANAGE, lambda tx: self._view(self._load(tx, task_id)[1]))

    def _record_loop(self, principal, task, result):
        from runtime.mission.repair import RepairLoopResult

        require(
            type(result) is RepairLoopResult
            and result.task_id == task.task_id
            and result.run_id == task.run_id,
            "CODING_LOOP_BINDING",
        )
        result.__post_init__()
        data = {
            "schema": "aioa.coding-loop.v1",
            "task_digest": task.digest,
            "result": asdict(result),
        }
        key = canonical_sha256(["aioa.coding-loop.v1", task.digest])

        def save(tx):
            require(
                tx.get(RecordKind.OPERATION, key) is None, "CODING_LOOP_REPLAY_DENIED"
            )
            row = StoredRecord(RecordKind.OPERATION, key, self.scope, 1, data)
            tx.insert(row)
            binding = OperationBinding.bind(
                "coding-loop-" + key,
                "CODING_LOOP_RECEIPT",
                {"record_digest": row.payload_digest},
            )
            append_domain_event(
                tx,
                binding,
                event_id="coding-loop-audit-" + key,
                proof_id="coding-loop-outbox-" + key,
                resource_id=key,
                before=None,
                after=result.status,
                content_digest=row.payload_digest,
                at=self.journal.ledger.clock(),
            )

        self._run(principal, Capability.COMMIT, save)

    def _execute(self, task_id, active):
        lifecycle = self.native_access.foundation.lifecycle if self.native_access is not None else None
        if lifecycle is not None:
            lifecycle._boundary.work_handle = active['native_handle']
        try:
            self._execute_body(task_id, active)
        finally:
            if lifecycle is not None:
                del lifecycle._boundary.work_handle
            active['done'].set()

    def _execute_body(self, task_id, active):
        from runtime.mission.repair import (
            BoundedRepairLoopCoordinator,
            RepairBoundaryError,
            failure_boundary,
        )

        principal = self.run_principal
        terminal = None
        cleanup_uncertain = False
        try:
            with failure_boundary("CODING_CONTROLLER_FAILED"):
                task = self._run(
                    principal,
                    Capability.COMMIT,
                    lambda tx: self._require_legacy_coding_task(tx, task_id),
                )
                run = self.run_factory(task, active["cancel"])
                require(
                    type(run) is CodingRun
                    and run.producer.task == task
                    and run.producer.materializer.journal is self.journal
                    and run.validator.journal is self.journal
                    and run.producer.cancel_token is active["cancel"]
                    and run.validator.cancel is active["cancel"],
                    "CODING_RUN_BINDING",
                )
                active["producer"] = run.producer

                def observe(state):
                    if active["cancel"].cancelled:
                        return
                    self._transition(
                        principal,
                        task_id,
                        ("RUNNING", "VALIDATING", "REPAIRING"),
                        state,
                    )

                result = BoundedRepairLoopCoordinator(clock=self.clock).run(
                    task=task,
                    source=run.source,
                    base_root=run.base_root,
                    producer=run.producer,
                    validator=run.validator,
                    cancelled=lambda: active["cancel"].cancelled,
                    on_state=observe,
                )
                cleanup_uncertain = result.failure_code in (
                    "WORKER_CLEANUP_FAILED",
                    "SANDBOX_CLEANUP_FAILED",
                )
                self._record_loop(principal, task, result)
                if result.status == "PATCH_READY" and not active["cancel"].cancelled:
                    with self._authority(Capability.COMMIT) as fresh:
                        signed = self.capsules.prepare(
                        fresh,
                        task=task,
                        source=run.source,
                        base_root=run.base_root,
                        final_root=run.producer.last_root,
                        result=result,
                        target_fingerprint=run.target_fingerprint,
                        target_revision=run.target_revision,
                        expires_at=(min(run.expires_at, int(self.clock()) + 300)
                                    if self.native_access is not None else run.expires_at),
                    )
                    # STOP/close and publication share the same lifecycle
                    # lock. An acknowledged cancellation cannot publish review
                    # in the check -> attach interval.
                    with self._active_lock:
                        if not self.closed and not active["cancel"].cancelled:
                            self.attach_review(
                                principal, task_id, signed["receipt"]["capsule_digest"]
                            )
                            # Retire the completed worker in the SAME handoff.
                            # STOP after publication must reach canonical
                            # review/approval cancellation, not a stale token.
                            active["completed"] = True
                            return
                if cleanup_uncertain:
                    terminal = "UNKNOWN"
                elif result.status == "PATCH_READY" and active["cancel"].cancelled:
                    terminal = "CANCELLED"
                else:
                    terminal = (
                        result.status
                        if result.status in ("DENIED", "CANCELLED", "UNKNOWN")
                        else "FAILED"
                    )
        except (ValueError, RepairBoundaryError):
            # A partial materialization can have an UNKNOWN Core intent. Do
            # not turn cleanup failure into a clean cancellation receipt.
            terminal = "UNKNOWN"
        finally:
            if terminal is not None:
                try:
                    with failure_boundary("CODING_HISTORY_UNRESOLVED"):
                        unresolved = self._run(
                            principal,
                            Capability.COMMIT,
                            lambda tx: self._unresolved_intents(
                                self._complete_history(tx)
                            ),
                        )
                except (ValueError, RepairBoundaryError):
                    # Missing/incomplete history is uncertainty, never proof
                    # that cleanup and effect accounting are complete.
                    unresolved = True
                if unresolved:
                    terminal = "UNKNOWN"
                cleanup_uncertain = cleanup_uncertain or terminal == "UNKNOWN"
                try:
                    self._transition(
                        principal,
                        task_id,
                        ("RUNNING", "VALIDATING", "REPAIRING"),
                        terminal,
                    )
                except ValueError:
                    # Another admitted recovery/STOP already won the CAS.
                    pass
            with self._active_lock:
                if cleanup_uncertain:
                    # Keep the owned handle and capacity quarantined. UNKNOWN
                    # cannot free a worker slot or grant a replacement run.
                    active["quarantined"] = True
                else:
                    active["completed"] = True

    def _active_cancel(self, principal, task_id):
        self._require_principal(principal, Capability.MANAGE, scope=self.scope)
        with self._active_lock:
            active = self._active.get(task_id)
            if active is None:
                return None
            active["cancel"].cancel()
            producer = active["producer"]
            completed = active.get("completed") is True and not active.get("quarantined")
        if producer is not None and not completed:
            producer.stop()
        view = self._run(
            principal,
            Capability.MANAGE,
            lambda tx: self._view(self._load(tx, task_id)[1]),
        )
        if completed and view["state"] in ("REVIEW_REQUIRED", "APPROVED", "CANCELLED"):
            # Keep the worker handle until EXIT; cancel its published review canonically.
            return None
        return {**view, "cancel_requested": True}

    def wait(self, task_id, timeout=5):
        require(
            type(timeout) in (int, float) and 0 <= timeout <= 30, "CODING_WAIT_BOUND"
        )
        with self._active_lock:
            active = self._active.get(task_id)
        if active is None:
            return True
        active["thread"].join(timeout)
        finished = not active["thread"].is_alive()
        self._retire_finished()
        return finished

    def close(self):
        return self.drain(5)

    def _effect(self, task_id, capsule_digest):
        from lab.archaioa.warrant import EffectWarrant
        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.mission.governor import ReservationRequest

        require(self.effect_factory is not None, "CODING_EFFECT_NOT_CONFIGURED")
        binding = self.effect_factory(task_id, capsule_digest)
        require(type(binding) is tuple and len(binding) == 3, "CODING_EFFECT_BINDING")
        route, warrant, reservation = binding
        require(
            type(route) is CoreRemoteGitRoute
            and route.journal is self.journal
            and route.mode == "LOCAL_PATCH_FIXTURE"
            and route.capsule.digest == capsule_digest
            and route.capsule.task_id == task_id
            and type(warrant) is EffectWarrant
            and type(reservation) is ReservationRequest,
            "CODING_EFFECT_BINDING",
        )
        return binding

    def _native_git_reconciliation_parent(self, parent, *, current=None):
        from lab.archaioa.warrant import EffectWarrant

        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.meta_hackathon.native_authority import NativeOwnedWorkHandle
        from runtime.mission.git_publish import CoreRemoteGitRoute

        require(not _IN_TRANSACTION.get(), "CODING_NATIVE_RECONCILIATION_INSIDE_SQL")
        self._require_native_binding()
        foundation = self.native_access.foundation
        require(type(parent) is NativeOwnedWorkHandle and type(parent.context) is tuple
                and len(parent.context) == 11, "CODING_NATIVE_RECONCILIATION_PARENT")
        binding, item = parent.context, parent.context[0]
        require(type(item) is dict and item.get('binding') is binding
                and binding[1] is self and binding[2] is foundation,
                "CODING_NATIVE_RECONCILIATION_PARENT")
        route, warrant = item['route'], item['warrant']
        require(type(route) is CoreRemoteGitRoute and type(warrant) is EffectWarrant,
                "CODING_NATIVE_RECONCILIATION_PARENT")
        task_id = route.capsule.task_id
        retained = foundation.owner._native_coding.effects.get((task_id, route.capsule.digest))
        require(type(retained) is tuple and type(retained[0]) is tuple
                and retained[0][0] is route and retained[0][1] is warrant,
                "CODING_NATIVE_RECONCILIATION_PARENT")
        with self._active_lock:
            require(self._effect_ownership.get(task_id) is item and self._effects.get(task_id) is item['cancel']
                    and item['native_handle'] is parent, "CODING_NATIVE_RECONCILIATION_PARENT")
            children = item.get('readbacks', ())
            require(type(children) is tuple and len(children) < 64,
                    "CODING_NATIVE_RECONCILIATION_PARENT")
        require(parent.foundation is foundation and parent.producer is self
                and parent.role == 'CODING_HTTP_EFFECT' and parent.kind == binding[10] == 'LOCAL_GIT_APPLY'
                and parent.synchronous and parent.started and parent.parent is None
                and parent.quarantined and item['quarantined'] and item['returned']
                and binding[3] is route and binding[4] is warrant
                and binding[5] == canonical_json_bytes(item['operation'])
                and parent.thread is binding[6] is item['thread']
                and parent.cancel is binding[7] is item['cancel']
                and parent.done is binding[8] is item['done'] and binding[9] is item['admission_guard']
                and not item['admission_held'] and parent.done.is_set()
                and type(parent.returned) is tuple and len(parent.returned) == 4
                and parent.returned[0] is self and parent.returned[1] is item
                and parent.returned[2] is parent.thread and parent.returned[3] is parent.done,
                "CODING_NATIVE_RECONCILIATION_PARENT")
        for child_item in children:
            child = child_item['native_handle']
            cb = child_item['binding']
            require(type(child) is NativeOwnedWorkHandle and type(cb) is tuple and len(cb) == 11
                    and child.context is cb and cb[0] is child_item and cb[1] is self and cb[2] is foundation
                    and cb[3] is route and cb[4] is warrant and cb[5] == binding[5]
                    and child.parent is parent and child.foundation is foundation and child.producer is self
                    and child.role == parent.role and child.kind == cb[10] == 'LOCAL_GIT_RECONCILE'
                    and child.synchronous and child.started
                    and child.thread is cb[6] is child_item['thread']
                    and child.cancel is cb[7] is child_item['cancel']
                    and child.done is cb[8] is child_item['done'] and cb[9] is child_item['admission_guard']
                    and child_item['route'] is route and child_item['warrant'] is warrant
                    and child_item['parent_item'] is item,
                    "CODING_NATIVE_RECONCILIATION_CHILD")
            if child is current:
                require(child.thread is threading.current_thread() and child_item['phase'] == 'VERIFIED_ACK'
                        and not child.quarantined and not child_item['quarantined'],
                        "CODING_NATIVE_RECONCILIATION_ACK")
            else:
                require(child.quarantined and child_item['quarantined'] and child_item['returned']
                        and child.done.is_set() and type(child.returned) is tuple and len(child.returned) == 4
                        and child.returned[0] is self and child.returned[1] is child_item
                        and child.returned[2] is child.thread and child.returned[3] is child.done,
                        "CODING_NATIVE_RECONCILIATION_CHILD")
        return item

    def _native_git_reconciliation_retirement(self, child):
        parent = child.parent
        item = self._native_git_reconciliation_parent(parent, current=child)
        current = getattr(self.native_access.foundation.lifecycle._boundary, 'coding_effect', None)
        require(type(current) is dict and current['native_handle'] is child
                and any(value is current for value in item['readbacks'])
                and current['phase'] == 'VERIFIED_ACK', "CODING_NATIVE_RECONCILIATION_ACK")
        result, view = current['canonical_ack']
        require(type(result) is dict and result['outcome']['contract_type'] == 'Applied'
                and type(view) is dict and view['state'] == 'VERIFIED'
                and view['task_id'] == parent.context[3].capsule.task_id
                and view['capsule_digest'] == parent.context[3].capsule.digest,
                "CODING_NATIVE_RECONCILIATION_ACK")
        return parent, tuple(value['native_handle'] for value in item['readbacks']
                             if value['native_handle'] is not child)

    def _native_git_reconcile(self, principal, task_id):
        from runtime.meta_hackathon.native_authority import (
            NativeOwnedWorkHandle,
            NativePhase,
        )
        from runtime.providers.exact import CancellationToken

        self._require_principal(principal, Capability.COMMIT)
        lifecycle = self.native_access.foundation.lifecycle
        require(lifecycle.phase is NativePhase.QUARANTINED
                and getattr(lifecycle._boundary, 'coding_effect', None) is None
                and getattr(lifecycle._boundary, 'settlement_handle', None) is None,
                "CODING_NATIVE_RECONCILIATION_BINDING")
        with self._active_lock:
            parent_item = self._effect_ownership.get(task_id)
            require(type(parent_item) is dict, "CODING_NATIVE_RECONCILIATION_PARENT")
            parent = parent_item['native_handle']
        require(self._native_git_reconciliation_parent(parent) is parent_item,
                "CODING_NATIVE_RECONCILIATION_PARENT")
        route, warrant, operation = parent_item['route'], parent_item['warrant'], parent_item['operation']
        prepared_plan = route.plan
        prepared_digest = prepared_plan.digest

        def read(tx):
            route._require_native_local_plan(prepared_plan, prepared_digest)
            _, data, task = self._load(tx, task_id)
            view = self._view(data)
            require(view['state'] in ('APPLYING', 'UNKNOWN', 'VERIFIED') and task.task_id == route.capsule.task_id
                    and view['capsule_digest'] == route.capsule.digest,
                    "CODING_NATIVE_RECONCILIATION_HISTORY")
            route._local_proofs(tx, historical=True)
            require(canonical_json_bytes(route._local_history(tx, prepared_plan_digest=prepared_digest))
                    == canonical_json_bytes(operation),
                    "CODING_NATIVE_RECONCILIATION_HISTORY")
            _, intent = self.journal._load(tx, warrant)
            require(intent is not None and canonical_json_bytes(intent['operation']) == canonical_json_bytes(operation),
                    "CODING_NATIVE_RECONCILIATION_HISTORY")
            return view

        self._run(None, Capability.READ, read)
        route._require_native_local_source(prepared_plan, prepared_digest)
        self.native_access.foundation.owner._native_coding.project_probe()
        cancel, guard = CancellationToken(), threading.Lock()
        identity = 'coding-readback-' + task_id + '-' + str(len(parent_item.get('readbacks', ())) + 1)
        handle = None
        item = {'route': route, 'warrant': warrant, 'operation': operation,
                'thread': threading.current_thread(), 'cancel': cancel, 'done': None,
                'native_handle': None, 'quarantined': False, 'producer': None,
                'admission_guard': guard, 'admission_held': False, 'returned': False,
                'phase': 'RECONCILING', 'parent_item': parent_item, 'binding': None}
        try:
            handle = lifecycle.begin_synchronous(self, 'CODING_HTTP_EFFECT', identity, cancel, parent=parent)
            item['native_handle'], item['thread'], item['done'] = handle, handle.thread, handle.done
            handle.kind = 'LOCAL_GIT_RECONCILE'
            item['binding'] = (item, self, self.native_access.foundation, route, warrant,
                               canonical_json_bytes(operation), handle.thread, cancel, handle.done, guard, handle.kind)
            handle.context = item['binding']
            with self._active_lock:
                require(self._effect_ownership.get(task_id) is parent_item and parent_item['native_handle'] is parent,
                        "CODING_NATIVE_RECONCILIATION_PARENT")
                parent_item['readbacks'] = parent_item.get('readbacks', ()) + (item,)
            lifecycle._boundary.coding_effect = item
            lifecycle._boundary.settlement_handle = handle
            with self._authority(Capability.COMMIT) as fresh:
                result = route.reconcile(fresh, warrant, cancel=cancel)
                require(result['outcome']['contract_type'] == 'Applied' and item['phase'] == 'READBACK',
                        "CODING_NATIVE_CANONICAL_COMPLETION_REQUIRED")
                view = self._transition(fresh, task_id, ('APPLYING', 'UNKNOWN'), 'VERIFIED')
                require(view['state'] == 'VERIFIED', "CODING_NATIVE_CANONICAL_COMPLETION_REQUIRED")
            item['canonical_ack'] = (result, view)
            item['phase'] = 'VERIFIED_ACK'
            lifecycle.complete_synchronous(handle)
            with self._active_lock:
                require(self._effect_ownership.get(task_id) is parent_item and self._effects.get(task_id) is parent.cancel,
                        "CODING_NATIVE_RECONCILIATION_PARENT")
                self._effect_ownership.pop(task_id)
                self._effects.pop(task_id)
            return view
        except BaseException:
            if handle is None:
                # An acquisition ACK may itself be lost after registration.
                # Retain only THIS exact source-owned identity/current thread;
                # never manufacture a handle or overwrite a retained binding.
                with lifecycle.lock:
                    candidate = lifecycle._handles.get(identity)
                    if (type(candidate) is NativeOwnedWorkHandle and candidate.parent is parent
                            and candidate.producer is self and candidate.foundation is self.native_access.foundation
                            and candidate.role == 'CODING_HTTP_EFFECT' and candidate.cancel is cancel
                            and candidate.thread is threading.current_thread()):
                        handle = candidate
            if handle is not None and lifecycle._handles.get(handle.task_id) is handle:
                item['native_handle'], item['thread'], item['done'] = handle, handle.thread, handle.done
                item['quarantined'] = True
                with self._active_lock:
                    if self._effect_ownership.get(task_id) is parent_item:
                        children = parent_item.get('readbacks', ())
                        if not any(value is item for value in children):
                            parent_item['readbacks'] = children + (item,)
                lifecycle.quarantine(handle)
            raise
        finally:
            if handle is not None:
                item['returned'] = True
                handle.returned = (self, item, handle.thread, handle.done)
                handle.done.set()
                if getattr(lifecycle._boundary, 'settlement_handle', None) is handle:
                    del lifecycle._boundary.settlement_handle
            if getattr(lifecycle._boundary, 'coding_effect', None) is item:
                del lifecycle._boundary.coding_effect

    def _native_git_effect_entry(self, route, warrant):
        from runtime.meta_hackathon.native_authority import NativeOwnedWorkHandle
        from runtime.mission.git_publish import CoreRemoteGitRoute

        self._require_native_binding()
        lifecycle = self.native_access.foundation.lifecycle
        require(type(route) is CoreRemoteGitRoute, "CODING_NATIVE_EFFECT_BINDING")
        retained = self._effect_ownership.get(route.capsule.task_id)
        item = getattr(lifecycle._boundary, 'coding_effect', None)
        require(type(retained) is dict and type(item) is dict, "CODING_NATIVE_EFFECT_BINDING")
        if item is not retained:
            require(item.get('parent_item') is retained
                    and any(value is item for value in retained.get('readbacks', ()))
                    and item['native_handle'].parent is retained['native_handle']
                    and retained['native_handle'].quarantined and retained['quarantined']
                    and retained['returned'] and retained['done'].is_set()
                    and lifecycle._handles.get(retained['native_handle'].task_id) is retained['native_handle']
                    and self._effects.get(route.capsule.task_id) is retained['cancel'],
                    "CODING_NATIVE_EFFECT_BINDING")
        handle, binding = item['native_handle'], item['binding']
        require(type(binding) is tuple and len(binding) == 11 and binding[0] is item
                and binding[1] is self and binding[2] is self.native_access.foundation
                and binding[3] is route and binding[4] is warrant
                and canonical_json_bytes(item['operation']) == binding[5]
                and item['route'] is route and item['warrant'] is warrant
                and item['thread'] is binding[6] is threading.current_thread()
                and item['cancel'] is binding[7]
                and (item is not retained or item['cancel'] is self._effects.get(route.capsule.task_id))
                and item['done'] is binding[8] and item['admission_guard'] is binding[9]
                and type(handle) is NativeOwnedWorkHandle and handle.context is binding
                and handle.foundation is binding[2] and handle.producer is self
                and handle.role == 'CODING_HTTP_EFFECT' and handle.kind == binding[10]
                and handle.thread is binding[6] and handle.cancel is binding[7]
                and handle.done is binding[8] and handle.synchronous and handle.started
                and lifecycle._handles.get(handle.task_id) is handle
                and not handle.done.is_set() and not handle.quarantined and not item['quarantined'],
                "CODING_NATIVE_EFFECT_BINDING")
        return item

    def _native_git_effect_check(self, route, warrant, purpose):
        item = self._native_git_effect_entry(route, warrant)
        require(purpose in (Capability.READ, Capability.COMMIT), "CODING_NATIVE_EFFECT_PURPOSE")
        lifecycle = self.native_access.foundation.lifecycle
        if item['phase'] == 'READBACK' or item['phase'] == 'RECONCILING' and item['native_handle'].parent is not None:
            require(getattr(lifecycle._boundary, 'settlement_handle', None) is item['native_handle'],
                    "CODING_NATIVE_SETTLEMENT_BINDING")
        else:
            require(item['phase'] in ('ADMITTING', 'APPLYING_ACK', 'EXECUTING', 'RECONCILING')
                    and not self.closed and not item['cancel'].cancelled,
                    "CODING_CANCELLED")
            lifecycle.require_execution()
        return item

    def _native_git_start_ack(self, route, warrant):
        item = self._native_git_effect_check(route, warrant, Capability.COMMIT)
        require(item['phase'] == 'APPLYING_ACK' and item['admission_held'],
                "CODING_NATIVE_START_ACK_BINDING")
        # Called only by the fixed local route after original START/release ACK.
        # Physical release checks below remain ordinary fresh EXECUTION checks.
        item['phase'] = 'EXECUTING'
        item['admission_held'] = False
        item['admission_guard'].release()

    def _native_git_begin_settlement(self, route, warrant, *, historical):
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.meta_hackathon.native_authority import NativeAccessUse

        require(not _IN_TRANSACTION.get(), "CODING_NATIVE_SETTLEMENT_INSIDE_SQL")
        item = self._native_git_effect_entry(route, warrant)
        require(type(historical) is bool and item['phase'] == ('RECONCILING' if historical else 'EXECUTING')
                and not item['admission_held'], "CODING_NATIVE_SETTLEMENT_BINDING")
        lifecycle = self.native_access.foundation.lifecycle
        previous = getattr(lifecycle._boundary, 'settlement_handle', None)
        require(previous is None or historical and item['native_handle'].parent is not None
                and previous is item['native_handle'], "CODING_NATIVE_SETTLEMENT_BINDING")
        # This fixed hook is inside original independent readback, after the
        # create-ref write path. No START or physical write runs in this context.
        lifecycle._boundary.settlement_handle = item['native_handle']
        item['phase'] = 'READBACK'
        capture = self.native_access.capture(Capability.READ, use=NativeAccessUse.SETTLEMENT)
        try:
            self.native_access.require_capture(capture, Capability.READ)
        finally:
            capture.close()

    def _native_git_effect_request(self, principal, action, task_id, route, warrant, operation, reservation):
        from runtime.mission.repair import RepairBoundaryError, failure_boundary
        from runtime.providers.exact import CancellationToken

        require(action in ('apply', 'reconcile'), "CODING_OPERATION_DENIED")
        lifecycle = self.native_access.foundation.lifecycle
        lifecycle.require_execution()
        require(getattr(lifecycle._boundary, 'coding_effect', None) is None
                and getattr(lifecycle._boundary, 'settlement_handle', None) is None,
                "CODING_NATIVE_NESTED_EFFECT")
        cancel, guard = CancellationToken(), threading.Lock()
        with self._active_lock:
            require(not self.closed and task_id not in self._effects
                    and task_id not in self._effect_ownership
                    and len(self._active) + len(self._effect_ownership) < 4,
                    "CODING_EFFECT_ACTIVE")
            handle = lifecycle.begin_synchronous(self, 'CODING_HTTP_EFFECT', 'coding-effect-' + task_id, cancel)
            item = {'route': route, 'warrant': warrant, 'operation': operation,
                'thread': handle.thread, 'cancel': cancel, 'done': handle.done,
                'native_handle': handle, 'quarantined': False, 'producer': None,
                'admission_guard': guard, 'admission_held': False, 'returned': False,
                'phase': 'ADMITTING' if action == 'apply' else 'RECONCILING'}
            handle.kind = 'LOCAL_GIT_APPLY' if action == 'apply' else 'LOCAL_GIT_RECONCILE'
            item['binding'] = (item, self, self.native_access.foundation, route, warrant,
                canonical_json_bytes(operation), handle.thread, cancel, handle.done, guard, handle.kind)
            handle.context = item['binding']
            self._effects[task_id], self._effect_ownership[task_id] = cancel, item
        lifecycle._boundary.coding_effect = item
        try:
            if action == 'apply':
                require(guard.acquire(timeout=1), "CODING_ADMISSION_GUARD_BUSY")
                item['admission_held'] = True
                self._native_git_effect_check(route, warrant, Capability.COMMIT)
                self._transition(principal, task_id, ('APPROVED',), 'APPLYING', idempotent=False)
                item['phase'] = 'APPLYING_ACK'
            try:
                with failure_boundary('CODING_GIT_UNKNOWN'):
                    self._native_git_effect_check(route, warrant, Capability.COMMIT)
                    result = (route.dispatch(principal, warrant, operation, reservation, cancel=cancel)
                              if action == 'apply' else route.reconcile(principal, warrant, cancel=cancel))
                state = 'VERIFIED' if result['outcome']['contract_type'] == 'Applied' else 'UNKNOWN'
            except (ValueError, RepairBoundaryError):
                state = 'UNKNOWN'
            if state == 'VERIFIED':
                require(item['phase'] == 'READBACK', "CODING_NATIVE_CANONICAL_COMPLETION_REQUIRED")
            view = self._transition(principal, task_id, ('APPLYING', 'UNKNOWN'), state)
            if state == 'VERIFIED':
                require(view['state'] == 'VERIFIED', "CODING_NATIVE_CANONICAL_COMPLETION_REQUIRED")
                lifecycle.complete_synchronous(handle)
                with self._active_lock:
                    require(self._effect_ownership.get(task_id) is item and self._effects.get(task_id) is cancel,
                            "CODING_NATIVE_EFFECT_BINDING")
                    self._effect_ownership.pop(task_id)
                    self._effects.pop(task_id)
            else:
                item['quarantined'] = True
                lifecycle.quarantine(handle)
            return view
        except BaseException:
            if not handle.quarantined and lifecycle._handles.get(handle.task_id) is handle:
                item['quarantined'] = True
                lifecycle.quarantine(handle)
            raise
        finally:
            if item['admission_held']:
                item['admission_held'] = False
                guard.release()
            item['returned'] = True
            handle.returned = (self, item, handle.thread, handle.done)
            handle.done.set()
            if getattr(lifecycle._boundary, 'settlement_handle', None) is handle:
                del lifecycle._boundary.settlement_handle
            if getattr(lifecycle._boundary, 'coding_effect', None) is item:
                del lifecycle._boundary.coding_effect

    def _controller_request(self, principal, action, payload):
        purpose = {
            "start": Capability.MANAGE,
            "recover": Capability.MANAGE,
            "review_effect": Capability.READ,
            "approve": Capability.OWNER_APPROVAL,
            "deny": Capability.OWNER_APPROVAL,
            "apply": Capability.COMMIT,
            "reconcile": Capability.COMMIT,
        }[action]
        self._require_principal(principal, purpose, scope=self.scope)
        fields = (
            {"task_id", "capsule_digest", "operation_digest"}
            if action in ("approve", "apply")
            else {"task_id"}
        )
        require(
            type(payload) is dict and set(payload) == fields, "CODING_REQUEST_SCHEMA"
        )
        task_id = logical_id(payload["task_id"])
        if action == 'reconcile' and self.native_access is not None:
            return self._native_git_reconcile(principal, task_id)
        if action == "start":
            return self._start(principal, task_id)
        if action == "recover":
            with self._active_lock:
                require(task_id not in self._active, "CODING_RUN_ACTIVE")
            return self._transition(
                principal,
                task_id,
                ("RUNNING", "VALIDATING", "REPAIRING", "APPLYING"),
                "UNKNOWN",
                purpose=purpose,
            )
        view = self._run(
            principal, purpose, lambda tx: self._view(self._load(tx, task_id)[1])
        )
        if action == "deny":
            return self._transition(
                principal, task_id, ("REVIEW_REQUIRED",), "DENIED", purpose=purpose
            )
        require(
            view["state"]
            in ("REVIEW_REQUIRED", "APPROVED", "APPLYING", "VERIFIED", "UNKNOWN"),
            "CODING_TASK_INACTIVE",
        )
        route, warrant, reservation = self._effect(task_id, view["capsule_digest"])
        operation = getattr(route, "historical_operation", None)
        if operation is None:
            operation = route.operation(principal.actor_session_id, warrant.lease_epoch)
        preview = {
            "task_id": task_id,
            "capsule_digest": view["capsule_digest"],
            "operation_digest": canonical_sha256(operation),
            "operation": operation,
            "authority": "NONE",
        }
        if action == "review_effect":
            return {**view, "effect_preview": preview}
        if action in ("approve", "apply"):
            require(
                payload["capsule_digest"] == preview["capsule_digest"]
                and payload["operation_digest"] == preview["operation_digest"],
                "CODING_EXACT_APPROVAL_REQUIRED",
            )
        if action == "approve":
            require(
                view["state"] in ("REVIEW_REQUIRED", "APPROVED"), "CODING_TASK_INACTIVE"
            )
            with self._active_lock:
                require(not self.closed, "CODING_CONTROLLER_CLOSED")
                return route.approve_local_patch(principal, warrant, controller=self)
        if self.native_access is not None:
            require(view['state'] == 'APPROVED' if action == 'apply'
                    else view['state'] in ('APPLYING', 'UNKNOWN'), "CODING_TASK_INACTIVE")
            return self._native_git_effect_request(principal, action, task_id, route, warrant, operation, reservation)
        from runtime.providers.exact import CancellationToken

        cancel = CancellationToken()
        if action == "apply":
            # The token is published before APPLYING can escape this lock.
            # STOP/close either wins before the claim, or sees its owned token.
            with self._active_lock:
                require(not self.closed, "CODING_CONTROLLER_CLOSED")
                require(task_id not in self._effects, "CODING_EFFECT_ACTIVE")
                self._effects[task_id] = cancel
                try:
                    self._transition(
                        principal, task_id, ("APPROVED",), "APPLYING", idempotent=False
                    )
                except BaseException:
                    self._effects.pop(task_id, None)
                    raise
        else:
            require(view["state"] in ("APPLYING", "UNKNOWN"), "CODING_TASK_INACTIVE")
        try:
            from runtime.mission.repair import RepairBoundaryError, failure_boundary

            with failure_boundary("CODING_GIT_UNKNOWN"):
                require(not self.closed and not cancel.cancelled, "CODING_STOPPED")
                result = (
                    route.dispatch(
                        principal, warrant, operation, reservation, cancel=cancel
                    )
                    if action == "apply"
                    else route.reconcile(principal, warrant, cancel=cancel)
                )
            state = (
                "VERIFIED"
                if result["outcome"]["contract_type"] == "Applied"
                else "UNKNOWN"
            )
        except (ValueError, RepairBoundaryError):
            state = "UNKNOWN"
        finally:
            with self._active_lock:
                self._effects.pop(task_id, None)
        return self._transition(principal, task_id, ("APPLYING", "UNKNOWN"), state)

    def request(self, principal, action, payload):
        if self.native_access is not None and action not in ('runtime_status','read_status','get_receipts','review_effect','reconcile','recover'):
            self.native_access.foundation.lifecycle.require_execution()
        if action == 'runtime_status':
            require(type(payload) is dict and not payload, 'CODING_REQUEST_SCHEMA')
            return self.runtime_view(principal)
        if action in (
            "start",
            "recover",
            "review_effect",
            "approve",
            "deny",
            "apply",
            "reconcile",
        ):
            return self._controller_request(principal, action, payload)
        if action == "stop":
            action = "cancel"
        purpose = {
            "create_task": Capability.MANAGE,
            "cancel": Capability.MANAGE,
            "read_status": Capability.READ,
            "get_receipts": Capability.READ,
        }.get(action)
        require(purpose is not None, "CODING_OPERATION_DENIED")
        self._require_principal(principal, purpose, scope=self.scope)
        require(
            type(payload) is dict
            and set(payload) == ({"task"} if action == "create_task" else {"task_id"}),
            "CODING_REQUEST_SCHEMA",
        )
        if action == "create_task":
            require(
                type(payload["task"]) is dict
                and set(payload["task"]) in (
                    set(Task.__dataclass_fields__),
                    set(Task.__dataclass_fields__) - {"max_output_tokens"},
                ),
                "CODING_REQUEST_SCHEMA",
            )
            task = Task(**payload["task"])
            signed = self._signed(task, "QUEUED", [])

            def create(tx):
                prior = tx.get(RecordKind.OPERATION, self._key(task.task_id))
                if prior is not None:
                    _, data, stored_task = self._load(tx, task.task_id)
                    require(stored_task == task, "CODING_TASK_CONFLICT")
                    return self._view(data)
                data = {
                    "schema": KIND,
                    "task": asdict(task),
                    "task_digest": task.digest,
                    "receipts": [signed],
                }
                self._save(tx, None, data)
                return self._view(data)

            return self._run(principal, purpose, create)
        task_id = logical_id(payload["task_id"])
        if action in ("read_status", "get_receipts"):

            def read(tx):
                _, data, _ = self._load(tx, task_id)
                result = self._view(data)
                if action == "get_receipts":
                    result["receipts"] = data["receipts"]
                    row = tx.get(
                        RecordKind.OPERATION,
                        canonical_sha256(["aioa.coding-loop.v1", data["task_digest"]]),
                    )
                    if row is not None:
                        result["run_result"] = json.loads(
                            canonical_json_bytes(row.payload)
                        )["result"]
                return result

            return self._run(principal, purpose, read)
        active = self._active_cancel(principal, task_id)
        if active is not None:
            return active
        if self.native_access is not None:
            with self._active_lock:
                token = self._effects.get(task_id)
                owned = self._effect_ownership.get(task_id)
            if token is not None:
                guard = owned['admission_guard'] if owned is not None else None
                acquired = guard is not None and guard.acquire(timeout=0.05)
                try:
                    # A racing admission remains owned/uncertain. This response
                    # is its canonical state, never a fabricated cleanup ACK.
                    token.cancel()
                finally:
                    if acquired:
                        guard.release()
                return self._run(principal, purpose, lambda tx: self._view(self._load(tx, task_id)[1]))
        else:
            with self._active_lock:
                token = self._effects.get(task_id)
                if token is not None:
                    token.cancel()
                    return self._run(
                        principal,
                        purpose,
                        lambda tx: self._view(self._load(tx, task_id)[1]),
                    )
        prior, data, task = self._run(
            principal, purpose, lambda tx: self._load(tx, task_id)
        )
        state = data["receipts"][-1]["receipt"]["state"]
        if state == "CANCELLED":
            return self._view(data)
        require(
            state in ("QUEUED", "REVIEW_REQUIRED", "APPROVED"),
            "NATIVE_STOP_REQUIRED",
        )
        data["receipts"].append(
            self._signed(
                task,
                "CANCELLED",
                data["receipts"],
                data["receipts"][-1]["receipt"]["capsule_digest"],
            )
        )

        def cancel(tx):
            current, current_data, _ = self._load(tx, task_id)
            if current_data["receipts"][-1]["receipt"]["state"] == "CANCELLED":
                return self._view(current_data)
            require(
                current.payload_digest == prior.payload_digest, "CODING_TASK_CONFLICT"
            )
            self._save(tx, current, data)
            return self._view(data)

        return self._run(principal, purpose, cancel)

    def attach_review(self, principal, task_id, capsule_digest):
        with self._active_lock:
            require(not self.closed, "CODING_CONTROLLER_CLOSED")
            active = self._active.get(task_id)
            require(
                active is None or not active["cancel"].cancelled,
                "CODING_CANCELLED",
            )
            return self._attach_review_locked(principal, task_id, capsule_digest)

    def _attach_review_locked(self, principal, task_id, capsule_digest):
        self._require_principal(principal, Capability.COMMIT, scope=self.scope)
        from runtime.mission.repair import digest

        digest(capsule_digest)

        def inspect(tx):
            prior, data, task = self._load(tx, task_id)
            caprow = tx.get(
                RecordKind.OPERATION, canonical_sha256([CAPSULE_KIND, capsule_digest])
            )
            require(caprow is not None, "CAPSULE_REQUIRED")
            capsule = self.capsules._decode(caprow)
            require(
                capsule.task_digest == task.digest and capsule.task_id == task.task_id,
                "CODING_CAPSULE_SWAP",
            )
            require(
                data["receipts"][-1]["receipt"]["state"]
                in ("QUEUED", "RUNNING", "VALIDATING", "REPAIRING", "REVIEW_REQUIRED"),
                "CODING_TASK_INACTIVE",
            )
            return prior, data, task, capsule

        prior, data, task, capsule = self._run(
            principal, Capability.COMMIT, inspect
        )
        self.capsules._fresh(capsule)
        if data["receipts"][-1]["receipt"]["capsule_digest"] == capsule_digest:
            return self._view(data)
        data["receipts"].append(
            self._signed(task, "REVIEW_REQUIRED", data["receipts"], capsule_digest)
        )

        def save(tx):
            current, _, _, observed = inspect(tx)
            require(
                current.payload_digest == prior.payload_digest and observed == capsule,
                "CODING_TASK_CONFLICT",
            )
            self._save(tx, current, data)
            return self._view(data)

        return self._run(principal, Capability.COMMIT, save)


def coding_cli_request(runtime, principal, action, payload):
    """Typed command adapter; the Native host must supply its admitted binding."""
    return runtime.coding_request(action, payload, principal=principal)


def run_coding_cli(argv, *, runtime, principal):
    """Parse commands for an explicitly bound host; never create another Core."""
    from runtime.mission.cli import DiagnosticParser
    from runtime.mobile_gateway.wire import strict_json

    parser = DiagnosticParser(prog="aioa-sparkhat mission coding")
    parser.add_argument(
        "action",
        choices=(
            "create_task",
            "read_status",
            "cancel",
            "stop",
            "get_receipts",
            "start",
            "recover",
            "review_effect",
            "approve",
            "deny",
            "apply",
            "reconcile",
        ),
    )
    parser.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    payload = strict_json(args.payload.encode("utf-8"))
    return coding_cli_request(runtime, principal, args.action, payload)


def coding_http_request(connection_file, action, payload):
    """CLI client for the existing loopback host, never a Core composition root."""
    import http.client
    import os
    import re
    import stat

    from runtime.mobile_gateway.wire import strict_json

    require(
        action
        in (
            "create_task",
            "read_status",
            "get_receipts",
            "cancel",
            "stop",
            "start",
            "recover",
            "review_effect",
            "approve",
            "deny",
            "apply",
            "reconcile",
        )
        and type(payload) is dict,
        "CODING_REQUEST_SCHEMA",
    )
    path = Path(connection_file)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o077
            and info.st_size <= 8192,
            "CODING_PRIVATE_CONNECTION_REQUIRED",
        )
        raw = os.read(fd, 8193)
    finally:
        os.close(fd)
    config = strict_json(raw)
    require(
        type(config) is dict
        and set(config) == {"port", "csrf_token"}
        and type(config["port"]) is int
        and 1 <= config["port"] <= 65535
        and type(config["csrf_token"]) is str
        and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", config["csrf_token"]),
        "CODING_CONNECTION_SCHEMA",
    )
    route = "/api/agent/coding/"
    reads = {
        "read_status": "tasks",
        "get_receipts": "receipts",
        "review_effect": "review",
    }
    headers = {
        "X-AIOA-Session-Token": config["csrf_token"],
        "Content-Type": "application/json",
    }
    if action in reads:
        require(set(payload) == {"task_id"}, "CODING_REQUEST_SCHEMA")
        target = route + reads[action] + "/" + logical_id(payload["task_id"])
        method = "GET"
        body = None
    else:
        target = route + action
        method = "POST"
        body = canonical_json_bytes(payload)
        require(len(body) <= 16384, "CODING_REQUEST_BOUND")
        headers["X-AIOA-Intent"] = "coding-" + action + "-v1"
    connection = http.client.HTTPConnection("127.0.0.1", config["port"], timeout=5)
    try:
        connection.request(method, target, body, headers)
        response = connection.getresponse()
        raw = response.read(1048577)
        require(len(raw) <= 1048576, "CODING_RESPONSE_BOUND")
        require(response.status == 200, "CODING_ACK_UNKNOWN_READBACK_REQUIRED")
        from runtime.mission.codex_worker import JsonlFramer

        framer = JsonlFramer(max_bytes=1048576)
        messages = framer.feed(raw + b"\n")
        framer.finish()
        require(len(messages) == 1, "CODING_RESPONSE_SCHEMA")
        return messages[0]
    finally:
        connection.close()


def run_coding_http_cli(argv):
    from runtime.mission.cli import DiagnosticParser
    from runtime.mission.repair import RepairBoundaryError, failure_boundary
    from runtime.mobile_gateway.wire import strict_json

    parser = DiagnosticParser(prog="aioa-sparkhat mission coding")
    parser.add_argument(
        "action",
        choices=(
            "create_task",
            "read_status",
            "get_receipts",
            "cancel",
            "stop",
            "start",
            "recover",
            "review_effect",
            "approve",
            "deny",
            "apply",
            "reconcile",
        ),
    )
    parser.add_argument("--payload", required=True)
    parser.add_argument("--connection-file", required=True)
    try:
        with failure_boundary("CODING_ACK_UNKNOWN_READBACK_REQUIRED"):
            args = parser.parse_args(argv)
            result = coding_http_request(
                args.connection_file, args.action, strict_json(args.payload.encode())
            )
        code = 0
    except (ValueError, RepairBoundaryError):
        result = {
            "state": "UNKNOWN",
            "error": "CODING_ACK_UNKNOWN_READBACK_REQUIRED",
            "automatic_retry": False,
        }
        code = 5
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return code
