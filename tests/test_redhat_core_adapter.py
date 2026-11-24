import tempfile
import unittest
import os
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

from q09_support import Fixture
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.warrant import approval_digest
from runtime.red_hat.broker_protocol import BrokerRequest, ProtocolError
from runtime.red_hat.core_adapter import CoreAdapterError, CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.witness import RegisteredExecutor
from test_redhat_broker_protocol import NOW, fixture_request
from runtime.mobile_gateway.wire import Identity


def request_for(binding, executor, **changes):
    base = fixture_request(executor_key_id=executor.key_id)
    values = asdict(base)
    values.pop("commit_permit_digest")
    values.update({
        "operation_id": binding.operation_id,
        "attempt_id": binding.attempt_id,
        "owner_id": binding.owner_scope_digest,
        "executor_id": executor.executor,
        "executor_key_id": executor.key_id,
        "key_epoch": 3,
        "start_digest": binding.start_digest,
        "intent_digest": binding.intent_digest,
        "warrant_digest": binding.warrant_digest,
        "reservation_digest": binding.reservation_digest,
        "core_epoch": binding.core_epoch,
    })
    values.update(changes)
    return BrokerRequest.for_fixture(**values)


def align_warrant_window(fx):
    issued = datetime.fromtimestamp(NOW - 120, timezone.utc)
    expires = datetime.fromtimestamp(NOW + 120, timezone.utc)
    scope = replace(fx.warrant.authority_scope,
                    not_before=issued, expires_at=expires + timedelta(hours=1))
    fx.warrant = replace(fx.warrant, authority_scope=scope,
                         issued_at=issued, expires_at=expires)


class RedHatCoreAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fx = Fixture(Path(self.temp.name) / "core-state.json")
        self.addCleanup(self.fx.close)
        align_warrant_window(self.fx)
        synthetic = fixture_request()
        payload = dict(self.fx.operation["payload"])
        payload.update({
            "schema": "aioa.redhat.fixture-core-publication.v1",
            "repository_dev": synthetic.repository_dev,
            "repository_inode": synthetic.repository_inode,
            "ref_directory_dev": synthetic.ref_directory_dev,
            "ref_directory_inode": synthetic.ref_directory_inode,
            "ref": synthetic.exact_ref,
            "old_oid": synthetic.old_oid,
            "new_oid": synthetic.new_oid,
        })
        self.fx.operation = {**self.fx.operation, "payload": payload}
        self.fx.warrant = replace(
            self.fx.warrant, operation_hash="sha256:" + canonical_sha256(self.fx.operation),
        )
        self.fx.warrant = replace(self.fx.warrant,
                                  approval_digest=approval_digest(self.fx.warrant))
        self.fx.request = replace(self.fx.request,
                                  request_digest=canonical_sha256(self.fx.operation))
        self.fx.journal = CoreIntentJournal(self.fx.ledger, self.fx.gov,
                                            verifier=self.fx.verify)
        self.fx.init()
        self.fx.start()
        self.adapter = CoreIntentAdapter(self.fx.journal)
        self.enrollment = ExecutorEnrollment(
            RegisteredExecutor("fixture-executor", os.getuid(),
                               Identity(ec.generate_private_key(ec.SECP256R1())).spki),
            3, NOW - 60, NOW + 600,
        )
        self.binding = self.adapter.capture_start(self.fx.p(), self.fx.warrant)
        self.request = request_for(self.binding, self.enrollment.executor)

    def check(self, request=None, *, enrollment=None, device="fixture-device", now=NOW,
              core_epoch=1, broker_epoch=7):
        return self.adapter.check_request(
            self.binding, request or self.request, enrollment or self.enrollment,
            trusted_device_id=device, now=now, core_epoch=core_epoch,
            broker_epoch=broker_epoch,
        )

    def test_core_start_binding_is_read_from_durable_unknown_and_held_records(self):
        self.assertEqual(self.fx.warrant.digest().removeprefix("sha256:"),
                         self.binding.warrant_digest)
        self.assertEqual(self.fx.warrant.operation_hash, self.binding.operation_digest)
        self.assertEqual("UNKNOWN", self.fx.gov.inspect(self.fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        self.assertFalse(self.binding.settled)
        self.assertTrue(self.check())

    def test_self_consistent_permit_digest_is_not_core_release_authority(self):
        self.assertTrue(self.check())
        with self.assertRaisesRegex(CoreAdapterError, "BLOCKED_SECURITY_REVIEW"):
            self.adapter.require_production_release(self.binding, self.request)
        # The fixture helper can make a perfectly self-consistent digest, but
        # it still cannot manufacture the missing cross-process Core gate.
        self.assertEqual(self.request.commit_permit_digest,
                         BrokerRequest.permit_digest({
                             key: value for key, value in asdict(self.request).items()
                             if key != "commit_permit_digest"
                         }))

    def test_wrong_start_warrant_reservation_owner_or_device_is_held(self):
        mutations = (
            {"start_digest": "a" * 64},
            {"warrant_digest": "b" * 64},
            {"reservation_digest": "c" * 64},
            {"owner_id": "d" * 64},
            {"device_id": "other-device"},
            {"repository_dev": 90},
            {"repository_inode": 91},
            {"ref_directory_dev": 92},
            {"ref_directory_inode": 93},
            {"exact_ref": "refs/heads/substituted"},
            {"new_oid": "e" * 40},
        )
        for changes in mutations:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(CoreAdapterError, "BROKER_CORE_BINDING"):
                    self.check(request_for(self.binding, self.enrollment.executor, **changes))
        with self.assertRaisesRegex(ProtocolError, "BROKER_REQUEST_SCHEMA"):
            request_for(self.binding, self.enrollment.executor, old_oid="1" * 40)

    def test_wrong_operation_epoch_and_broker_identity_are_held(self):
        with self.assertRaisesRegex(CoreAdapterError, "BROKER_CORE_BINDING"):
            self.check(request_for(self.binding, self.enrollment.executor,
                                   operation_id="other-operation"))
        with self.assertRaisesRegex(CoreAdapterError, "BROKER_CORE_BINDING"):
            self.check(core_epoch=2)
        retired = ExecutorEnrollment(self.enrollment.executor, 2, NOW - 60, NOW + 600)
        with self.assertRaisesRegex(CoreAdapterError, "BROKER_ENROLLMENT"):
            self.check(enrollment=retired)
        revoked = ExecutorEnrollment(self.enrollment.executor, 3, NOW - 60, NOW + 600,
                                     revoked=True)
        with self.assertRaisesRegex(CoreAdapterError, "BROKER_ENROLLMENT"):
            self.check(enrollment=revoked)

    def test_expired_permit_and_missing_trusted_device_fail_closed(self):
        with self.assertRaisesRegex(CoreAdapterError, "BROKER_ENROLLMENT"):
            self.check(now=NOW + 601)
        with self.assertRaisesRegex(CoreAdapterError, "BROKER_CORE_BINDING"):
            self.check(request_for(self.binding, self.enrollment.executor,
                                   issued_at=NOW - 200))
        with self.assertRaisesRegex(CoreAdapterError, "TRUSTED_DEVICE_BINDING_REQUIRED"):
            self.check(device=None)

    def test_expired_or_revoked_core_warrant_blocks_new_candidate(self):
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)
        with self.assertRaisesRegex(ValueError, "WARRANT_REVOKED"):
            self.adapter.capture_pre_dispatch_candidate(self.fx.p(), self.fx.warrant)

    def test_unrelated_operation_schema_cannot_be_read_as_git_cas(self):
        other = Fixture(Path(self.temp.name) / "unrelated-core-state.json")
        self.addCleanup(other.close)
        align_warrant_window(other)
        operation = {**other.operation,
                     "payload": {**other.operation["payload"], "schema": "aioa.unrelated.v1"}}
        other.operation = operation
        other.warrant = replace(other.warrant,
                                operation_hash="sha256:" + canonical_sha256(operation))
        other.warrant = replace(other.warrant,
                                 approval_digest=approval_digest(other.warrant))
        other.request = replace(other.request, request_digest=canonical_sha256(operation))
        other.journal = CoreIntentJournal(other.ledger, other.gov, verifier=other.verify)
        other.init()
        other.start()
        with self.assertRaisesRegex(CoreAdapterError, "CORE_CAS_INTENT_REQUIRED"):
            CoreIntentAdapter(other.journal).capture_start(other.p(), other.warrant)


if __name__ == "__main__":
    unittest.main()
