"""Q09 bounded native-port process fixtures; no live/local effect execution."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from q09_support import Fixture, DurableTransaction
from runtime.core_admission import Capability, AdmissionError
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.warrant import approval_digest


class CoreIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'intent.json'
        self.fx = Fixture(self.path); self.addCleanup(self.fx.close)
        self.fx.init()

    def child(self, mode, expected=0):
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('q09_support.py')),
                                 mode, str(self.path)], capture_output=True, text=True, timeout=20)
        self.assertEqual(expected, result.returncode, result.stderr)
        return result.stdout

    def test_start_atomically_consumes_and_reserves_both_with_exact_intent(self):
        result = self.fx.start()
        self.assertTrue(result['fixture_step_now'])
        self.assertFalse(result['grants_replay'])
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertEqual(result['liability_id'], result['outcome']['liability_id'])
        self.assertFalse(self.fx.ledger.inspect(self.fx.p(Capability.READ), self.fx.warrant)['grants_replay'])
        state = self.fx.gov.inspect(self.fx.p(Capability.READ))
        self.assertEqual({'money_nano':50, 'risk_units':5}, state['exposure']['global'])
        self.assertEqual('UNKNOWN', state['reservations']['paired-1']['state'])
        def read(tx):
            return tx.get(RecordKind.OPERATION, self.fx.journal._key(self.fx.warrant)).payload['operation']
        self.assertEqual(self.fx.operation, self.fx.runner.run(TransactionContext(self.fx.p(Capability.READ),Capability.READ), read))

    def test_duplicate_and_restart_never_grant_second_step(self):
        self.fx.start()
        self.assertFalse(self.fx.start()['fixture_step_now'])
        self.assertIn('UNKNOWN_NO_REPLAY', self.child('probe'))

    def test_budget_failure_rolls_back_warrant_intent_and_reservation(self):
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.fx.journal.start(self.fx.p(), self.fx.warrant, self.fx.operation, replace(self.fx.request,risk_units=11))
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ), self.fx.warrant))
        self.assertEqual({}, self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'])
        self.assertTrue(self.fx.start()['fixture_step_now'])

    def test_no_approval_and_untrusted_principal_deny(self):
        for principal in (None, {'actor':'github'}, self.fx.core.critic_candidate()):
            with self.assertRaises(AdmissionError):
                self.fx.journal.start(principal,self.fx.warrant,self.fx.operation,self.fx.request)
        other = replace(self.fx.warrant, nonce='other')
        other = replace(other, approval_digest=approval_digest(other))
        with self.assertRaisesRegex(ValueError, 'HUMAN_APPROVAL_REQUIRED'):
            self.fx.journal.start(self.fx.p(),other,self.fx.operation,self.fx.request)

    def test_changed_fingerprint_revision_payload_or_reservation_deny(self):
        for key, value in (('target_fingerprint','sha256:'+'f'*64), ('expected_target_revision','r2'),
                           ('payload',{'value':2}), ('operation_class','delete')):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'INTENT_BINDING'):
                self.fx.journal.start(self.fx.p(),self.fx.warrant,{**self.fx.operation,key:value},self.fx.request)
        with self.assertRaisesRegex(ValueError,'RESERVATION_BINDING'):
            self.fx.journal.start(self.fx.p(),self.fx.warrant,self.fx.operation,replace(self.fx.request,request_id='changed'))
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),self.fx.warrant))

    def test_unadmitted_model_cannot_consume_or_reserve(self):
        before = self.path.read_bytes()
        request = replace(self.fx.request, model_id='UNADMITTED-MODEL')
        with self.assertRaisesRegex(ValueError, 'MODEL_BINDING_DENIED'):
            self.fx.journal.start(self.fx.p(), self.fx.warrant, self.fx.operation, request)
        self.assertEqual(before, self.path.read_bytes())
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ), self.fx.warrant))

    def test_corrupt_prior_resolution_cannot_bypass_unknown_reservation(self):
        self.fx.start()
        def corrupt(tx):
            row = tx.get(RecordKind.OPERATION, self.fx.journal._key(self.fx.warrant))
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1,
                       {**row.payload, 'resolution': {}}), expected_revision=row.revision)
        self.fx.runner.run(TransactionContext(self.fx.p(), Capability.COMMIT), corrupt)
        with self.assertRaisesRegex(ValueError, 'INTENT_INTEGRITY'):
            self.fx.inspect()
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        operation = {**self.fx.operation, 'payload': {'fixture_only': True, 'value': 2}}
        warrant = replace(self.fx.warrant, nonce='next-nonce', warrant_id='next-warrant',
                          operation_hash='sha256:' + canonical_sha256(operation),
                          money_reservation_id='paired-2', risk_reservation_id='paired-2')
        warrant = replace(warrant, approval_digest=approval_digest(warrant))
        self.fx.ledger.approve(self.fx.p(Capability.OWNER_APPROVAL), warrant)
        request = replace(self.fx.request, request_id='paired-2',
                          request_digest=canonical_sha256(operation))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED_INTENT'):
            self.fx.journal.start(self.fx.p(), warrant, operation, request)
        self.assertEqual(before, self.path.read_bytes())
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ), warrant))
        reservations = self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations']
        self.assertEqual('UNKNOWN', reservations['paired-1']['state'])
        self.assertNotIn('paired-2', reservations)

    def test_process_crash_before_start_leaves_no_partial_mutation(self):
        before = self.path.read_bytes()
        self.child('crash-before-start',75)
        self.assertEqual(before,self.path.read_bytes())
        self.assertTrue(self.fx.start()['fixture_step_now'])

    def test_process_crash_after_start_keeps_unknown_and_no_replay(self):
        self.child('crash-after-start',75)
        self.assertIn('UNKNOWN_NO_REPLAY',self.child('probe'))
        with self.assertRaisesRegex(ValueError,'OUTCOME_UNKNOWN'):
            self.fx.journal.delivery(self.fx.p(Capability.READ),self.fx.warrant)

    def test_lost_storage_ack_never_repeats_transaction_or_step(self):
        original = DurableTransaction.commit
        def lost(tx):
            original(tx); raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction,'commit',lost), self.assertRaises(CommitOutcomeUnknown):
            self.fx.start()
        self.assertIn('UNKNOWN_NO_REPLAY',self.child('probe'))

    def test_lost_effect_ack_requires_independent_readback_in_new_process(self):
        self.fx.start()  # Synthetic host send/ACK loss: no target effect is executed.
        self.assertIn('UNKNOWN_NO_REPLAY',self.child('probe'))
        self.assertIn('READBACK_ONLY',self.child('reconcile'))
        self.assertEqual('Applied',self.fx.inspect()['outcome']['contract_type'])
        self.assertTrue(self.fx.inspect()['liability_id'])

    def test_takeover_fences_old_start_resolution_and_delivery_commit(self):
        self.fx.start()
        epoch = self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        with self.assertRaisesRegex(ValueError,'STALE_EPOCH'):self.fx.start()
        with self.assertRaisesRegex(ValueError,'STALE_EPOCH'):
            self.fx.journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.fx.journal.reconcile(self.fx.p(),self.fx.warrant,epoch)
        delivery = self.fx.journal.delivery(self.fx.p(Capability.READ),self.fx.warrant)
        with self.assertRaisesRegex(ValueError,'STALE_EPOCH'):
            self.fx.journal.acknowledge_delivery(self.fx.p(),self.fx.warrant,1,delivery['delivery_revision'])

    def test_takeover_during_verification_cannot_commit_stale_result(self):
        self.fx.start()
        def verify(operation):
            self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
            return self.fx.verify(operation)
        journal = CoreIntentJournal(self.fx.ledger,self.fx.gov,verifier=verify)
        with self.assertRaisesRegex(ValueError,'STALE_EPOCH'):
            journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.assertEqual('Unknown',self.fx.inspect()['outcome']['contract_type'])

    def test_missing_or_timeout_verifier_keeps_unknown_and_budget(self):
        self.fx.start()
        for verifier in (None,lambda operation:None):
            journal = CoreIntentJournal(self.fx.ledger,self.fx.gov,verifier=verifier)
            with self.assertRaises(ValueError):journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.assertEqual('Unknown',self.fx.inspect()['outcome']['contract_type'])
        self.assertEqual(50,self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['money_nano'])

    def test_publication_retries_only_projection_and_revision_cas(self):
        self.fx.start(); self.fx.journal.reconcile(self.fx.p(),self.fx.warrant,1)
        first = self.fx.journal.delivery(self.fx.p(Capability.READ),self.fx.warrant)
        self.assertEqual(first,self.fx.journal.delivery(self.fx.p(Capability.READ),self.fx.warrant))
        self.assertEqual('PENDING',first['delivery_state'])
        self.assertNotIn('operation',first)
        self.assertFalse(self.fx.start()['fixture_step_now'])
        self.fx.journal.acknowledge_delivery(self.fx.p(),self.fx.warrant,1,first['delivery_revision'])
        with self.assertRaisesRegex(ValueError,'STALE_DELIVERY_REVISION'):
            self.fx.journal.acknowledge_delivery(self.fx.p(),self.fx.warrant,1,first['delivery_revision'])
        self.assertEqual('DELIVERED',self.fx.journal.delivery(self.fx.p(Capability.READ),self.fx.warrant)['delivery_state'])

    def test_outbox_corruption_fails_closed(self):
        self.fx.start()
        def corrupt(tx):
            row = tx.get(RecordKind.OUTBOX,self.fx.journal._key(self.fx.warrant))
            tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,
                       {'state':'PENDING','intent_digest':row.payload['intent_digest']}),expected_revision=row.revision)
        self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),corrupt)
        with self.assertRaisesRegex(ValueError,'INTENT_OUTBOX_INTEGRITY'):self.fx.inspect()

    def test_unresolved_send_blocks_new_nonce_and_revised_intent(self):
        self.fx.start()
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        operation = {**self.fx.operation, 'payload': {'fixture_only':True,'value':2}}
        warrant = replace(self.fx.warrant, nonce='next-nonce', warrant_id='next-warrant',
                          operation_hash='sha256:'+canonical_sha256(operation),
                          money_reservation_id='paired-2',risk_reservation_id='paired-2')
        warrant = replace(warrant, approval_digest=approval_digest(warrant))
        self.fx.ledger.approve(self.fx.p(Capability.OWNER_APPROVAL),warrant)
        request = replace(self.fx.request,request_id='paired-2',request_digest=canonical_sha256(operation))
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_INTENT'):
            self.fx.journal.start(self.fx.p(),warrant,operation,request)
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),warrant))
        self.fx.journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.assertTrue(self.fx.journal.start(self.fx.p(),warrant,operation,request)['fixture_step_now'])

    def test_kill_denies_start_but_allows_reconciliation(self):
        self.fx.gov.set_kill(self.fx.p(Capability.MANAGE),True)
        with self.assertRaisesRegex(ValueError,'KILL_SWITCH'):self.fx.start()
        self.fx.gov.set_kill(self.fx.p(Capability.MANAGE),False)
        self.fx.start()
        self.fx.gov.set_kill(self.fx.p(Capability.MANAGE),True)
        self.fx.journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.assertEqual('Applied',self.fx.inspect()['outcome']['contract_type'])

    def test_not_applied_certificate_resolves_without_refund_or_replay(self):
        from lab.archaioa.outcome import NotApplied
        from lab.archaioa.evidence import EvidenceRef
        from runtime.mission.liability import Reconciliation
        self.fx.start()
        def verify(operation):
            return Reconciliation(self.fx.warrant.operation_hash,NotApplied(),
                EvidenceRef('no-effect','no-effect-certificate','sha256:'+'a'*64,'v1'),
                EvidenceRef('readback','independent-readback','sha256:'+'b'*64,'v1'))
        journal = CoreIntentJournal(self.fx.ledger,self.fx.gov,verifier=verify)
        journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.assertEqual('NotApplied',self.fx.inspect()['outcome']['contract_type'])
        self.assertFalse(self.fx.start()['fixture_step_now'])
        self.assertEqual(50,self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['money_nano'])

    def test_competing_starts_have_one_fixture_step(self):
        import concurrent.futures
        other = Fixture(self.path); self.addCleanup(other.close)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda fixture:fixture.start()['fixture_step_now'],(self.fx,other)))
        self.assertEqual([False,True],sorted(results))

    def test_intent_insert_failure_rolls_back_consumption_and_budgets(self):
        from runtime.mission.warrant import WarrantError
        before = self.path.read_bytes()
        with patch.object(CoreIntentJournal,'_save',side_effect=WarrantError('FIXTURE_STORAGE_FAILURE')):
            with self.assertRaisesRegex(ValueError,'FIXTURE_STORAGE_FAILURE'):self.fx.start()
        self.assertEqual(before,self.path.read_bytes())
        self.assertTrue(self.fx.start()['fixture_step_now'])
