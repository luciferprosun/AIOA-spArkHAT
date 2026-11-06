"""CLI and AgentRuntime use the same admitted Core and durable receipts."""

import importlib
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from q09_support import Fixture

from runtime.core_admission import Capability
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.worker import Task
from runtime.mobile_gateway.wire import Identity


class IntakeTests(unittest.TestCase):
    def test_two_distinct_fixture_adapters_share_policy_without_model_authority(self):
        from test_hybrid_repair import DirectoryProducer

        import runtime.mission.repair as repair
        from runtime.mission.patchset import BoundedPatchSetPolicy, observe_source
        from runtime.mission.worker import (
            CandidateFile,
            CandidatePatch,
            SyntheticWorker,
            WorkerMailbox,
            WorkerPort,
        )

        class ProgressAdapter:
            def start(self, task):
                self.box = WorkerMailbox(
                    task, worker_id="progress-fixture", clock=lambda: 100
                )
                return self.box.session

            def poll(self, session):
                self.box.progress(session)
                self.box.complete(
                    session,
                    CandidatePatch(
                        (CandidateFile("calc.py", "def add(a,b):\n    return b+a\n"),)
                    ),
                )
                return self.box.drain(session)

            def result(self, session):
                return self.box.result(session)

            def cancel(self, session):
                self.box.fail(session, "CANCELLED")

            def interrupt(self, session):
                self.box.fail(session, "INTERRUPTED")

            def close(self):
                self.box.fail(self.box.session, "CLOSED")

        base = self.root / "base"
        base.mkdir(mode=0o700)
        (base / "calc.py").write_text("def add(a,b):\n    return a-b\n")
        (base / "calc.py").chmod(0o644)
        source = observe_source(
            base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        candidate = CandidatePatch(
            (CandidateFile("calc.py", "def add(a,b):\n    return a+b\n"),)
        )
        workers = (SyntheticWorker((candidate,), clock=lambda: 100), ProgressAdapter())
        self.assertNotEqual(type(workers[0]), type(workers[1]))
        for index, worker in enumerate(workers):
            self.assertIsInstance(worker, WorkerPort)
            root = self.root / str(index)
            root.mkdir(mode=0o700)
            producer = DirectoryProducer(repair, base, root, self.task, ())
            producer.worker = worker
            proposed = producer.produce(0, None)
            patch = BoundedPatchSetPolicy().evaluate(
                base,
                proposed.root,
                source=source,
                task=self.task,
                worker_session_id=proposed.session.session_id,
            )
            self.assertEqual(patch.files[0].operation, "MODIFY")
            self.assertEqual(proposed.worker_result.authority, "NONE")
            producer.close()

    def api(self):
        try:
            return importlib.import_module("runtime.mission.coding_tasks")
        except ModuleNotFoundError:
            self.fail("Same-Core coding intake is not implemented")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fx = Fixture(self.root / "core.json")
        self.addCleanup(self.fx.close)
        self.capsules = CorePatchCapsules(
            self.fx.journal,
            Identity(ec.generate_private_key(ec.SECP256R1())),
            source_probe=lambda: None,
        )
        self.task = Task(
            "coding-1",
            "run-1",
            "workspace-1",
            "repo-1",
            "a" * 40,
            "Fix arithmetic.",
            200,
        )

    def service(self):
        return self.api().CoreCodingTasks(self.fx.journal, self.capsules)

    def test_cli_create_read_receipts_cancel_and_repeat_use_one_core(self):
        api = self.api()
        service = self.service()
        from runtime.main import AgentRuntime

        runtime = AgentRuntime(
            None, "", self.root, inspection_only=True, coding_tasks=service
        )
        self.addCleanup(runtime.close)
        result = api.run_coding_cli(
            ["create_task", "--payload", json.dumps({"task": asdict(self.task)})],
            runtime=runtime,
            principal=self.fx.p(Capability.MANAGE),
        )
        self.assertEqual(result["state"], "QUEUED")
        status = api.coding_cli_request(
            runtime,
            self.fx.p(Capability.READ),
            "read_status",
            {"task_id": self.task.task_id},
        )
        self.assertEqual(status["task_digest"], self.task.digest)
        self.assertEqual(status["authority"], "NONE")
        receipts = runtime.coding_request(
            "get_receipts",
            {"task_id": self.task.task_id},
            principal=self.fx.p(Capability.READ),
        )
        self.assertEqual(len(receipts["receipts"]), 1)
        cancelled = runtime.coding_request(
            "cancel",
            {"task_id": self.task.task_id},
            principal=self.fx.p(Capability.MANAGE),
        )
        self.assertEqual(cancelled["state"], "CANCELLED")
        before = (self.root / "core.json").read_bytes()
        again = runtime.coding_request(
            "cancel",
            {"task_id": self.task.task_id},
            principal=self.fx.p(Capability.MANAGE),
        )
        self.assertEqual(again, cancelled)
        self.assertEqual(before, (self.root / "core.json").read_bytes())

    def test_model_approval_fields_and_wrong_purpose_are_rejected_without_history(self):
        service = self.service()
        for principal in (
            None,
            {"approved": True},
            self.fx.p(Capability.READ),
            self.fx.core.critic_candidate(),
        ):
            with self.assertRaises(ValueError):
                service.request(principal, "create_task", {"task": asdict(self.task)})
        for payload in (
            {"task": asdict(self.task), "approved": True},
            {"task": {**asdict(self.task), "credentials": "forbidden"}},
        ):
            with self.assertRaises(ValueError):
                service.request(self.fx.p(Capability.MANAGE), "create_task", payload)

    def test_duplicate_task_is_idempotent_but_changed_run_or_instruction_is_denied(
        self,
    ):
        service = self.service()
        principal = self.fx.p(Capability.MANAGE)
        first = service.request(principal, "create_task", {"task": asdict(self.task)})
        before = (self.root / "core.json").read_bytes()
        self.assertEqual(
            first,
            service.request(principal, "create_task", {"task": asdict(self.task)}),
        )
        self.assertEqual(before, (self.root / "core.json").read_bytes())
        with self.assertRaises(ValueError):
            service.request(
                principal,
                "create_task",
                {"task": asdict(replace(self.task, run_id="other"))},
            )

    def test_runtime_requires_explicit_same_core_binding_and_is_inert_by_default(self):
        self.api()
        from runtime.main import AgentRuntime

        runtime = AgentRuntime(None, "", self.root, inspection_only=True)
        self.addCleanup(runtime.close)
        with self.assertRaises(ValueError):
            runtime.coding_request("read_status", {"task_id": "x"}, principal=None)
        with self.assertRaises(ValueError):
            AgentRuntime(None, "", self.root, inspection_only=True, coding_tasks={})

    def test_task_cannot_claim_verified_without_core_capsule_or_supply_state(self):
        service = self.service()
        service.request(
            self.fx.p(Capability.MANAGE), "create_task", {"task": asdict(self.task)}
        )
        for action, payload in (
            ("set_state", {"state": "VERIFIED"}),
            ("approve", {"approved": True}),
            ("read_status", {"task_id": self.task.task_id, "state": "VERIFIED"}),
        ):
            with self.assertRaises(ValueError):
                service.request(
                    self.fx.p(),
                    "set_state" if action == "set_state" else action,
                    payload,
                )
        with self.assertRaises(ValueError):
            service.attach_review(self.fx.p(), self.task.task_id, "b" * 64)


if __name__ == "__main__":
    unittest.main()
