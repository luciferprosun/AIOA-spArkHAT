import unittest
from dataclasses import replace, FrozenInstanceError
from datetime import timedelta

from lab.archaioa import Applied, NotApplied, Unknown, ContractValidationError, LiabilityStatus
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultKind, FaultTrace, open_liability, classify_fault, ambiguity_liability, is_blocking, resolve_liability
from lab.archaioa.pre02_fixtures import fault_story, START


class FaultTests(unittest.TestCase):
    def test_all_faults_unknown_open(self):
        for kind in FaultKind:
            trace, record, _ = fault_story(kind)
            self.assertIs(type(classify_fault(trace)), Unknown)
            self.assertEqual(classify_fault(trace).liability_id, record.liability_id)
            self.assertIs(record.status, LiabilityStatus.OPEN)
            self.assertTrue(is_blocking(record))

    def test_unknown_nonboolean_nonempty(self):
        for value in (Applied('receipt'), NotApplied(), Unknown('liability')):
            with self.assertRaises(TypeError):
                bool(value)
        for bad in ('', None, ' '):
            with self.assertRaises(ContractValidationError):
                Unknown(bad)

    def test_unambiguous_outcomes_have_no_liability(self):
        for value in (Applied('receipt'), NotApplied()):
            self.assertIsNone(ambiguity_liability(value, ()))

    def test_unknown_requires_exact_open_reference(self):
        trace, record, _ = fault_story(FaultKind.LOST_ACK)
        self.assertEqual(ambiguity_liability(classify_fault(trace), (record, record)), record)
        for records in ((), (replace(record, status=LiabilityStatus.ESCALATED),),
                        (record, replace(record, kind='other'))):
            with self.assertRaises(ContractValidationError):
                ambiguity_liability(classify_fault(trace), records)

    def test_repeated_faults_same_operation_one_liability(self):
        trace, record, _ = fault_story(FaultKind.LOST_ACK)
        for kind in FaultKind:
            changed = replace(trace, kind=kind)
            self.assertEqual(classify_fault(changed).liability_id, record.liability_id)
            self.assertIs(open_liability(changed, START, record), record)
        self.assertNotEqual(classify_fault(replace(trace, operation_digest='sha256:' + 'b' * 64)), classify_fault(trace))

    def test_existing_binding_and_closed_reuse_rejected(self):
        trace, record, _ = fault_story(FaultKind.LOST_ACK)
        closed = resolve_liability(record, self.evidence(), START)
        for bad in (replace(record, task_id='other'), replace(record, request_ref='other'),
                    replace(record, kind='other'), closed):
            with self.assertRaises(ContractValidationError):
                open_liability(trace, START, bad)

    @staticmethod
    def evidence():
        return EvidenceRef('resolution-1', 'fixture', 'sha256:' + 'c' * 64, 'r1')

    def test_explicit_resolution_requires_evidence_and_time(self):
        _, record, _ = fault_story(FaultKind.LOST_ACK)
        for evidence, time in ((None, START), ('raw', START), (self.evidence(), START - timedelta(seconds=1))):
            with self.assertRaises(ContractValidationError):
                resolve_liability(record, evidence, time)
        closed = resolve_liability(record, self.evidence(), START)
        self.assertEqual(closed.resolution_ref, self.evidence().evidence_id)
        self.assertIn(self.evidence(), closed.evidence_refs)
        self.assertFalse(is_blocking(closed))
        self.assertIs(record.status, LiabilityStatus.OPEN)
        with self.assertRaises(ContractValidationError):
            resolve_liability(closed, self.evidence(), START)

    def test_escalated_requires_explicit_resolution(self):
        _, record, _ = fault_story(FaultKind.LOST_ACK)
        record = replace(record, status=LiabilityStatus.ESCALATED)
        self.assertTrue(is_blocking(record))
        self.assertFalse(is_blocking(resolve_liability(record, self.evidence(), START)))

    def test_fault_roundtrip_immutable_and_payload_rejected(self):
        trace, _, _ = fault_story(FaultKind.LOST_ACK)
        self.assertEqual(FaultTrace.from_json(trace.to_json()), trace)
        with self.assertRaises(FrozenInstanceError):
            trace.kind = FaultKind.INCONCLUSIVE_READBACK
        with self.assertRaises(ContractValidationError):
            FaultTrace.from_dict(trace.to_dict() | {'response': 'private-fixture'})
        for changes in ({'kind': 'private-fixture'}, {'task_id': 'private fixture text'}, {'operation_digest': 'private-fixture'}):
            with self.assertRaises(ContractValidationError) as caught:
                replace(trace, **changes)
            self.assertNotIn('private', str(caught.exception))

    def test_invalid_helper_inputs_typed(self):
        for operation in (lambda: classify_fault(None), lambda: is_blocking(None),
                          lambda: ambiguity_liability(None, ()), lambda: open_liability(None, START)):
            with self.assertRaises(ContractValidationError):
                operation()
