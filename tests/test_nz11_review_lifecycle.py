"""Deterministic lifecycle windows; real Core rows, no Git/provider effects."""

import os
import signal
import threading
import unittest
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import test_nz11_controller as support
from nv03_support import DurableTransaction

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.git_publish import CoreRemoteGitRoute
from runtime.mission.patch_capsule import KIND, ExecutionCapsule
from runtime.mission.warrant import approval_digest
from runtime.providers.exact import CancellationToken


class ReviewLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.case = support.ControllerTests(
            "test_two_active_runs_cancel_independently_without_worker_or_core_replay"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx, self.task = self.case.fx, self.case.case.task
        self.service = self.case.service()
        self.case.admit(self.service, self.task)

    def prepared_effect(self):
        """Isolate approval/lifecycle after independent route proof checks."""
        service, fx, task = self.service, self.fx, self.task
        service._transition(
            fx.p(),
            task.task_id,
            ("QUEUED",),
            "REVIEW_REQUIRED",
            capsule_digest="b" * 64,
        )
        fx.warrant = replace(
            fx.warrant,
            task_id=task.task_id,
            authority_scope=replace(
                fx.warrant.authority_scope, task_scope=task.task_id
            ),
        )
        fx.warrant = replace(fx.warrant, approval_digest=approval_digest(fx.warrant))
        reservation = replace(fx.request, task_id=task.task_id)
        route = CoreRemoteGitRoute.__new__(CoreRemoteGitRoute)
        route.journal, route.mode = fx.journal, "LOCAL_PATCH_FIXTURE"
        route.capsules, route.identity = (
            self.case.case.capsules,
            self.case.case.identity,
        )
        route.capsule = SimpleNamespace(task_id=task.task_id, digest="b" * 64)
        route.plan = SimpleNamespace(digest="a" * 64)
        route.core, route.scope = fx.core, fx.ledger.scope
        route.target_guard, route.check = nullcontext, lambda: None
        route.operation = lambda session, epoch: fx.operation
        # Proofs/target freshness have separate integration gates. These tests
        # isolate the existing final Core owner-witness persistence boundary.
        route._local_warrant = lambda *_: None
        route._local_proofs = lambda *_args, **_kwargs: None
        service.effect_factory = lambda *_: (route, fx.warrant, reservation)
        preview = service.request(
            fx.p(Capability.READ), "review_effect", {"task_id": task.task_id}
        )["effect_preview"]
        exact = {
            key: preview[key]
            for key in ("task_id", "capsule_digest", "operation_digest")
        }
        return route, exact

    def test_owner_witness_and_approved_receipt_rollback_together(self):
        _route, exact = self.prepared_effect()
        original = self.service._save

        def fail(tx, prior, data):
            if data["receipts"][-1]["receipt"]["state"] == "APPROVED":
                raise ValueError("FIXTURE_AFTER_STAGED_OWNER_WITNESS")
            return original(tx, prior, data)

        with (
            patch.object(self.service, "_save", side_effect=fail),
            self.assertRaisesRegex(MemoryPatchError, "TRANSACTION_FAILED"),
        ):
            self.service.request(self.fx.p(Capability.OWNER_APPROVAL), "approve", exact)
        witness = self.fx.journal._run(
            self.fx.p(Capability.READ),
            Capability.READ,
            lambda tx: tx.get(
                RecordKind.APPROVAL, self.fx.ledger._key(self.fx.warrant)
            ),
        )
        self.assertIsNone(witness)
        self.assertEqual(
            self.service.request(
                self.fx.p(Capability.READ),
                "read_status",
                {"task_id": self.task.task_id},
            )["state"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(
            self.service.request(
                self.fx.p(Capability.OWNER_APPROVAL), "approve", exact
            )["state"],
            "APPROVED",
        )

    def test_exact_existing_witness_repairs_old_split_and_repeat_is_idempotent(self):
        _route, exact = self.prepared_effect()
        self.fx.ledger.approve(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)
        # Recreate the controller: a pre-fix process left only its witness.
        restarted = self.case.service(effect_factory=self.service.effect_factory)
        first = restarted.request(
            self.fx.p(Capability.OWNER_APPROVAL), "approve", exact
        )
        second = restarted.request(
            self.fx.p(Capability.OWNER_APPROVAL), "approve", exact
        )
        self.assertEqual(first, second)
        self.assertEqual(first["state"], "APPROVED")
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)
        with self.assertRaises(ValueError):
            restarted.request(self.fx.p(Capability.OWNER_APPROVAL), "approve", exact)

    def test_process_crash_after_atomic_commit_preserves_readback_and_exact_retry(self):
        _route, exact = self.prepared_effect()
        original = DurableTransaction.commit
        child = os.fork()
        if child == 0:
            signal.alarm(15)

            def crash_after_commit(tx):
                approved = any(
                    row.payload.get("schema") == "aioa.coding-task.v1"
                    and row.payload["receipts"][-1]["receipt"]["state"] == "APPROVED"
                    for row in tx.snapshot.values()
                )
                original(tx)
                if approved and tx.context.purpose is Capability.OWNER_APPROVAL:
                    os._exit(75)

            with patch.object(DurableTransaction, "commit", new=crash_after_commit):
                self.service.request(
                    self.fx.p(Capability.OWNER_APPROVAL), "approve", exact
                )
            os._exit(76)
        _, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 75)
        self.service.close()
        restarted = self.case.service(effect_factory=self.service.effect_factory)
        view = restarted.request(
            self.fx.p(Capability.READ), "get_receipts", {"task_id": self.task.task_id}
        )
        self.assertEqual(view["state"], "APPROVED")
        approved_receipts = [
            r for r in view["receipts"] if r["receipt"]["state"] == "APPROVED"
        ]
        self.assertEqual(len(approved_receipts), 1)
        retried = restarted.request(
            self.fx.p(Capability.OWNER_APPROVAL), "approve", exact
        )
        self.assertEqual(retried["receipt_count"], view["receipt_count"])
        self.assertEqual(
            restarted.request(
                self.fx.p(Capability.READ),
                "get_receipts",
                {"task_id": self.task.task_id},
            )["receipts"],
            view["receipts"],
        )
        # A new Native admission session may inspect that history but cannot
        # resurrect its old owner witness for prospective use.
        with patch.object(self.fx.core, "_session", "restarted-native-session"):
            self.assertEqual(
                restarted.request(
                    self.fx.p(Capability.READ),
                    "read_status",
                    {"task_id": self.task.task_id},
                )["state"],
                "APPROVED",
            )
            with self.assertRaisesRegex(ValueError, "OWNER_SESSION_CHANGED"):
                restarted.request(
                    self.fx.p(Capability.OWNER_APPROVAL), "approve", exact
                )

    def test_approved_cancellation_through_core_api_cannot_later_dispatch(self):
        route, exact = self.prepared_effect()
        self.service.request(self.fx.p(Capability.OWNER_APPROVAL), "approve", exact)
        with patch.object(route, "dispatch") as dispatch:
            stopped = self.service.request(
                self.fx.p(Capability.MANAGE), "stop", {"task_id": self.task.task_id}
            )
            self.assertEqual(stopped["state"], "CANCELLED")
            with self.assertRaisesRegex(ValueError, "CODING_TASK_INACTIVE"):
                self.service.request(self.fx.p(), "apply", exact)
            dispatch.assert_not_called()

    def test_stop_and_close_cannot_miss_an_applying_effect_token(self):
        route, exact = self.prepared_effect()
        self.service.request(self.fx.p(Capability.OWNER_APPROVAL), "approve", exact)
        original = self.service._transition
        observed = {"dispatches": 0}

        def handoff(principal, task_id, expected, state, **kwargs):
            result = original(principal, task_id, expected, state, **kwargs)
            if state == "APPLYING":
                try:
                    self.service.request(
                        self.fx.p(Capability.MANAGE), "stop", {"task_id": task_id}
                    )
                except ValueError as error:
                    observed["stop_denial"] = str(error)
                self.service.close()
            return result

        def dispatch(*_args, cancel, **_kwargs):
            observed["dispatches"] += 1
            observed["dispatch_cancelled"] = cancel.cancelled
            return {"outcome": {"contract_type": "Unknown"}}

        route.dispatch = dispatch
        with patch.object(self.service, "_transition", side_effect=handoff):
            result = self.service.request(self.fx.p(), "apply", exact)
        self.assertNotIn("stop_denial", observed)
        self.assertEqual(observed["dispatches"], 0)
        self.assertEqual(result["state"], "UNKNOWN")

    def test_closed_controller_cannot_claim_an_approved_effect(self):
        _route, exact = self.prepared_effect()
        self.service.request(self.fx.p(Capability.OWNER_APPROVAL), "approve", exact)
        self.service.close()
        with self.assertRaisesRegex(ValueError, "CODING_CONTROLLER_CLOSED"):
            self.service.request(self.fx.p(), "apply", exact)
        self.assertEqual(
            self.service.request(
                self.fx.p(Capability.READ),
                "read_status",
                {"task_id": self.task.task_id},
            )["state"],
            "APPROVED",
        )

    def test_acknowledged_stop_cannot_be_followed_by_review_publication(self):
        service, fx, task, proposal = (
            self.service,
            self.fx,
            self.task,
            self.case.case.patch,
        )
        fx.ledger.clock = lambda: datetime.fromtimestamp(100, UTC)
        service._transition(fx.p(), task.task_id, ("QUEUED",), "RUNNING")
        capsule = ExecutionCapsule(
            task.task_id,
            task.run_id,
            task.workspace_id,
            task.repository_id,
            proposal.worker_session_id,
            task.source_base_sha,
            proposal.base_tree_sha256,
            proposal.final_tree_sha256,
            task.digest,
            proposal.patchset_sha256,
            "f" * 64,
            self.case.case.case.profile().digest,
            canonical_sha256(service.scope),
            tuple("sha256:" + char * 64 for char in "345"),
            tuple(char * 64 for char in "678"),
            100,
            200,
            "sha256:" + "9" * 64,
            "target-1",
        )
        receipt = {
            "schema": "aioa.patch-review-receipt.v1",
            "state": "REVIEW_REQUIRED",
            "capsule": capsule.payload(),
            "capsule_digest": capsule.digest,
            "authority": "NONE",
        }
        signed = {
            "receipt": receipt,
            "signature": self.case.case.identity.sign(receipt),
            "signer_spki": self.case.case.identity.spki,
        }
        fx.journal._run(
            fx.p(),
            Capability.COMMIT,
            lambda tx: tx.insert(
                StoredRecord(
                    RecordKind.OPERATION,
                    canonical_sha256([KIND, capsule.digest]),
                    service.scope,
                    1,
                    signed,
                )
            ),
        )
        active = {
            "cancel": CancellationToken(),
            "producer": None,
            "thread": threading.current_thread(),
        }
        service._active[task.task_id] = active
        try:
            stopped = service.request(
                fx.p(Capability.MANAGE), "stop", {"task_id": task.task_id}
            )
            self.assertTrue(stopped["cancel_requested"])
            with self.assertRaisesRegex(ValueError, "CODING_CANCELLED"):
                service.attach_review(fx.p(), task.task_id, capsule.digest)
            self.assertNotEqual(
                service.request(
                    fx.p(Capability.READ), "read_status", {"task_id": task.task_id}
                )["state"],
                "REVIEW_REQUIRED",
            )
        finally:
            service._active.clear()


if __name__ == "__main__":
    unittest.main()
