"""Opt-in coding intake on the existing Core transaction and receipt ports.

No server, model credential, executor, default database or automatic principal.
Pending tasks are advisory; only existing Core-signed capsules can reach review.
Execution/STOP remain on the existing registered Native routes.
"""

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.contracts import logical_id
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.patch_capsule import KIND as CAPSULE_KIND
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.warrant import require
from runtime.mission.worker import Task
from runtime.mobile_gateway.wire import verify

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
    ):
        require(
            type(journal) is CoreIntentJournal
            and type(capsules) is CorePatchCapsules
            and capsules.journal is journal,
            "EXISTING_CORE_REQUIRED",
        )
        self.journal, self.capsules = journal, capsules
        self.scope = journal.ledger.scope
        require(
            callable(clock)
            and (run_factory is None or callable(run_factory))
            and (effect_factory is None or callable(effect_factory)),
            "CODING_HOST_BINDING",
        )
        require((run_factory is None) == (run_principal is None), "CODING_HOST_BINDING")
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
        self._active, self._effects = {}, {}
        self.closed = False

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
    ):
        def change(tx):
            if admission:
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

        return self.journal._run(principal, purpose, change)

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

        self.journal.ledger.core.require(principal, Capability.MANAGE, scope=self.scope)
        require(
            self.run_factory is not None
            and self.run_principal is not None
            and not self.closed,
            "CODING_CONTROLLER_NOT_CONFIGURED",
        )
        with self._active_lock:
            # close can win while this starter waits for the lifecycle lock.
            # The durable claim and owned thread must observe that same lock.
            require(not self.closed, "CODING_CONTROLLER_CLOSED")
            if task_id in self._active:
                return self.journal._run(
                    principal,
                    Capability.MANAGE,
                    lambda tx: self._view(self._load(tx, task_id)[1]),
                )
            require(len(self._active) < 2, "CODING_ACTIVE_LIMIT")
            self._transition(
                self.run_principal,
                task_id,
                ("QUEUED",),
                "RUNNING",
                idempotent=False,
                admission=True,
            )
            cancel = CancellationToken()
            active = {"cancel": cancel, "producer": None, "thread": None}
            thread = threading.Thread(
                target=self._execute,
                args=(task_id, active),
                name="aioa-coding-" + task_id,
                daemon=True,
            )
            active["thread"] = thread
            self._active[task_id] = active
            thread.start()
        return self.journal._run(
            principal,
            Capability.MANAGE,
            lambda tx: self._view(self._load(tx, task_id)[1]),
        )

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

        self.journal._run(principal, Capability.COMMIT, save)

    def _execute(self, task_id, active):
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
                task = self.journal._run(
                    principal, Capability.COMMIT, lambda tx: self._load(tx, task_id)[2]
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
                    signed = self.capsules.prepare(
                        principal,
                        task=task,
                        source=run.source,
                        base_root=run.base_root,
                        final_root=run.producer.last_root,
                        result=result,
                        target_fingerprint=run.target_fingerprint,
                        target_revision=run.target_revision,
                        expires_at=run.expires_at,
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
                            self._active.pop(task_id, None)
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
                        unresolved = self.journal._run(
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
                    self._active.pop(task_id, None)

    def _active_cancel(self, principal, task_id):
        self.journal.ledger.core.require(principal, Capability.MANAGE, scope=self.scope)
        with self._active_lock:
            active = self._active.get(task_id)
            if active is None:
                return None
            active["cancel"].cancel()
            producer = active["producer"]
            if producer is not None:
                producer.stop()
        view = self.journal._run(
            principal,
            Capability.MANAGE,
            lambda tx: self._view(self._load(tx, task_id)[1]),
        )
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
        return not active["thread"].is_alive()

    def close(self):
        with self._active_lock:
            self.closed = True
            active = tuple(self._active.values())
            for token in self._effects.values():
                token.cancel()
            for item in active:
                item["cancel"].cancel()
                if item["producer"] is not None:
                    item["producer"].stop()
        for item in active:
            if item["thread"] is not threading.current_thread():
                item["thread"].join(5)

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
        self.journal.ledger.core.require(principal, purpose, scope=self.scope)
        fields = (
            {"task_id", "capsule_digest", "operation_digest"}
            if action in ("approve", "apply")
            else {"task_id"}
        )
        require(
            type(payload) is dict and set(payload) == fields, "CODING_REQUEST_SCHEMA"
        )
        task_id = logical_id(payload["task_id"])
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
        view = self.journal._run(
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
        self.journal.ledger.core.require(principal, purpose, scope=self.scope)
        require(
            type(payload) is dict
            and set(payload) == ({"task"} if action == "create_task" else {"task_id"}),
            "CODING_REQUEST_SCHEMA",
        )
        if action == "create_task":
            require(
                type(payload["task"]) is dict
                and set(payload["task"]) == set(Task.__dataclass_fields__),
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

            return self.journal._run(principal, purpose, create)
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

            return self.journal._run(principal, purpose, read)
        active = self._active_cancel(principal, task_id)
        if active is not None:
            return active
        with self._active_lock:
            token = self._effects.get(task_id)
            if token is not None:
                token.cancel()
                return self.journal._run(
                    principal,
                    purpose,
                    lambda tx: self._view(self._load(tx, task_id)[1]),
                )
        prior, data, task = self.journal._run(
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

        return self.journal._run(principal, purpose, cancel)

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
        self.journal.ledger.core.require(principal, Capability.COMMIT, scope=self.scope)
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

        prior, data, task, capsule = self.journal._run(
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

        return self.journal._run(principal, Capability.COMMIT, save)


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
