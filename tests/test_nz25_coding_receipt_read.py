"""The existing read API projects only task-bound, audited repair receipts."""
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

import test_hybrid_repair as support
from q09_support import Fixture
from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.audit import append_domain_event, domain_chain
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
    to_canonical_data,
)
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mobile_gateway.wire import Identity


class CodingReceiptReadTests(unittest.TestCase):
    def setUp(self):
        case = support.RepairTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case
        self.task = case.task
        self.path = case.root / "core.json"
        self.identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.payload = {"task_id": self.task.task_id}

    @contextmanager
    def service(self):
        fixture = Fixture(self.path)
        capsules = CorePatchCapsules(
            fixture.journal, self.identity, source_probe=lambda: self.case.source,
        )
        service = CoreCodingTasks(fixture.journal, capsules)
        try:
            yield fixture, service
        finally:
            service.close()
            fixture.close()

    def create_task(self, fixture, service):
        service.request(fixture.p(Capability.MANAGE), "create_task", {"task": asdict(self.task)})

    def candidate_receipt(self):
        result, _, _ = self.case.run_loop([self.case.candidate("a+b")], ["PASS"])
        self.assertEqual(result.status, "PATCH_READY")
        return result

    def keep_fixture_record(self, fixture, result, *, audit):
        kind = "aioa.coding-loop.v1"
        key = canonical_sha256([kind, self.task.digest])

        def insert(tx):
            row = StoredRecord(RecordKind.OPERATION, key, tx.context.scope, 1, {
                "schema": kind, "task_digest": self.task.digest, "result": result,
            })
            tx.insert(row)
            if audit:
                binding = OperationBinding.bind(
                    "coding-loop-" + key, "CODING_LOOP_RECEIPT", {"record_digest": row.payload_digest},
                )
                append_domain_event(
                    tx, binding, event_id="coding-loop-audit-" + key,
                    proof_id="coding-loop-outbox-" + key, resource_id=key,
                    before=None, after=result["status"], content_digest=row.payload_digest,
                    at=fixture.ledger.clock(),
                )

        fixture.runner.run(TransactionContext(fixture.p(), Capability.COMMIT), insert)

    def test_exact_preexisting_wire_is_read_only_after_stop_and_reopen(self):
        receipt = self.candidate_receipt()
        with self.service() as (fixture, service):
            self.create_task(fixture, service)
            service._record_loop(fixture.p(), self.task, receipt)
            service.request(fixture.p(Capability.MANAGE), "stop", self.payload)
            stale_read = fixture.p(Capability.READ)

        before = self.path.read_bytes()
        with self.service() as (fixture, service):
            with self.assertRaises(AdmissionError):
                service.request(stale_read, "get_receipts", self.payload)
            with self.assertRaises(AdmissionError):
                service.request(fixture.p(Capability.MANAGE), "get_receipts", self.payload)
            read = fixture.p(Capability.READ)
            view = service.request(read, "get_receipts", self.payload)
            self.assertEqual(service.request(read, "get_receipts", self.payload), view)
            self.assertEqual(view["state"], "CANCELLED")
            self.assertFalse(view["effect_verified"])
            self.assertEqual(view["run_result"], json.loads(canonical_json_bytes(asdict(receipt))))
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_run_row_requires_its_canonical_audit_event(self):
        receipt = self.candidate_receipt()
        with self.service() as (fixture, service):
            self.create_task(fixture, service)
            self.keep_fixture_record(fixture, asdict(receipt), audit=False)
            before = self.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "CODING_LOOP_RECEIPT_INTEGRITY"):
                service.request(fixture.p(Capability.READ), "get_receipts", self.payload)
            self.assertEqual(self.path.read_bytes(), before)

    def test_audit_capacity_does_not_hide_an_existing_receipt(self):
        receipt = self.candidate_receipt()
        with self.service() as (fixture, service):
            self.create_task(fixture, service)
            service._record_loop(fixture.p(), self.task, receipt)

            def fill(tx):
                current = domain_chain(tx)
                previous = current[-1]
                for index in range(len(current), 1024):
                    event = replace(
                        previous, audit_event_id=f"fixture-audit-{index}",
                        event_type="FIXTURE_EVENT", resource_id=f"fixture-item-{index}",
                        sequence_number=index, previous_event_hash=previous.event_hash,
                    )
                    tx.insert(StoredRecord(
                        RecordKind.AUDIT, event.audit_event_id, tx.context.scope, 1,
                        to_canonical_data(event),
                    ))
                    previous = event

            fixture.runner.run(TransactionContext(fixture.p(), Capability.COMMIT), fill)
            view = service.request(fixture.p(Capability.READ), "get_receipts", self.payload)
            self.assertEqual(view["run_result"]["receipt_sha256"], receipt.receipt_sha256)

    def test_nested_patchset_identity_is_checked_in_audited_older_rows(self):
        record = asdict(self.candidate_receipt())
        record["final_patchset"]["files"][0]["after"]["sha256"] = "9" * 64
        record["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in record.items() if key != "receipt_sha256"}
        )
        with self.service() as (fixture, service):
            self.create_task(fixture, service)
            self.keep_fixture_record(fixture, record, audit=True)
            with self.assertRaisesRegex(ValueError, "CODING_LOOP_RECEIPT_INTEGRITY"):
                service.request(fixture.p(Capability.READ), "get_receipts", self.payload)

    def test_same_task_id_with_a_different_revision_does_not_bind_the_patch(self):
        self.case.task = replace(self.task, instruction="Fix addition with different context.")
        receipt = self.candidate_receipt()
        self.assertNotEqual(receipt.final_patchset.task_digest, self.task.digest)
        with self.service() as (fixture, service):
            self.create_task(fixture, service)
            self.keep_fixture_record(fixture, asdict(receipt), audit=True)
            with self.assertRaisesRegex(ValueError, "CODING_LOOP_RECEIPT_INTEGRITY"):
                service.request(fixture.p(Capability.READ), "get_receipts", self.payload)

    def test_invalid_warrant_digest_type_has_a_bounded_receipt_error(self):
        record = asdict(self.candidate_receipt())
        record["attempts"][0]["steps"][0]["core_warrant_digest"] = 42
        record["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in record.items() if key != "receipt_sha256"}
        )
        with self.service() as (fixture, service):
            self.create_task(fixture, service)
            self.keep_fixture_record(fixture, record, audit=True)
            with self.assertRaisesRegex(ValueError, "CODING_LOOP_RECEIPT_INTEGRITY"):
                service.request(fixture.p(Capability.READ), "get_receipts", self.payload)
