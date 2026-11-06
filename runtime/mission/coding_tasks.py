"""Opt-in coding intake on the existing Core transaction and receipt ports.

No server, model credential, executor, default database or automatic principal.
Pending tasks are advisory; only existing Core-signed capsules can reach review.
Execution/STOP remain on the existing registered Native routes.
"""

import json
from dataclasses import asdict

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
STATES = (
    "QUEUED",
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


class CoreCodingTasks:
    def __init__(self, journal, capsules):
        require(
            type(journal) is CoreIntentJournal
            and type(capsules) is CorePatchCapsules
            and capsules.journal is journal,
            "EXISTING_CORE_REQUIRED",
        )
        self.journal, self.capsules = journal, capsules
        self.scope = journal.ledger.scope

    def _key(self, task_id):
        logical_id(task_id)
        return canonical_sha256([KIND, task_id])

    def _load(self, tx, task_id):
        row = tx.get(RecordKind.OPERATION, self._key(task_id))
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
            verify(self.capsules.identity.spki, signed["signature"], proof)
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
            "effects_registered": False,
        }

    def request(self, principal, action, payload):
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
                return result

            return self.journal._run(principal, purpose, read)
        prior, data, task = self.journal._run(
            principal, purpose, lambda tx: self._load(tx, task_id)
        )
        state = data["receipts"][-1]["receipt"]["state"]
        if state == "CANCELLED":
            return self._view(data)
        require(
            state in ("QUEUED", "PLANNED", "PATCH_READY", "REVIEW_REQUIRED"),
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
                in ("QUEUED", "REVIEW_REQUIRED"),
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
        "action", choices=("create_task", "read_status", "cancel", "get_receipts")
    )
    parser.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    payload = strict_json(args.payload.encode("utf-8"))
    return coding_cli_request(runtime, principal, args.action, payload)
