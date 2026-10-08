"""Shared native audit encoding; legacy receipts remain readable, not rewritten."""
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event, domain_chain
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.ports import TransactionContext


class GovernorAuditCompatibilityTests(unittest.TestCase):
    def test_mixed_service_and_governor_events_cannot_commit_a_backwards_audit_timestamp(self):
        from nv09_support import GuardFixture, LocalTarget
        from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,Limits
        with tempfile.TemporaryDirectory() as temporary:
            target=LocalTarget(Path(temporary)/'target');fixture=GuardFixture(Path(temporary)/'guard',target.client)
            try:
                fixture.approve()
                policy=GovernorPolicy(fixture.scope,'single-core',Limits(100,10),Limits(100,10),Limits(100,10))
                governor=CoreDualGovernor(fixture.core,fixture.runner,policy,clock=fixture.clock)
                governor.start_epoch(fixture.core.local_operator(Capability.MANAGE))
                principal=fixture.core.local_operator(Capability.READ)
                try:events=fixture.runner.run(TransactionContext(principal,Capability.READ),domain_chain)
                except MemoryPatchError:self.fail('Committed shared audit chain was poisoned by truncated governor time')
                self.assertEqual(2,len(events));self.assertGreaterEqual(events[1].created_at,events[0].created_at)
                fixture.guard.revoke(fixture.core.local_operator(Capability.OWNER_APPROVAL),fixture.operation_id)
                self.assertEqual(3,len(fixture.runner.run(TransactionContext(principal,Capability.READ),domain_chain)))
            finally:fixture.close();target.close()

    def test_existing_legacy_guard_can_continue_without_rewriting_history(self):
        from nv09_support import GuardFixture,LocalTarget
        with tempfile.TemporaryDirectory() as temporary:
            target=LocalTarget(Path(temporary)/'target');fixture=GuardFixture(Path(temporary)/'guard',target.client)
            try:
                approval=fixture.approve();key=fixture.guard._key(fixture.operation_id,'approval')
                tx=fixture.factory.begin(TransactionContext(fixture.core.local_operator(Capability.READ),Capability.READ),attempt=1)
                raw=StoredRecord(RecordKind.AUDIT,'nv09-'+key,fixture.scope,1,
                    {'state':'SERVICE_GUARD','phase':'approval','operation_id':fixture.operation_id,
                     'outcome_digest':canonical_sha256(approval),'recorded_at':fixture.clock_value})
                tx.snapshot[(fixture.scope.binding(),RecordKind.AUDIT,raw.record_id)]=raw
                tx.snapshot.pop((fixture.scope.binding(),RecordKind.OUTBOX,'nv09-outbox-'+key))
                tx.commit();tx.close()
                before=fixture.factory.path.read_bytes()
                fixture.guard.receipt_graph(fixture.core.local_operator(Capability.READ),fixture.operation_id)
                self.assertEqual(before,fixture.factory.path.read_bytes())
                self.assertEqual('VERIFIED',fixture.tick()['status'])
                self.assertEqual('COMPLETE',fixture.guard.receipt_graph(fixture.core.local_operator(Capability.READ),fixture.operation_id)['projection_status'])
                original=fixture.factory.state[(fixture.scope.binding(),RecordKind.AUDIT,raw.record_id)]
                self.assertEqual(raw.payload_digest,original.payload_digest)
            finally:fixture.close();target.close()
    def test_service_approval_does_not_poison_shared_native_audit_chain(self):
        from nv09_support import GuardFixture, LocalTarget
        with tempfile.TemporaryDirectory() as temporary:
            target = LocalTarget(Path(temporary)/'target')
            fixture = GuardFixture(Path(temporary)/'guard', target.client)
            try:
                fixture.approve()
                principal = fixture.core.local_operator(Capability.READ)
                try:
                    events = fixture.runner.run(
                        TransactionContext(principal, Capability.READ), domain_chain)
                except MemoryPatchError:
                    self.fail('ServiceGuard approval breaks the existing native domain audit chain')
                self.assertEqual(1, len(events))
                self.assertEqual('nv09-approval', events[0].event_type)
                self.assertEqual('PARTIAL', fixture.guard.receipt_graph(principal, fixture.operation_id)['projection_status'])
            finally:
                fixture.close()
                target.close()

    def test_service_complete_receipt_retains_valid_and_recorded_time(self):
        from nv09_support import GuardFixture, LocalTarget
        with tempfile.TemporaryDirectory() as temporary:
            target = LocalTarget(Path(temporary)/'target')
            fixture = GuardFixture(Path(temporary)/'guard', target.client)
            try:
                fixture.approve()
                self.assertEqual('VERIFIED', fixture.tick()['status'])
                principal = fixture.core.local_operator(Capability.READ)
                events = fixture.runner.run(TransactionContext(principal, Capability.READ), domain_chain)
                self.assertEqual(5, len(events))
                graph = fixture.guard.receipt_graph(principal, fixture.operation_id)
                node = next(n for n in graph['nodes'] if n['id'] == 'receipt')
                self.assertIs(type(node['valid_time']), int)
                self.assertIs(type(node['transaction_time']), int)
                self.assertEqual('COMPLETE', graph['projection_status'])
            finally:
                fixture.close()
                target.close()
