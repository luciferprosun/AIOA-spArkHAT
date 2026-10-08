"""Receipt projection catches broken provenance without granting authority."""
import json
from pathlib import Path
import tempfile
import unittest

from runtime.core_admission import AdmissionError, Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.service_guard.contracts import GuardError, ServicePolicy


class ReceiptGraphTests(unittest.TestCase):
    def setUp(self):
        self.policy = ServicePolicy(OwnerScope('graph-tenant', 'graph-owner', 'graph-space', 'graph-slot'), 'graph-target')
        self.operation = 'graph-operation'
        scope = list(self.policy.scope.binding())
        approval = {'operation_id': self.operation, 'scope': scope, 'target_id': self.policy.target_id,
            'approved_revision': 1, 'before_effect_count': 0, 'effect_class': 'SET_MAINTENANCE',
            'max_effects': 1, 'policy_digest': self.policy.digest, 'policy_decision': 'ALLOW',
            'consent_id': '00000000000000000000000000000001', 'approved_at': 100, 'expires_at': 400}
        proposal = {'target_id': self.policy.target_id, 'observed_mode': 'NORMAL',
            'expected_target_revision': 1, 'proposed_effect': 'SET_MAINTENANCE',
            'reason_summary': 'private fixture context must not be exported', 'needs_attention': True}
        command = {'operation_id': self.operation, 'scope': scope, 'target_id': self.policy.target_id,
            'expected_revision': 1, 'before_effect_count': 0, 'effect_class': 'SET_MAINTENANCE',
            'approval_digest': canonical_sha256(approval), 'policy_digest': self.policy.digest,
            'proposal_digest': canonical_sha256(proposal), 'expires_at': 400,
            'idempotency_key': canonical_sha256(('nv09-service', self.policy.scope, self.operation, 'effect'))}
        intent = {**command, 'request_digest': canonical_sha256(command)}
        receipt = {**intent, 'receipt_id': 'target-'+command['idempotency_key'], 'new_revision': 2,
            'effect_count': 1, 'mode': 'MAINTENANCE', 'dispatched_at': 110,
            'transport_result': 'TARGET_DURABLY_APPLIED', 'reconciliation_state': 'COMMITTED_BY_TARGET_RECEIPT'}
        measurement = {'target_id': self.policy.target_id, 'scope': scope, 'mode': 'MAINTENANCE', 'revision': 2, 'effect_count': 1}
        verified = {'operation_id': self.operation, 'request_digest': intent['request_digest'],
            'receipt_digest': canonical_sha256(receipt), 'measurement': measurement,
            'measurement_digest': canonical_sha256(measurement), 'verified_effect': True}
        self.outcomes = {'approval': approval, 'proposal': proposal, 'intent': intent, 'receipt': receipt, 'verified': verified}
        self.records, self.audits = {}, {}
        for index, (phase, outcome) in enumerate(self.outcomes.items()):
            self._store(phase, outcome, 200+index)

    def _store(self, phase, outcome, recorded_at):
        key = canonical_sha256(('nv09-service', self.policy.scope, self.operation, phase))
        digest = canonical_sha256(outcome)
        self.records[phase] = StoredRecord(RecordKind.OPERATION, key, self.policy.scope, 1,
            {'operation_kind': 'nv09-'+phase, 'payload_digest': digest, 'outcome': outcome})
        audit = {'state': 'SERVICE_GUARD', 'phase': phase, 'operation_id': self.operation, 'outcome_digest': digest}
        if recorded_at is not None:
            audit['recorded_at'] = recorded_at
        self.audits[phase] = StoredRecord(RecordKind.AUDIT, 'nv09-'+key, self.policy.scope, 1, audit)

    def project(self):
        try:
            from runtime.service_guard.receipt_graph import project_receipt_graph
        except ModuleNotFoundError as error:
            if error.name != 'runtime.service_guard.receipt_graph':
                raise
            self.fail('Missing native read-only receipt graph projection')
        return project_receipt_graph(self.records, self.audits, policy=self.policy, operation_id=self.operation)

    def test_graph_links_native_decision_receipt_and_measurement_digests(self):
        graph = self.project()
        self.assertEqual('COMPLETE', graph['projection_status'])
        self.assertEqual('VERIFIED_RECORD_PRESENT', graph['outcome_status'])
        self.assertEqual({'approval', 'proposal', 'intent', 'receipt', 'measurement', 'verified'}, {n['id'] for n in graph['nodes']})
        self.assertEqual({('approval', 'intent', 'APPROVAL_BINDING'), ('proposal', 'intent', 'PROPOSAL_BINDING'),
            ('intent', 'receipt', 'REQUEST_BINDING'), ('intent', 'verified', 'REQUEST_BINDING'),
            ('receipt', 'verified', 'RECEIPT_BINDING'), ('receipt', 'measurement', 'READBACK_AFTER_RECEIPT'),
            ('measurement', 'verified', 'MEASUREMENT_BINDING')},
            {(e['source'], e['target'], e['relation']) for e in graph['edges']})

    def test_late_receipt_keeps_event_time_separate_from_journal_time(self):
        node = next(n for n in self.project()['nodes'] if n['id'] == 'receipt')
        self.assertEqual(110, node['valid_time'])
        self.assertEqual(203, node['transaction_time'])
        self.assertEqual('dispatched_at', node['valid_time_source'])

    def test_clock_skew_is_not_used_to_invent_causal_order(self):
        self._store('receipt', self.outcomes['receipt'], 90)
        node = next(n for n in self.project()['nodes'] if n['id'] == 'receipt')
        self.assertEqual((110, 90), (node['valid_time'], node['transaction_time']))

    def test_legacy_missing_journal_time_remains_unknown(self):
        self._store('receipt', self.outcomes['receipt'], None)
        node = next(n for n in self.project()['nodes'] if n['id'] == 'receipt')
        self.assertIsNone(node['transaction_time'])
        self.assertEqual('UNKNOWN_LEGACY', node['transaction_time_status'])

    def test_ambiguous_intent_stays_unknown_and_reconciliation_only(self):
        for phase in ['receipt', 'verified']:
            self.records.pop(phase); self.audits.pop(phase)
        graph = self.project()
        self.assertEqual('PARTIAL', graph['projection_status'])
        self.assertEqual('UNKNOWN', graph['outcome_status'])
        self.assertEqual('RECONCILE_READ_ONLY', graph['next_action'])
        self.assertEqual('NONE', graph['authority'])

    def test_tampered_receipt_reference_fails_even_with_rehashed_storage(self):
        bad = {**self.outcomes['verified'], 'receipt_digest': '0'*64}
        self._store('verified', bad, 204)
        with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
            self.project()

    def test_tampered_measurement_reference_fails(self):
        self._store('verified', {**self.outcomes['verified'], 'measurement_digest': '0'*64}, 204)
        with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
            self.project()

    def assert_rehashed_measurement_rejected(self, changes):
        measurement = {**self.outcomes['verified']['measurement'], **changes}
        verified = {**self.outcomes['verified'], 'measurement': measurement,
                    'measurement_digest': canonical_sha256(measurement)}
        self._store('verified', verified, 204)
        with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
            self.project()

    def test_rehashed_measurement_foreign_target_is_rejected(self):
        self.assert_rehashed_measurement_rejected({'target_id': 'other-target'})

    def test_rehashed_measurement_foreign_scope_is_rejected(self):
        other = OwnerScope('other-tenant', 'other-owner', 'other-space', 'other-slot')
        self.assert_rehashed_measurement_rejected({'scope': list(other.binding())})

    def test_rehashed_measurement_unknown_field_is_rejected(self):
        self.assert_rehashed_measurement_rejected({'extra_state': 'UNTRUSTED'})

    def test_rehashed_measurement_boolean_revision_is_rejected(self):
        self.assert_rehashed_measurement_rejected({'revision': True})

    def test_rehashed_measurement_revision_must_match_receipt(self):
        self.assert_rehashed_measurement_rejected({'revision': 3})

    def test_rehashed_measurement_effect_count_must_match_receipt(self):
        self.assert_rehashed_measurement_rejected({'effect_count': 0})

    def test_rehashed_measurement_mode_must_match_receipt(self):
        self.assert_rehashed_measurement_rejected({'mode': 'NORMAL'})

    def test_rehashed_valid_pre_effect_observation_is_not_receipt_readback(self):
        self.assert_rehashed_measurement_rejected({'mode': 'NORMAL', 'revision': 1, 'effect_count': 0})

    def test_dangling_approval_dependency_fails_closed(self):
        self.records.pop('approval'); self.audits.pop('approval')
        with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
            self.project()

    def test_missing_audit_does_not_gain_an_invented_timestamp(self):
        self.audits.pop('receipt')
        with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
            self.project()

    def test_foreign_scope_record_cannot_join_the_graph(self):
        row = self.records['receipt']
        other = OwnerScope('other-tenant', 'other-owner', 'other-space', 'other-slot')
        self.records['receipt'] = StoredRecord(row.kind, row.record_id, other, row.revision, row.payload)
        with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
            self.project()

    def test_extra_phase_and_boolean_timestamp_fail_closed(self):
        for phase, timestamp in [('model_approval', 200), ('receipt', True)]:
            with self.subTest(phase=phase):
                self._store(phase, self.outcomes['receipt'], timestamp)
                with self.assertRaisesRegex(GuardError, 'RECEIPT_GRAPH_INTEGRITY'):
                    self.project()
                if phase == 'model_approval':
                    self.records.pop(phase); self.audits.pop(phase)

    def test_projection_is_bounded_stable_and_excludes_private_bodies(self):
        first = self.project()
        self.records = dict(reversed(list(self.records.items())))
        self.audits = dict(reversed(list(self.audits.items())))
        self.assertEqual(first, self.project())
        self.assertLessEqual(len(json.dumps(first).encode()), 8192)
        self.assertEqual('NONE', first['authority'])
        self.assertEqual('PROVENANCE_ONLY', first['verification'])
        raw = json.dumps(first)
        for private in ['graph-owner', self.operation, self.outcomes['approval']['consent_id'], 'private fixture context']:
            self.assertNotIn(private, raw)


