import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from dataclasses import replace, FrozenInstanceError
from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.contracts import ContractValidationError


class WarrantTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
        return EffectWarrant, RevisionPolicy

    def fixture(self):
        Warrant, Policy = self.api()
        start = datetime(2026, 10, 4, tzinfo=timezone.utc)
        target = 'sha256:' + 'b' * 64
        scope = AuthorityScope(('write',), target, RiskLevel.MODERATE, Money(Decimal('10'), 'EUR'), start, start + timedelta(hours=1), 'owner-1', 'task-1')
        return Warrant(warrant_id='warrant-1', task_id='task-1', owner_scope='owner-1', operation_class='write', operation_hash='sha256:' + 'a' * 64, target_fingerprint=target, expected_target_revision='revision-1', revision_policy=Policy.REQUIRE, decision_dependency_root=DecisionDependencyRoot(()), lease_epoch=0, authority_scope=scope, approval_digest='sha256:' + 'c' * 64, money_reservation_id='money-1', risk_reservation_id='risk-1', nonce='fixture-nonce-1', issued_at=start, expires_at=start + timedelta(minutes=30))

    def test_warrant_roundtrip_and_immutability(self):
        value = self.fixture()
        self.assertEqual(type(value).from_json(value.to_json()), value)
        self.assertEqual(type(value).from_dict(dict(reversed(list(value.to_dict().items())))).digest(), value.digest())
        with self.assertRaises(FrozenInstanceError):
            value.lease_epoch = 1

    def test_warrant_rejects_required_ids_and_hashes(self):
        value = self.fixture()
        fields = ('warrant_id', 'task_id', 'owner_scope', 'operation_class', 'operation_hash', 'target_fingerprint', 'approval_digest', 'money_reservation_id', 'risk_reservation_id', 'nonce')
        for field in fields:
            for bad in ('', ' ', None):
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                    replace(value, **{field: bad})
        for field in ('operation_hash', 'target_fingerprint', 'approval_digest'):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(value, **{field: 'not-a-digest'})

    def test_warrant_rejects_negative_epoch_and_invalid_expiry(self):
        value = self.fixture()
        for field, bad in (('lease_epoch', -1), ('lease_epoch', True), ('lease_epoch', 1.0), ('issued_at', datetime(2026, 1, 1)), ('expires_at', value.issued_at), ('expires_at', value.issued_at - timedelta(seconds=1))):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(value, **{field: bad})

    def test_warrant_rejects_missing_root_and_malformed_scope(self):
        value = self.fixture()
        for field in ('decision_dependency_root', 'authority_scope'):
            for bad in (None, {}, 'sha256:' + 'a' * 64):
                with self.subTest(field=field), self.assertRaises(ContractValidationError):
                    replace(value, **{field: bad})
        wire = value.to_dict()
        del wire['decision_dependency_root']
        with self.assertRaises(ContractValidationError):
            type(value).from_dict(wire)

    def test_warrant_bindings_fit_scope(self):
        value = self.fixture()
        for field, bad in (('owner_scope', 'other'), ('task_id', 'other'), ('operation_class', 'delete'), ('target_fingerprint', 'sha256:' + 'd' * 64), ('issued_at', value.issued_at - timedelta(seconds=1)), ('expires_at', value.authority_scope.expires_at + timedelta(seconds=1))):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(value, **{field: bad})

    def test_null_revision_requires_explicit_policy(self):
        value = self.fixture()
        _, Policy = self.api()
        with self.assertRaises(ContractValidationError):
            replace(value, expected_target_revision=None)
        valid = replace(value, expected_target_revision=None, revision_policy=Policy.ALLOW_UNVERSIONED)
        self.assertEqual(type(valid).from_json(valid.to_json()), valid)
        with self.assertRaises(ContractValidationError):
            replace(value, expected_target_revision='')

    def test_reservations_are_consistent_with_ceilings(self):
        value = self.fixture()
        for field in ('money_reservation_id', 'risk_reservation_id'):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(value, **{field: 'NONE'})
        scope = replace(value.authority_scope, risk_ceiling=RiskLevel.LOW, monetary_ceiling=Money(Decimal('0'), 'EUR'))
        zero = replace(value, authority_scope=scope, money_reservation_id='NONE', risk_reservation_id='NONE')
        self.assertEqual(type(zero).from_json(zero.to_json()), zero)
        for field in ('money_reservation_id', 'risk_reservation_id'):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(zero, **{field: 'reservation-1'})
