"""Worker advice never grants authority; finite lifecycle and hostile protocol cases."""

import importlib
import json
import unittest
from dataclasses import replace


class WorkerTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("runtime.mission.worker")
        except ModuleNotFoundError:
            self.fail("Provider-neutral WorkerPort is not implemented")

    def task(self, **changes):
        api = self.api()
        return api.Task(
            **dict(
                task_id="task-1",
                run_id="run-1",
                workspace_id="workspace-1",
                repository_id="repo-1",
                source_base_sha="a" * 40,
                instruction="Fix the bounded example.",
                deadline_at=200,
                max_events=8,
                **changes,
            )
        )

    def test_task_denies_malformed_identity_secret_and_credential_fields(self):
        api = self.api()
        task = self.task()
        for key, value in [
            ("task_id", "../escape"),
            ("source_base_sha", "main"),
            ("deadline_at", True),
            ("max_events", 257),
            ("instruction", "Authorization: Bearer " + "synthetic-credential-123"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                replace(task, **{key: value})
        with self.assertRaises(TypeError):
            api.Task(**{**task.to_dict(), "api_key": "synthetic-only"})

    def test_two_synthetic_models_share_identical_neutral_result_contract(self):
        api = self.api()
        candidate = api.CandidatePatch(
            (api.CandidateFile("calc.py", "return_value = 4\n"),)
        )
        for model in ("synthetic-a", "synthetic-b"):
            worker = api.SyntheticWorker(
                (candidate,), model_id=model, clock=lambda: 100
            )
            session = worker.start(self.task())
            events = worker.poll(session)
            result = worker.result(session)
            self.assertEqual(
                [e.kind for e in events], ["STARTED", "CANDIDATE", "COMPLETED"]
            )
            self.assertEqual(result.status, "SUCCEEDED")
            self.assertEqual(result.candidate.files[0].text, "return_value = 4\n")
            self.assertEqual(result.authority, "NONE")
            self.assertFalse(result.verified)
            self.assertEqual(result.task_id, "task-1")
            worker.close()

    def test_deadline_expires_before_any_candidate_can_be_admitted(self):
        api = self.api()
        now = [100]
        candidate = api.CandidatePatch((api.CandidateFile("x.py", "x=1\n"),))
        worker = api.SyntheticWorker((candidate,), clock=lambda: now[0])
        session = worker.start(self.task())
        now[0] = 200
        worker.poll(session)
        self.assertEqual(worker.result(session).code, "TIMEOUT")
        self.assertFalse(hasattr(worker.result(session), "candidate"))

    def test_cancel_interrupt_and_close_prevent_completion(self):
        api = self.api()
        candidate = api.CandidatePatch((api.CandidateFile("x.py", "x=1\n"),))
        for action, code in [
            ("cancel", "CANCELLED"),
            ("interrupt", "INTERRUPTED"),
            ("close", "CLOSED"),
        ]:
            with self.subTest(action=action):
                worker = api.SyntheticWorker((candidate,), clock=lambda: 100)
                session = worker.start(self.task())
                getattr(worker, action)(
                    session
                ) if action != "close" else worker.close()
                worker.poll(session)
                self.assertEqual(worker.result(session).code, code)

    def test_event_bound_is_total_even_when_the_queue_is_drained(self):
        api = self.api()
        box = api.WorkerMailbox(replace(self.task(), max_events=3), clock=lambda: 100)
        box.drain(box.session)
        for _ in range(8):
            box.progress(box.session)
            self.assertLessEqual(len(box.drain(box.session)), 3)
        self.assertEqual(box.result(box.session).code, "EVENT_LIMIT")

    def test_cross_task_session_cannot_read_or_complete_another_worker(self):
        api = self.api()
        box = api.WorkerMailbox(self.task(), clock=lambda: 100)
        forged = replace(box.session, task_id="other-task")
        with self.assertRaises(ValueError):
            box.drain(forged)
        with self.assertRaises(ValueError):
            box.complete(
                forged, api.CandidatePatch((api.CandidateFile("x.py", "x=1\n"),))
            )
        self.assertIsNone(box.result(box.session))

    def test_late_event_invalidates_unpublished_success(self):
        api = self.api()
        box = api.WorkerMailbox(self.task(), clock=lambda: 100)
        box.complete(
            box.session, api.CandidatePatch((api.CandidateFile("x.py", "x=1\n"),))
        )
        box.progress(box.session)
        self.assertEqual(box.result(box.session).code, "LATE_EVENT")

    def test_exhausted_adapter_and_secret_candidate_fail_closed(self):
        api = self.api()
        worker = api.SyntheticWorker((), clock=lambda: 100)
        session = worker.start(self.task())
        worker.poll(session)
        self.assertEqual(worker.result(session).code, "WORKER_CRASH")
        with self.assertRaises(ValueError):
            api.CandidatePatch(
                (api.CandidateFile("x.py", "api_key=synthetic-secret-value"),)
            )

    def test_event_contract_rejects_unbounded_sequence_unknown_kind_and_bad_digest(
        self,
    ):
        api = self.api()
        valid = api.WorkerEvent("session-1", "task-1", "run-1", 1, "STARTED", "b" * 64)
        for changes in (
            {"sequence": True},
            {"sequence": 257},
            {"kind": "APPROVED"},
            {"evidence_digest": "unbound"},
            {"task_id": "../wrong"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)

    def test_result_and_failure_contracts_reject_forged_payloads(self):
        api = self.api()
        candidate = api.CandidatePatch((api.CandidateFile("x.py", "x=1\n"),))
        valid = api.WorkerResult("session-1", "task-1", "run-1", candidate, "worker-1")
        for changes in ({"candidate": {}}, {"run_id": "../wrong"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)
        with self.assertRaises(ValueError):
            api.WorkerFailure("session-1", "task-1", "run-1", "raw arbitrary exception")


class ProtocolTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("runtime.mission.codex_worker")
        except ModuleNotFoundError:
            self.fail("Current Codex protocol boundary is not implemented")

    def test_fragmented_utf8_jsonl_reassembles_exact_messages(self):
        api = self.api()
        framer = api.JsonlFramer(max_bytes=1024)
        data = (
            json.dumps(
                {"method": "event", "params": {"text": "zażółć"}}, ensure_ascii=False
            )
            + "\n"
        ).encode()
        messages = []
        for b in data:
            messages.extend(framer.feed(bytes([b])))
        self.assertEqual(messages, [{"method": "event", "params": {"text": "zażółć"}}])
        framer.finish()

    def test_non_object_duplicate_nan_bad_utf8_and_truncated_eof_are_denied(self):
        api = self.api()
        for data in [
            b"[]\n",
            b"null\n",
            b'{"id":1,"id":2}\n',
            b'{"v":NaN}\n',
            b"\xff\n",
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                api.JsonlFramer(max_bytes=128).feed(data)
        f = api.JsonlFramer(max_bytes=128)
        f.feed(b'{"id":1}')
        with self.assertRaises(ValueError):
            f.finish()
        with self.assertRaises(ValueError):
            api.JsonlFramer(max_bytes=16).feed(b"x" * 17)

    def test_server_approval_is_explicitly_denied_and_cross_turn_events_fail(self):
        api = self.api()
        protocol = api.CodexProtocol("thread-1", "turn-1")
        response = protocol.observe(
            {
                "id": 8,
                "method": "item/commandExecution/requestApproval",
                "params": {"command": "echo harmless"},
            }
        )
        self.assertEqual(
            response,
            {
                "id": 8,
                "error": {
                    "code": -32601,
                    "message": "AIOA approval is required outside the worker",
                },
            },
        )
        with self.assertRaises(ValueError):
            protocol.observe(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "other-thread",
                        "turn": {"id": "turn-1", "status": "completed"},
                    },
                }
            )

    def test_turn_completion_does_not_certify_adapter_or_grant_authority(self):
        api = self.api()
        protocol = api.CodexProtocol("thread-1", "turn-1")
        protocol.observe(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "turn-1", "status": "completed"},
                },
            }
        )
        self.assertEqual(protocol.terminal_status, "SUCCEEDED")
        self.assertEqual(api.CODEX_CERTIFICATION, "NOT_CERTIFIED")
        with self.assertRaises(ValueError):
            protocol.observe(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "turn-1", "status": "completed"},
                    },
                }
            )

    def test_uncertified_codex_adapter_refuses_execution_through_worker_port(self):
        api = self.api()
        worker_api = importlib.import_module("runtime.mission.worker")
        self.assertTrue(
            hasattr(api, "CodexWorker"), "Missing fail-closed optional adapter"
        )
        adapter = api.CodexWorker(clock=lambda: 100)
        self.assertIsInstance(adapter, worker_api.WorkerPort)
        task = worker_api.Task(
            "task-1", "run-1", "workspace-1", "repo-1", "a" * 40, "Fix example.", 200
        )
        session = adapter.start(task)
        self.assertEqual(adapter.result(session).code, "NOT_CERTIFIED")
        self.assertFalse(hasattr(adapter.result(session), "candidate"))
        adapter.close()


if __name__ == "__main__":
    unittest.main()
