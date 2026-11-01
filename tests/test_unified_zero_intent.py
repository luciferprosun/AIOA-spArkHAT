"""U1: real native transactions; zero money is not a synthetic positive spend."""
from dataclasses import replace
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest

from q09_support import Fixture
from runtime.core_admission import Capability, AdmissionError
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.warrant import approval_digest
from lab.archaioa.authority import Money


class LocalZeroIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(Path(self.tmp.name)/'records.json'); self.addCleanup(self.fx.close)
        self.fx.operation.update(operation_class='WORKSPACE_WRITE', payload={
            'schema': 'aioa.local-operation.v2', 'workspace': 'fixture:sensorbridge',
            'source_sha': '1'*40, 'capsule_digest': 'a'*64, 'device_id': 'local-host',
            'session_id': self.fx.p().actor_session_id, 'policy_epoch': 1,
            'operation_id': 'write-once', 'task_digest': 'b'*64})
        scope = replace(self.fx.warrant.authority_scope, operation_classes=('WORKSPACE_WRITE',),
                        monetary_ceiling=Money(Decimal(0), 'USD'))
        w = replace(self.fx.warrant, operation_class='WORKSPACE_WRITE', authority_scope=scope,
                    money_reservation_id='NONE', operation_hash='sha256:'+canonical_sha256(self.fx.operation))
        self.fx.warrant = replace(w, approval_digest=approval_digest(w))
        self.fx.request = replace(self.fx.request, money_nano=0,
                                 request_digest=canonical_sha256(self.fx.operation))
        self.fx.init()

    def start(self, **changes):
        self.assertTrue(callable(getattr(self.fx.journal, 'start_local_zero', None)),
                        'versioned zero-cost Core START is missing')
        args = dict(principal=self.fx.p(), warrant=self.fx.warrant,
                    operation=self.fx.operation, reservation=self.fx.request)
        return self.fx.journal.start_local_zero(**{**args, **changes})

    def test_zero_cost_start_consumes_one_warrant_holds_real_risk_and_no_money(self):
        started = self.start()
        self.assertTrue(started['local_step_now']); self.assertFalse(started['grants_replay'])
        self.assertEqual('Unknown', started['outcome']['contract_type'])
        state = self.fx.gov.inspect(self.fx.p(Capability.READ))
        self.assertEqual({'money_nano': 0, 'risk_units': 5}, state['exposure']['global'])
        self.assertFalse(self.start()['local_step_now'])
        self.assertEqual('Unknown', self.fx.inspect()['outcome']['contract_type'])

    def test_approval_is_stored_native_witness_not_operation_text(self):
        self.start()
        rows = self.fx.runner.run(TransactionContext(self.fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.scan(RecordKind.APPROVAL))
        self.assertEqual(1, len(rows))
        self.assertEqual(self.fx.p().actor_session_id, rows[0].payload['session_id'])

    def test_zero_profile_does_not_change_positive_v1_semantics(self):
        with self.assertRaisesRegex(ValueError, 'RESERVATION_BINDING'):
            self.fx.start()
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ), self.fx.warrant))

    def test_changed_session_and_revoked_authorization_cannot_start(self):
        self.assertTrue(callable(getattr(self.fx.ledger, 'revoke', None)), 'native revocation missing')
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)
        with self.assertRaisesRegex(ValueError, 'REVOKED'): self.start()
        self.assertEqual({}, self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'])

    def test_forged_core_principal_cannot_start(self):
        self.assertTrue(callable(getattr(self.fx.journal, 'start_local_zero', None)))
        with self.assertRaises(AdmissionError): self.start(principal=replace(self.fx.p(), _seal=b'forged'))

    def test_known_result_requires_existing_independent_reconciliation(self):
        self.start()
        resolved = self.fx.journal.reconcile(self.fx.p(), self.fx.warrant, 1)
        self.assertEqual('Applied', resolved['outcome']['contract_type'])
        self.assertFalse(self.start()['local_step_now'])
        self.assertEqual('COMMITTED', self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations']['paired-1']['state'])


if __name__ == '__main__': unittest.main()
