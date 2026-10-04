import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from dataclasses import replace, FrozenInstanceError
from lab.archaioa.contracts import ContractValidationError


class AuthorityTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
        return AuthorityScope, Money, RiskLevel

    def scope(self):
        Scope, Money, Risk = self.api()
        start = datetime(2026, 10, 4, tzinfo=timezone.utc)
        return Scope(['write', 'read'], 'target-1', Risk.MODERATE, Money(Decimal('10.00'), 'EUR'), start, start + timedelta(hours=1), 'owner-1', 'task-1')

    def test_scope_normalizes_and_freezes_operation_set(self):
        scope = self.scope()
        operations = ['write', 'read', 'read']
        value = replace(scope, operation_classes=operations)
        operations.clear()
        self.assertEqual(value.operation_classes, ('read', 'write'))
        self.assertEqual(value, scope)
        self.assertEqual(type(value).from_json(value.to_json()), value)
        with self.assertRaises(FrozenInstanceError):
            value.owner_scope = 'other'

    def test_scope_rejects_empty_scopes_invalid_window_and_risk(self):
        scope = self.scope()
        for field, bad in (('operation_classes', []), ('operation_classes', ['']), ('operation_classes', 'read'), ('target_scope', ''), ('owner_scope', ''), ('task_scope', ''), ('risk_ceiling', -1), ('risk_ceiling', 'LOW'), ('monetary_ceiling', 1.2), ('not_before', datetime(2026, 1, 1)), ('expires_at', scope.not_before)):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                replace(scope, **{field: bad})

    def test_money_rejects_float_negative_and_invalid_currency(self):
        _, Money, _ = self.api()
        for bad in (1.2, 2, Decimal('-1'), Decimal('NaN'), Decimal('Infinity')):
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                Money(bad, 'EUR')
        for bad in ('eur', '', 'EURO', None):
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                Money(Decimal('1'), bad)
        self.assertEqual(Money(Decimal('1.000'), 'EUR').to_dict()['amount'], '1')
        wire = Money(Decimal('1'), 'EUR').to_dict()
        for bad in (1.0, 'NaN', 'bad'):
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                Money.from_dict(wire | {'amount': bad})

    def test_money_precision_is_independent_of_decimal_context(self):
        from decimal import localcontext
        _, Money, _ = self.api()
        amount = Decimal('12345678901234567890.123456789')
        with localcontext() as context:
            context.prec = 3
            value = Money(amount, 'EUR')
            self.assertEqual(value.to_dict()['amount'], '12345678901234567890.123456789')

    def test_exact_scope_containment_basics(self):
        scope = self.scope()
        _, Money, Risk = self.api()
        narrower = replace(scope, operation_classes=('read',), risk_ceiling=Risk.LOW, monetary_ceiling=Money(Decimal('1'), 'EUR'), not_before=scope.not_before + timedelta(minutes=1))
        self.assertTrue(scope.contains(narrower))
        self.assertFalse(narrower.contains(scope))
        for field, bad in (('target_scope', 'other'), ('owner_scope', 'other'), ('task_scope', 'other'), ('monetary_ceiling', Money(Decimal('1'), 'USD'))):
            with self.subTest(field=field):
                self.assertFalse(scope.contains(replace(narrower, **{field: bad})))
