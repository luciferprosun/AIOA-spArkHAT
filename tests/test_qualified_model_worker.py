"""One real loopback POST after a durable Core START. No provider credentials."""

import hashlib
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from lab.archaioa.authority import Money
from q09_support import Fixture
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.governor import (
    CoreDualGovernor,
    GovernorPolicy,
    Limits,
    ReservationRequest,
)
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.qualified_worker import (
    MAX_COST_NANO,
    MODEL,
    OP_CLASS,
    QualifiedModelWorker,
    worker_lease_digest,
)
from runtime.mission.warrant import approval_digest
from runtime.mission.worker import Task, WorkerError, WorkerPort
from runtime.providers.live_gate import (
    LiveCallGate,
    LocalGateResult,
    PermitUsageLedger,
    issue_test_permit,
)


class QualifiedWorkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.fx = Fixture(root / "core.json")
        self.addCleanup(self.fx.close)
        fx = self.fx
        limits = Limits(MAX_COST_NANO, 5)
        fx.gov = CoreDualGovernor(
            fx.core,
            fx.runner,
            GovernorPolicy(fx.ledger.scope, "worker", limits, limits, limits),
            clock=lambda: 100,
        )
        fx.journal = CoreIntentJournal(fx.ledger, fx.gov)
        self.calls = []
        self.response = "valid"
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.calls.append((self.path, data))
                if test.response == "lost":
                    self.close_connection = True
                    return
                s = test.worker.mailbox.session
                content = {
                    "schema": "aioa.worker-candidate.v1",
                    "session_id": s.session_id,
                    "task_digest": s.task_digest,
                    "task_id": s.task_id,
                    "run_id": s.run_id,
                    "files": [{"path": "example.txt", "text": "example\n"}],
                }
                if test.response == "wrong_session":
                    content["session_id"] = "unrelated"
                response = {
                    "id": "test-only",
                    "model": MODEL,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(content)},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 80,
                        "total_tokens": 180,
                    },
                }
                if test.response == "no_usage":
                    del response["usage"]
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        sha, source, suite = "1" * 40, "2" * 64, "3" * 64
        self.permit = issue_test_permit(
            permit_id="worker-test",
            phase="Worker",
            git_sha=sha,
            worktree_digest=source,
            local_gate=LocalGateResult("PASS", suite),
            issued_at=1,
            expires_at=4102444800,
            max_live_calls=1,
            provider_id="nebius",
            model_id=MODEL,
        ).permit
        self.gate = LiveCallGate(
            self.permit,
            clock=lambda: int(time.time()),
            source_reader=lambda: (sha, source, suite),
            usage_ledger=PermitUsageLedger(root / "usage.db"),
        )
        self.task = Task(
            fx.warrant.task_id,
            "run-1",
            "workspace-1",
            "repository-1",
            "a" * 40,
            "Propose example.txt containing example.",
            int(time.time()) + 55,
            max_output_tokens=256,
        )
        self.worker = QualifiedModelWorker.loopback(
            self.task,
            gate=self.gate,
            capsule_digest="c" * 64,
            lease_digest=worker_lease_digest(fx.p(), 1),
            price_checked_at=int(time.time()),
            port=server.server_port,
        )
        self.assertIsInstance(self.worker, WorkerPort)
        self.principal = fx.p()
        self.operation = self.worker.operation(self.principal, 1)
        scope = replace(
            fx.warrant.authority_scope,
            operation_classes=(OP_CLASS,),
            target_scope=self.operation["target_fingerprint"],
            monetary_ceiling=Money(Decimal(".01"), "USD"),
        )
        fx.warrant = replace(
            fx.warrant,
            operation_class=OP_CLASS,
            operation_hash="sha256:" + canonical_sha256(self.operation),
            target_fingerprint=scope.target_scope,
            expected_target_revision=sha,
            authority_scope=scope,
        )
        fx.warrant = replace(fx.warrant, approval_digest=approval_digest(fx.warrant))
        self.request = ReservationRequest(
            "paired-1",
            self.task.task_id,
            "nebius",
            MODEL,
            canonical_sha256(self.operation),
            MAX_COST_NANO,
            1,
        )
        self.worker.bind(fx.journal, self.principal, fx.warrant, self.request)

    def test_one_post_yields_inert_advice_and_separate_usage(self):
        self.fx.init()
        s = self.worker.start(self.task)
        self.assertEqual([], self.calls)
        self.assertEqual("Unknown", self.fx.inspect()["outcome"]["contract_type"])
        self.worker.poll(s)
        self.worker.poll(s)
        result = self.worker.result(s)
        self.assertEqual(
            ("NONE", False, "example.txt"),
            (result.authority, result.verified, result.candidate.files[0].path),
        )
        self.assertEqual(
            hashlib.sha256(b"test-only").hexdigest(),
            self.worker.provider_receipt["receipt"]["request_id_sha256"],
        )
        self.assertEqual(1, len(self.calls))
        self.assertEqual("/v1/chat/completions", self.calls[0][0])
        self.assertEqual(256, self.calls[0][1]["max_completion_tokens"])
        self.assertEqual(1, self.gate.usage_ledger.used(self.permit))

    def test_unknown_does_not_reissue_after_lost_response(self):
        self.fx.init()
        self.response = "lost"
        s = self.worker.start(self.task)
        self.worker.poll(s)
        self.assertEqual("UNKNOWN", self.worker.result(s).status)
        self.worker.poll(s)
        with self.assertRaises(WorkerError):
            self.worker.start(self.task)
        restarted = CoreIntentJournal(self.fx.ledger, self.fx.gov)
        self.assertFalse(
            restarted.start_paid_worker(
                self.principal, self.fx.warrant, self.operation, self.request
            )["worker_step_now"]
        )
        self.assertEqual(1, len(self.calls))
        self.assertEqual(
            "UNKNOWN",
            self.fx.gov.inspect(self.fx.p(Capability.READ))["reservations"]["paired-1"][
                "state"
            ],
        )

    def test_unsigned_warrant_cannot_send_even_if_poll_called_after_denial(self):
        self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        with self.assertRaisesRegex(ValueError, "HUMAN_APPROVAL_REQUIRED"):
            self.worker.start(self.task)
        with self.assertRaises(WorkerError):
            self.worker.poll(self.worker.mailbox.session)
        self.assertEqual([], self.calls)

    def test_revoke_after_start_prevents_post(self):
        self.fx.init()
        s = self.worker.start(self.task)
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)
        self.worker.poll(s)
        self.assertEqual("UNKNOWN", self.worker.result(s).status)
        self.assertEqual([], self.calls)

    def test_missing_provider_usage_stays_unknown(self):
        self.fx.init()
        self.response = "no_usage"
        s = self.worker.start(self.task)
        self.worker.poll(s)
        self.assertEqual("UNKNOWN", self.worker.result(s).status)
        self.assertIsNone(self.worker.provider_receipt)

    def test_wrong_envelope_fails_mailbox_and_holds_liability(self):
        self.fx.init()
        self.response = "wrong_session"
        s = self.worker.start(self.task)
        self.worker.poll(s)
        self.assertEqual("PROTOCOL", self.worker.result(s).code)
        self.assertEqual("Unknown", self.fx.inspect()["outcome"]["contract_type"])

    def test_receipt_is_durable_without_settling_from_model_text(self):
        self.fx.init()
        s = self.worker.start(self.task)
        self.worker.poll(s)
        key = "worker-" + canonical_sha256(self.fx.warrant.digest())
        journal = CoreIntentJournal(self.fx.ledger, self.fx.gov)
        stored = journal._run(
            self.fx.p(Capability.READ),
            Capability.READ,
            lambda tx: tx.get(RecordKind.RECEIPT, key),
        )
        self.assertEqual(1, stored.revision)
        self.assertEqual(
            self.worker.provider_receipt["receipt"]["candidate_digest"],
            stored.payload["receipt"]["candidate_digest"],
        )
        self.assertEqual("TEST", stored.payload["receipt"]["scope"])
        self.assertIsNone(stored.payload["signature"])
        self.assertEqual("Unknown", self.fx.inspect()["outcome"]["contract_type"])

    def test_wrong_budget_does_not_consume_warrant(self):
        self.fx.init()
        request = replace(self.request, money_nano=MAX_COST_NANO - 1)
        with self.assertRaisesRegex(ValueError, "WORKER_START_BINDING"):
            self.fx.journal.start_paid_worker(
                self.principal, self.fx.warrant, self.operation, request
            )
        self.assertIsNone(
            self.fx.ledger.inspect(self.fx.p(Capability.READ), self.fx.warrant)
        )
        self.assertEqual(0, len(self.calls))

    def test_close_after_start_is_unknown_without_dispatch(self):
        self.fx.init()
        s = self.worker.start(self.task)
        self.worker.close()
        self.worker.poll(s)
        self.assertEqual("UNKNOWN", self.worker.result(s).status)
        self.assertEqual(0, len(self.calls))

    def test_cannot_promote_test_permit_to_live(self):
        with self.assertRaisesRegex(WorkerError, "WORKER_PERMIT_BINDING"):
            QualifiedModelWorker.live(
                self.task,
                gate=self.gate,
                api_key="fixture",
                capsule_digest="c" * 64,
                lease_digest="d" * 64,
                price_checked_at=1,
            )
