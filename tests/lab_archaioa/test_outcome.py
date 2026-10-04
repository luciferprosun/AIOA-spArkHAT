import unittest
from dataclasses import FrozenInstanceError


class OutcomeTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.outcome import Applied, NotApplied, Unknown
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.contracts import ContractValidationError
        return Applied, NotApplied, Unknown, EvidenceRef, ContractValidationError

    def test_outcome_variants_reject_implicit_boolean(self):
        Applied, NotApplied, Unknown, _, _ = self.api()
        for value in (Applied('receipt-1'), NotApplied(), Unknown('liability-1')):
            with self.subTest(variant=type(value).__name__):
                with self.assertRaises(TypeError):
                    bool(value)
                self.assertEqual(type(value).from_json(value.to_json()), value)

    def test_unknown_requires_nonblank_liability(self):
        _, _, Unknown, _, Error = self.api()
        for bad in ('', ' ', None, 4):
            with self.subTest(bad=bad), self.assertRaises(Error):
                Unknown(bad)

    def test_applied_requires_receipt(self):
        Applied, _, _, _, Error = self.api()
        with self.assertRaises(Error):
            Applied('')

    def test_outcome_freezes_evidence_inputs(self):
        Applied, _, _, EvidenceRef, _ = self.api()
        ref = EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1')
        refs = [ref]
        value = Applied('receipt-1', refs)
        before = value.to_json()
        refs.clear()
        self.assertEqual(value.evidence_refs, (ref,))
        self.assertEqual(value.to_json(), before)
        with self.assertRaises(FrozenInstanceError):
            value.receipt_ref = 'changed'

    def test_outcome_rejects_raw_evidence(self):
        _, NotApplied, _, _, Error = self.api()
        with self.assertRaises(Error):
            NotApplied([{'raw_payload': 'fixture'}])
