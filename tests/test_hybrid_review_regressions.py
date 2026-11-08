"""Security regressions from the one whole-candidate review."""

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest import mock

import test_hybrid_repair as support
from cryptography.hazmat.primitives.asymmetric import ec
from q09_support import Fixture

import runtime.mission.patchset as policy
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence import ports
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission import repair
from runtime.mission.git_publish import VerifiedPatchSet
from runtime.mission.patch_capsule import (
    KIND,
    CorePatchCapsules,
    ExecutionCapsule,
    capsule_dependencies,
    capsule_operation,
)
from runtime.mission.repair_validation import TrustedTestProfile
from runtime.mission.warrant import approval_digest
from runtime.mobile_gateway.wire import Identity


class ReviewRegressions(unittest.TestCase):
    def repair_case(self):
        fixture = support.RepairTests(
            "test_one_failed_attempt_then_repair_reaches_reviewed_patch"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_I1_arbitrary_exec_profile_cannot_receive_builtin_certification(self):
        script = b"namespace={}\nexec(compile(workspace['calc.py'],'calc.py','exec'),namespace)\ncheck(True)\n"
        with self.assertRaises(ValueError):
            TrustedTestProfile(
                "calculator-fixed-v1",
                tuple((s, script) for s in repair.TEST_STAGES),
                tuple((s, 3) for s in repair.TEST_STAGES),
            )

    def test_I2_self_hashed_loop_cannot_skip_independent_semantic_review(self):
        fixture = self.repair_case()
        fx = Fixture(fixture.root / "review-core.json")
        self.addCleanup(fx.close)
        now = int(fx.warrant.issued_at.timestamp())
        task = replace(fixture.task, deadline_at=now + 200)
        producer = support.DirectoryProducer(
            repair,
            fixture.base,
            fixture.root,
            task,
            (fixture.candidate("a+b  # noqa"),),
        )
        denied = fixture.coordinator.run(
            task=task,
            source=fixture.source,
            base_root=fixture.base,
            producer=producer,
            validator=support.FaultBackend(repair, ["PASS"]),
        )
        self.assertEqual(denied.failure_code, "REVIEW_TEST_BYPASS")
        patch = policy.BoundedPatchSetPolicy().evaluate(
            fixture.base,
            fixture.root / "attempt-0",
            source=fixture.source,
            task=task,
            worker_session_id=denied.attempts[-1].worker_session_id,
        )
        steps = tuple(
            replace(
                step,
                core_warrant_digest="sha256:" + str(i + 3) * 64,
                evidence_digest=str(i + 6) * 64,
            )
            for i, step in enumerate(denied.attempts[-1].steps)
        )
        forged = repair.RepairLoopResult(
            task.task_id,
            task.run_id,
            "PATCH_READY",
            ("INDEPENDENT_REVIEW", "PATCH_READY"),
            (replace(denied.attempts[-1], status="PASS", steps=steps),),
            patch,
            None,
        )
        service = CorePatchCapsules(
            fx.journal,
            Identity(ec.generate_private_key(ec.SECP256R1())),
            source_probe=lambda: fixture.source,
        )
        with self.assertRaisesRegex(ValueError, "CAPSULE_REVIEW_DENIED"):
            service.prepare(
                fx.p(),
                task=task,
                source=fixture.source,
                base_root=fixture.base,
                final_root=fixture.root / "attempt-0",
                result=forged,
                target_fingerprint=fx.warrant.target_fingerprint,
                target_revision="revision-1",
                expires_at=now + 120,
            )

    def test_I3_nested_parent_swap_during_second_census_is_denied(self):
        fixture = self.repair_case()
        for tree, expression in (
            (fixture.base, "a-b"),
            (fixture.root / "final", "a+b"),
        ):
            tree.mkdir(mode=0o700, exist_ok=True)
            if (tree / "calc.py").exists():
                (tree / "calc.py").unlink()
            (tree / "one").mkdir(mode=0o700)
            (tree / "one/two").mkdir(mode=0o700)
            target = tree / "one/two/calc.py"
            target.write_text("def add(a,b):\n    return " + expression + "\n")
            target.chmod(0o644)
        source = policy.observe_source(
            fixture.base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        original = policy._read_regular
        hits = [0]
        final = fixture.root / "final"

        def race(fd, name, expected, **kwargs):
            raw = original(fd, name, expected, **kwargs)
            if raw.endswith(b"return a+b\n"):
                hits[0] += 1
                if hits[0] == 2:
                    (final / "one/two").rename(fixture.root / "outside")
                    (final / "one/two").symlink_to(
                        fixture.root / "outside", target_is_directory=True
                    )
            return raw

        with (
            mock.patch.object(policy, "_read_regular", side_effect=race),
            self.assertRaises(ValueError),
        ):
            policy.BoundedPatchSetPolicy().evaluate(
                fixture.base,
                final,
                source=source,
                task=fixture.task,
                worker_session_id="worker-1",
            )
        self.assertEqual(hits[0], 2)

    def _final_race(self, where, kind):
        fixture = self.repair_case()
        now = [100]
        cancelled = [False]
        producer = support.DirectoryProducer(
            repair,
            fixture.base,
            fixture.root,
            fixture.task,
            (fixture.candidate("a+b"),),
        )
        backend = support.FaultBackend(repair, ["PASS"])

        def trigger():
            if kind == "cancel":
                cancelled[0] = True
            else:
                now[0] = fixture.task.deadline_at

        if where == "stage":
            original_open = backend.open

            def open_session(root, patch):
                session = original_open(root, patch)
                original_run = session.run

                def run(stage):
                    result = original_run(stage)
                    if stage == "FINAL_TESTS":
                        trigger()
                    return result

                session.run = run
                return session

            backend.open = open_session
        else:
            original_close = producer.close

            def close():
                result = original_close()
                trigger()
                return result

            producer.close = close
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: now[0]).run(
            task=fixture.task,
            source=fixture.source,
            base_root=fixture.base,
            producer=producer,
            validator=backend,
            cancelled=lambda: cancelled[0],
        )
        self.assertNotEqual(result.status, "PATCH_READY")
        self.assertIsNone(result.final_patchset)
        self.assertEqual(result.status, "CANCELLED" if kind == "cancel" else "FAILED")

    def test_I4_final_stage_cancel_and_deadline_never_publish_success(self):
        for kind in ("cancel", "deadline"):
            with self.subTest(kind=kind):
                self._final_race("stage", kind)

    def test_I4_final_cleanup_cancel_and_deadline_never_publish_success(self):
        for kind in ("cancel", "deadline"):
            with self.subTest(kind=kind):
                self._final_race("close", kind)

    def test_I5_hash_consistent_301_line_dto_cannot_convert_to_remote_plan(self):
        fixture = self.repair_case()
        raw = b"x=1\n" * 301
        after = policy.FileIdentity(hashlib.sha256(raw).hexdigest(), len(raw), 0o644)
        patch = policy.PatchSet(
            fixture.task.task_id,
            fixture.task.run_id,
            "workspace-1",
            "1445911975",
            fixture.task.digest,
            "worker-1",
            "a" * 40,
            "b" * 64,
            "c" * 64,
            (policy.FileChange("agent-demo/proposal.py", "ADD", None, after, 1, 0),),
            "diff --aioa a/agent-demo/proposal.py b/agent-demo/proposal.py\n+safe\n",
        )
        with self.assertRaises(ValueError):
            prepared = VerifiedPatchSet(
                patch, (("agent-demo/proposal.py", raw),), "d" * 64
            )
            prepared.create_only_plan(
                title="Add file",
                body="Reviewed.",
                operation_id="e" * 32,
                issued_at=100,
                base_tree_sha="f" * 40,
                source_reply_sha256="1" * 64,
                source_receipt_sha256="2" * 64,
            )

    def test_I6_work_budget_is_checked_before_sequence_matcher(self):
        with (
            mock.patch.object(
                policy.difflib,
                "SequenceMatcher",
                side_effect=AssertionError("unbounded matching reached"),
            ),
            self.assertRaises(ValueError),
        ):
            policy._counts("x\n" * 32767, "x\n" * 32766 + "y\n")

    def test_I5_valid_add_without_canonical_capsule_cannot_convert(self):
        from runtime.mission.git_publish import CoreRemoteGitRoute

        fixture = self.repair_case()
        final = fixture.root / "add-final"
        final.mkdir(mode=0o700)
        (final / "calc.py").write_bytes((fixture.base / "calc.py").read_bytes())
        (final / "calc.py").chmod(0o644)
        (final / "agent-demo").mkdir(mode=0o700)
        (final / "agent-demo/proposal.py").write_bytes(b"VALUE = 1\n")
        (final / "agent-demo/proposal.py").chmod(0o644)
        task = replace(fixture.task, repository_id="1445911975")
        source = policy.observe_source(
            fixture.base,
            repository_id=task.repository_id,
            workspace_id=task.workspace_id,
            source_base_sha=task.source_base_sha,
        )
        prepared = CoreRemoteGitRoute.prepare_patchset(
            fixture.base,
            final,
            source=source,
            task=task,
            worker_session_id="worker-1",
            capsule_digest="d" * 64,
        )
        with self.assertRaisesRegex(
            ValueError, "GITHUB_PATCH_CONVERSION_NOT_QUALIFIED"
        ):
            prepared.create_only_plan(
                title="Add file",
                body="Reviewed.",
                operation_id="e" * 32,
                issued_at=100,
                base_tree_sha="f" * 40,
                source_reply_sha256="1" * 64,
                source_receipt_sha256="2" * 64,
            )

    def test_I7_source_probe_runs_outside_retryable_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            fx = Fixture(Path(directory) / "core.json")
            self.addCleanup(fx.close)
            now = int(fx.warrant.issued_at.timestamp())
            source = policy.SourceIdentity("repo-1", "workspace-1", "a" * 40, "b" * 64)
            capsule = ExecutionCapsule(
                "capsule-task",
                "run-1",
                "workspace-1",
                "repo-1",
                "worker-1",
                "a" * 40,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "1" * 64,
                canonical_sha256(fx.ledger.scope),
                tuple("sha256:" + str(i) * 64 for i in (3, 4, 5)),
                tuple(str(i) * 64 for i in (6, 7, 8)),
                now,
                now + 120,
                fx.warrant.target_fingerprint,
                "revision-1",
            )
            identity = Identity(ec.generate_private_key(ec.SECP256R1()))
            receipt = {
                "schema": "aioa.patch-review-receipt.v1",
                "state": "REVIEW_REQUIRED",
                "capsule": capsule.payload(),
                "capsule_digest": capsule.digest,
                "authority": "NONE",
            }
            record = {
                "receipt": receipt,
                "signature": identity.sign(receipt),
                "signer_spki": identity.spki,
            }

            def insert(tx):
                tx.insert(
                    StoredRecord(
                        RecordKind.OPERATION,
                        canonical_sha256([KIND, capsule.digest]),
                        fx.ledger.scope,
                        1,
                        record,
                    )
                )

            fx.journal._run(fx.p(), Capability.COMMIT, insert)
            states = []

            def probe():
                states.append(ports._IN_TRANSACTION.get())
                return source

            service = CorePatchCapsules(fx.journal, identity, source_probe=probe)
            operation = capsule_operation(capsule)
            scope = replace(
                fx.warrant.authority_scope,
                operation_classes=(operation["operation_class"],),
                task_scope=capsule.task_id,
                target_scope=capsule.target_fingerprint,
                expires_at=fx.warrant.issued_at + timedelta(seconds=120),
            )
            warrant = replace(
                fx.warrant,
                task_id=capsule.task_id,
                operation_class=operation["operation_class"],
                authority_scope=scope,
                operation_hash="sha256:" + canonical_sha256(operation),
                target_fingerprint=capsule.target_fingerprint,
                expected_target_revision=capsule.target_revision,
                decision_dependency_root=capsule_dependencies(capsule),
                expires_at=scope.expires_at,
            )
            warrant = replace(warrant, approval_digest=approval_digest(warrant))
            service.approve(fx.p(Capability.OWNER_APPROVAL), capsule.digest, warrant)
            service.require_approved(fx.p(), capsule.digest, warrant)
            self.assertEqual(states, [False, False])
