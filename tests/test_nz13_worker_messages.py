"""Candidate messages are inert, strictly bound advice, never effect authority."""
import json
import unittest
from dataclasses import replace

from runtime.nonzero_cloudops import module_descriptor

AVAILABLE = module_descriptor()['available']
if AVAILABLE:
    from runtime.mission.worker import (
        Task,
        WorkerError,
        WorkerFailure,
        WorkerMailbox,
        WorkerResult,
    )


@unittest.skipUnless(AVAILABLE, 'NonZero optional extra is not installed')
class CandidateMessageTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.task = Task('task-1', 'run-1', 'workspace-1', 'repo-1', 'a'*40, 'Repair a neutral fixture.', 200)
        self.box = WorkerMailbox(self.task, worker_id='fixture-model', clock=lambda: self.now)
        self.session = self.box.session

    def message(self, **changes):
        body = {'schema': 'aioa.worker-candidate.v1', 'task_id': self.task.task_id,
                'run_id': self.task.run_id, 'session_id': self.session.session_id,
                'task_digest': self.task.digest,
                'files': [{'path': 'src/calc.py', 'text': 'def add(a, b):\n    return a + b\n'}]}
        body.update(changes)
        return json.dumps(body).encode()

    def admit(self, raw, *, tokens=32, box=None, session=None):
        value = box or self.box
        method = getattr(value, 'complete_json', None)
        self.assertTrue(callable(method), 'WorkerMailbox lacks strict candidate message admission')
        return method(session or self.session, raw, completion_tokens=tokens)

    def refused(self, raw, *, tokens=32):
        result = self.admit(raw, tokens=tokens)
        self.assertIs(type(result), WorkerFailure)
        self.assertEqual(result.code, 'PROTOCOL')
        self.assertEqual(result.authority, 'NONE')
        self.assertNotIn('CANDIDATE', [event.kind for event in self.box.drain(self.session)])
        return result

    def test_bound_message_yields_unverified_candidate_and_bounded_events(self):
        result = self.admit(self.message())
        self.assertIs(type(result), WorkerResult)
        self.assertEqual(result.candidate.files[0].path, 'src/calc.py')
        self.assertEqual(result.candidate.files[0].text, 'def add(a, b):\n    return a + b\n')
        self.assertFalse(result.verified)
        self.assertEqual(result.authority, 'NONE')
        events = self.box.drain(self.session)
        self.assertEqual([e.kind for e in events], ['STARTED', 'CANDIDATE', 'COMPLETED'])
        self.assertEqual([e.sequence for e in events], [1, 2, 3])
        self.assertEqual(events[-1].evidence_digest, result.candidate.digest)

    def test_task_budget_is_part_of_the_admitted_task_digest(self):
        from inspect import signature
        self.assertIn('max_output_tokens', signature(Task).parameters,
                      'Output token budget is absent from canonical Task')
        limited = replace(self.task, max_output_tokens=64)
        self.assertNotEqual(limited.digest, self.task.digest)
        for value in (True, 0, -1, 4097, '64'):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                replace(self.task, max_output_tokens=value)

    def test_other_run_task_session_or_digest_fails_without_candidate(self):
        for key in ('run_id', 'task_id', 'session_id', 'task_digest'):
            with self.subTest(field=key):
                self.box = WorkerMailbox(self.task, clock=lambda: self.now)
                self.session = self.box.session
                self.refused(self.message(**{key: 'different'}))

    def test_duplicate_json_fields_are_refused(self):
        raw = self.message().replace(b'"schema":', b'"schema":"duplicate","schema":', 1)
        self.refused(raw)

    def test_nonfinite_invalid_utf8_and_incomplete_json_are_refused(self):
        for raw in (b'{}NaN', b'{"files":NaN}', b'\xff', b'{', b'null', b'[]'):
            with self.subTest(size=len(raw)):
                self.box = WorkerMailbox(self.task, clock=lambda: self.now)
                self.session = self.box.session
                self.refused(raw)

    def test_extensions_commands_and_claims_of_authority_are_refused(self):
        for key in ('command', 'authority', 'approval', 'tool_calls', 'completion_tokens'):
            with self.subTest(field=key):
                self.box = WorkerMailbox(self.task, clock=lambda: self.now)
                self.session = self.box.session
                self.refused(self.message(**{key: 'not-an-authority'}))

    def test_file_contract_is_closed_and_secret_bearing_content_is_refused(self):
        cases = ([], [{'path': 'x.py', 'text': 'ok', 'command': 'forbidden'}],
                 [{'path': 'x.py', 'text': 1}],
                 [{'path': 'x.py', 'text': 'ghu_'+'A'*40}],
                 [{'path': 'x.py', 'text': 'a'}, {'path': 'x.py', 'text': 'b'}],
                 [{'path': str(i)+'.py', 'text': 'a'} for i in range(4)])
        for files in cases:
            with self.subTest(file_count=len(files)):
                self.box = WorkerMailbox(self.task, clock=lambda: self.now)
                self.session = self.box.session
                self.refused(self.message(files=files))

    def test_usage_outside_message_is_required_typed_and_bounded(self):
        for tokens in (None, True, 0, -1, 4097, '32'):
            with self.subTest(kind=type(tokens).__name__):
                self.box = WorkerMailbox(self.task, clock=lambda: self.now)
                self.session = self.box.session
                self.refused(self.message(), tokens=tokens)

    def test_oversize_message_fails_before_parsing_and_cannot_retry(self):
        result = self.refused(b' '*65537)
        self.assertIs(self.admit(self.message()), result)
        self.assertIs(self.box.result(self.session), result)

    def test_cancel_timeout_and_late_messages_do_not_emit_candidates(self):
        self.box.fail(self.session, 'CANCELLED')
        result = self.admit(self.message())
        self.assertEqual(result.code, 'CANCELLED')
        self.box = WorkerMailbox(self.task, clock=lambda: self.now)
        self.session = self.box.session
        self.now = 201
        self.assertEqual(self.admit(self.message()).code, 'TIMEOUT')
        self.now = 100
        self.box = WorkerMailbox(self.task, clock=lambda: self.now)
        self.session = self.box.session
        self.assertIs(type(self.admit(self.message())), WorkerResult)
        self.assertEqual(self.admit(self.message()).code, 'LATE_EVENT')

    def test_stale_handle_does_not_change_current_session(self):
        other = WorkerMailbox(self.task, clock=lambda: self.now)
        with self.assertRaises(WorkerError):
            self.admit(self.message(), session=other.session)
        self.assertIsNone(self.box.result(self.session))
        self.assertEqual([event.kind for event in self.box.drain(self.session)], ['STARTED'])

    def test_legacy_task_digest_stays_bound_to_original_eight_fields(self):
        import hashlib

        legacy = {
            "task_id": "task-1", "run_id": "run-1", "workspace_id": "workspace-1",
            "repository_id": "repo-1", "source_base_sha": "a" * 40,
            "instruction": "Repair a neutral fixture.", "deadline_at": 200,
            "max_events": 64,
        }
        # Independent v1 canonical bytes, not Task.to_dict as an oracle.
        expected = hashlib.sha256(json.dumps(
            legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode()).hexdigest()
        self.assertIn("max_output_tokens", type(self.task).__dataclass_fields__)
        self.assertEqual(self.task.digest, expected)
        self.assertEqual(self.task.to_dict(), legacy)
        limited = replace(self.task, max_output_tokens=64)
        self.assertNotEqual(limited.digest, expected)
        self.assertEqual(limited.to_dict()["max_output_tokens"], 64)
        self.assertEqual(Task(**legacy).digest, expected)

    def test_wrong_wire_types_and_empty_message_fail_closed(self):
        for raw in (None, True, "{}", bytearray(b"{}"), b""):
            with self.subTest(kind=type(raw).__name__):
                self.box = WorkerMailbox(self.task, clock=lambda: self.now)
                self.session = self.box.session
                self.refused(raw)

    def test_total_event_limit_blocks_result_for_otherwise_valid_message(self):
        limited = replace(self.task, max_events=2)
        self.box = WorkerMailbox(limited, clock=lambda: self.now)
        self.task, self.session = limited, self.box.session
        result = self.admit(self.message())
        self.assertIs(type(result), WorkerFailure)
        self.assertEqual(result.code, "EVENT_LIMIT")
        self.assertFalse(hasattr(result, "candidate"))
        self.assertEqual([event.kind for event in self.box.drain(self.session)], ["STARTED"])
        self.assertIs(self.admit(self.message()), result)
        self.assertEqual(self.box.drain(self.session), ())

    def test_completion_publishes_both_events_admitted_before_deadline(self):
        self.task = replace(self.task, max_events=3)
        clock = iter((100, 100, 199, 200))
        self.box = WorkerMailbox(self.task, clock=lambda: next(clock))
        self.session = self.box.session

        result = self.admit(self.message())

        self.assertIs(type(result), WorkerResult)
        self.assertIs(self.box.result(self.session), result)
        events = self.box.drain(self.session)
        self.assertEqual([event.kind for event in events], ["STARTED", "CANDIDATE", "COMPLETED"])
        self.assertEqual([event.sequence for event in events], [1, 2, 3])
        self.assertEqual([event.evidence_digest for event in events[1:]], [result.candidate.digest] * 2)

    def test_completion_deadline_is_rechecked_after_parsing(self):
        clock = iter((100, 100, 200))
        self.box = WorkerMailbox(self.task, clock=lambda: next(clock))
        self.session = self.box.session

        result = self.admit(self.message())

        self.assertIs(type(result), WorkerFailure)
        self.assertEqual(result.code, "TIMEOUT")
        self.assertEqual([event.kind for event in self.box.drain(self.session)], ["STARTED"])

    def test_explicit_small_operator_budget_limits_bytes_and_usage(self):
        self.assertIn('max_output_tokens', Task.__dataclass_fields__,
                      'Canonical Task has no bounded output budget')
        self.task = replace(self.task, max_output_tokens=32)
        self.box = WorkerMailbox(self.task, clock=lambda: self.now)
        self.session = self.box.session
        self.refused(self.message(files=[{"path": "x.py", "text": "x" * 513}]))