class NativeReceiptGraphTests(unittest.TestCase):
    def test_native_read_projection_preserves_state_and_restart_replay(self):
        from nv09_support import GuardFixture, LocalTarget
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = LocalTarget(root/'target')
            first = GuardFixture(root/'guard', target.client)
            try:
                self.assertTrue(callable(getattr(first.guard, 'receipt_graph', None)), 'Missing native READ graph surface')
                first.approve()
                self.assertEqual('VERIFIED', first.tick()['status'])
                stored_before = (root/'guard/native-fixture.json').read_bytes()
                graph = first.guard.receipt_graph(first.core.local_operator(Capability.READ), first.operation_id)
                self.assertEqual(stored_before, (root/'guard/native-fixture.json').read_bytes())
                self.assertEqual('COMPLETE', graph['projection_status'])
                self.assertEqual(1, target.client.read()['effect_count'])
                with self.assertRaises(AdmissionError):
                    first.guard.receipt_graph(first.core.local_operator(Capability.COMMIT), first.operation_id)
                first.close()
                restarted = GuardFixture(root/'guard', target.client)
                try:
                    after = restarted.guard.receipt_graph(restarted.core.local_operator(Capability.READ), restarted.operation_id)
                    self.assertEqual(graph, after)
                    self.assertEqual('REPLAY', restarted.tick()['status'])
                    self.assertEqual(graph, restarted.guard.receipt_graph(restarted.core.local_operator(Capability.READ), restarted.operation_id))
                    self.assertEqual(1, target.client.read()['effect_count'])
                finally:
                    restarted.close()
            finally:
                first.close(); target.close()
