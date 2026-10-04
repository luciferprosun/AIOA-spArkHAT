import unittest
from dataclasses import replace, FrozenInstanceError
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from lab.archaioa.authority import Money
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.contracts import ContractValidationError


class LiabilityTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.liability import LiabilityRecord, LiabilityStatus
        return LiabilityRecord, LiabilityStatus

    def fixture(self):
        Record, Status = self.api()
        return Record(liability_id='liability-1', task_id='task-1', request_ref='request-1', kind='UNKNOWN_EFFECT', status=Status.OPEN, opened_at=datetime(2026, 10, 4, tzinfo=timezone.utc), max_cost_exposure=Money(Decimal('10'), 'EUR'))

    def test_all_statuses_roundtrip(self):
        value = self.fixture()
        _, Status = self.api()
        for record in (value, replace(value, status=Status.ESCALATED), replace(value, status=Status.CLOSED, closed_at=value.opened_at + timedelta(minutes=5), resolution_ref='resolution-1')):
            with self.subTest(status=record.status):
                self.assertEqual(type(record).from_json(record.to_json()), record)
        with self.assertRaises(FrozenInstanceError):
            value.kind = 'changed'

    def test_closed_requires_resolution_and_time(self):
        value = self.fixture()
        _, Status = self.api()
        for changes in ({}, {'closed_at': value.opened_at}, {'resolution_ref': 'resolution-1'}, {'closed_at': value.opened_at - timedelta(seconds=1), 'resolution_ref': 'resolution-1'}):
            with self.subTest(changes=changes), self.assertRaises(ContractValidationError):
                replace(value, status=Status.CLOSED, **changes)

    def test_open_and_escalated_reject_closure_fields(self):
        value = self.fixture()
        _, Status = self.api()
        for status in (Status.OPEN, Status.ESCALATED):
            for changes in ({'closed_at': value.opened_at}, {'resolution_ref': 'resolution-1'}):
                with self.subTest(status=status), self.assertRaises(ContractValidationError):
                    replace(value, status=status, **changes)

    def test_invalid_ids_status_times_and_exposure(self):
        value = self.fixture()
        for field, bad in (('liability_id', ''), ('task_id', ''), ('request_ref', ''), ('kind', ''), ('status', 'OPEN'), ('opened_at', datetime(2026, 1, 1)), ('max_cost_exposure', 1.2)):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(value, **{field: bad})

    def test_refs_are_immutable_metadata_and_affect_digest(self):
        value = self.fixture()
        ref = EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1')
        refs = [ref]
        record = replace(value, evidence_refs=refs, dependency_refs=refs)
        before = record.digest()
        refs.clear()
        self.assertEqual(record.evidence_refs, (ref,))
        self.assertEqual(record.dependency_refs, (ref,))
        self.assertEqual(record.digest(), before)
        self.assertNotEqual(value.digest(), before)
        self.assertEqual(type(record).from_json(record.to_json()), record)
