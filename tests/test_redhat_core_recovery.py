import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

from q09_support import Fixture
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.warrant import approval_digest
from runtime.red_hat.broker_protocol import BrokerRequest
from runtime.red_hat.core_adapter import CoreAdapterError, CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from test_redhat_broker_protocol import NOW


class RedHatCoreRecoveryTests(unittest.TestCase):
    def test_lost_ack_fresh_verifier_and_idempotent_original_core_settlement(self):
        from test_redhat_native_cas_broker import CasBrokerTests
        from test_redhat_core_adapter import align_warrant_window

        harness = CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        harness.workspace()
        self.addCleanup(harness.doCleanups)

        # Rebuild the real Q09 Core intent using the exact disposable repository
        # and ref bindings that the RH-02 broker will execute.
        base = harness.request
        fx = Fixture(harness.root / "original-core-intent.json")
        self.addCleanup(fx.close)
        align_warrant_window(fx)
        payload = dict(fx.operation["payload"])
        payload.update({
            "schema": "aioa.redhat.fixture-core-publication.v1",
            "repository_dev": base.repository_dev,
            "repository_inode": base.repository_inode,
            "ref_directory_dev": base.ref_directory_dev,
            "ref_directory_inode": base.ref_directory_inode,
            "ref": base.exact_ref,
            "old_oid": base.old_oid,
            "new_oid": base.new_oid,
        })
        fx.operation = {**fx.operation, "payload": payload}
        fx.warrant = replace(fx.warrant,
                             operation_hash="sha256:" + canonical_sha256(fx.operation))
        fx.warrant = replace(fx.warrant, approval_digest=approval_digest(fx.warrant))
        fx.request = replace(fx.request, request_digest=canonical_sha256(fx.operation))
        fx.journal = CoreIntentJournal(fx.ledger, fx.gov, verifier=fx.verify)
        fx.init()
        started = fx.start()
        self.assertTrue(started["outcome"]["contract_type"] == "Unknown")
        self.assertEqual("UNKNOWN", fx.gov.inspect(fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        held = fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX, fx.journal._key(fx.warrant)).payload["state"],
        )
        self.assertEqual("HELD", held)

        adapter = CoreIntentAdapter(fx.journal)
        binding = adapter.capture_start(fx.p(), fx.warrant)
        executor = harness.enrollment
        enrollment = ExecutorEnrollment(executor, 3, NOW - 60, NOW + 600)
        values = asdict(base)
        values.pop("commit_permit_digest")
        values.update({
            "operation_id": binding.operation_id,
            "attempt_id": binding.attempt_id,
            "owner_id": binding.owner_scope_digest,
            "executor_id": executor.executor,
            "executor_key_id": executor.key_id,
            "key_epoch": enrollment.key_epoch,
            "start_digest": binding.start_digest,
            "intent_digest": binding.intent_digest,
            "warrant_digest": binding.warrant_digest,
            "reservation_digest": binding.reservation_digest,
            "core_epoch": binding.core_epoch,
        })
        request = BrokerRequest.for_fixture(**values)
        root_fd = os.open(harness.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, root_fd)
        harness.request = request
        harness.spec["request"] = request.to_wire()
        harness.spec["core_epoch"] = binding.core_epoch
        (harness.root / "fixture.json").write_text(json.dumps(harness.spec))

        before_revision = fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OPERATION, fx.journal._key(fx.warrant)).revision,
        )
        harness.run_broker("witness_durable", crash=True)  # producer dies before ACK
        self.assertEqual(1, len(harness.dispatches()))
        self.assertEqual(request.new_oid + "\n",
                         (harness.root / "repo" / request.exact_ref).read_text())
        self.assertFalse(harness.run_broker()["ack"])
        self.assertEqual(1, len(harness.dispatches()))

        # Revocation blocks future authority but does not erase historical
        # evidence or prevent reconciliation of this already-started operation.
        fx.ledger.revoke(fx.p(Capability.OWNER_APPROVAL), fx.warrant)
        evidence_dir = harness.root / "evidence"
        witness_path = evidence_dir / request.witness_binding().witness_id
        hidden_witness = evidence_dir / "temporarily-held-witness"
        witness_path.rename(hidden_witness)
        try:
            with self.assertRaisesRegex(CoreAdapterError, "WITNESS_NOT_SETTLEMENT_GRADE"):
                adapter.recover_disposable_fixture(
                    fx.p(), fx.warrant, request, enrollment, root_fd=root_fd,
                    trusted_device_id="fixture-device", now=NOW + 60,
                    core_epoch=1, broker_epoch=7,
                )
            self.assertEqual("Unknown", fx.journal.inspect(
                fx.p(Capability.READ), fx.warrant)["outcome"]["contract_type"])
            self.assertEqual("HELD", fx.runner.run(
                TransactionContext(fx.p(Capability.READ), Capability.READ),
                lambda tx: tx.get(RecordKind.OUTBOX,
                                  fx.journal._key(fx.warrant)).payload["state"],
            ))
            self.assertEqual(1, len(harness.dispatches()))
        finally:
            hidden_witness.rename(witness_path)
        independent = harness.recover()
        self.assertNotEqual(independent["pid"], os.getpid())
        self.assertTrue(independent["producer_witness_sync_attested"])
        self.assertTrue(independent["settlement_supported"])

        # Recover after the short request permit has expired. The verifier
        # checks enrollment and permit validity at the signed publication time.
        with ThreadPoolExecutor(max_workers=2) as pool:
            recovered = list(pool.map(
                lambda _: adapter.recover_disposable_fixture(
                    fx.p(), fx.warrant, request, enrollment, root_fd=root_fd,
                    trusted_device_id="fixture-device", now=NOW + 60,
                    core_epoch=1, broker_epoch=7,
                ), range(2),
            ))
        settled = recovered[0]
        self.assertEqual(settled["outcome"], recovered[1]["outcome"])
        self.assertEqual("Applied", settled["outcome"]["contract_type"])
        self.assertNotEqual(settled["verification_process_pid"], os.getpid())
        delivery = fx.journal.delivery(fx.p(Capability.READ), fx.warrant)
        self.assertEqual("PENDING", delivery["delivery_state"])
        self.assertFalse(delivery["grants_replay"])
        self.assertEqual("COMMITTED", fx.gov.inspect(fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])

        # A later repeated recovery remains idempotent. There is no second CAS
        # dispatch even though the original short permit is now expired.
        repeated = adapter.recover_disposable_fixture(
            fx.p(), fx.warrant, request, enrollment, root_fd=root_fd,
            trusted_device_id="fixture-device", now=NOW + 60,
            core_epoch=1, broker_epoch=7,
        )
        self.assertEqual(settled["outcome"], repeated["outcome"])
        after_revision = fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OPERATION, fx.journal._key(fx.warrant)).revision,
        )
        self.assertEqual(before_revision + 1, after_revision)
        self.assertEqual(1, len(harness.dispatches()))  # broker_dispatch_count
        self.assertEqual(1, len(list((harness.root / "repo/refs/heads").iterdir())))
        self.assertEqual("COMMITTED", fx.gov.inspect(fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])


if __name__ == "__main__":
    unittest.main()
