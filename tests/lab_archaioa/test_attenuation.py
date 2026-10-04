"""PRE-03 deterministic meet-only attenuation campaign."""
import os
import random
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

from lab.archaioa import AuthorityScope, ContractValidationError, Money, RiskLevel, RevisionPolicy
from lab.archaioa.fixtures import contract_bundle


class AttenuationTests(unittest.TestCase):
    def setUp(self):
        self.parent = replace(contract_bundle().warrant.authority_scope,
                              operation_classes=('read', 'write'), risk_ceiling=RiskLevel.HIGH)

    def test_exact_relation_and_existing_semantics(self):
        from lab.archaioa.attenuation import scope_contains, validate_attenuation
        child = replace(self.parent, operation_classes=('read',))
        self.assertTrue(scope_contains(self.parent, child))
        self.assertEqual(scope_contains(self.parent, child), self.parent.contains(child))
        self.assertFalse(scope_contains(child, self.parent))
        self.assertIsNone(validate_attenuation(self.parent, child))

    def test_amplifications_rejected(self):
        from lab.archaioa.attenuation import validate_attenuation
        changes = {
            'extra_operation': dict(operation_classes=('read', 'write', 'delete')),
            'extra_target': dict(target_scope='other-target'),
            'higher_risk': dict(risk_ceiling=RiskLevel.CRITICAL),
            'higher_money': dict(monetary_ceiling=Money(Decimal('11'), 'EUR')),
            'earlier_start': dict(not_before=self.parent.not_before - timedelta(seconds=1)),
            'later_expiry': dict(expires_at=self.parent.expires_at + timedelta(seconds=1)),
            'owner_mismatch': dict(owner_scope='other-owner'),
            'task_mismatch': dict(task_scope='other-task'),
            'currency_mismatch': dict(monetary_ceiling=Money(Decimal('1'), 'USD')),
        }
        for name, change in changes.items():
            with self.subTest(name=name), self.assertRaises(ContractValidationError):
                validate_attenuation(self.parent, replace(self.parent, **change))

    def test_meet_clamps_broader_restriction(self):
        from lab.archaioa.attenuation import attenuate_scope
        restriction = replace(self.parent, operation_classes=('read', 'delete'),
                              risk_ceiling=RiskLevel.CRITICAL,
                              monetary_ceiling=Money(Decimal('100'), 'EUR'),
                              not_before=self.parent.not_before - timedelta(seconds=1),
                              expires_at=self.parent.expires_at + timedelta(seconds=1))
        self.assertEqual(attenuate_scope(self.parent, restriction),
                         replace(self.parent, operation_classes=('read',)))

    def test_incomparable_and_empty_meets_fail_closed(self):
        from lab.archaioa.attenuation import attenuate_scope
        changes = [dict(target_scope='other'), dict(owner_scope='other'), dict(task_scope='other'),
                   dict(monetary_ceiling=Money(Decimal('1'), 'USD')),
                   dict(operation_classes=('delete',)),
                   dict(not_before=self.parent.expires_at, expires_at=self.parent.expires_at + timedelta(hours=1))]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ContractValidationError):
                attenuate_scope(self.parent, replace(self.parent, **change))

    def test_strict_wire_and_duplicate_inputs(self):
        from lab.archaioa.attenuation import attenuate_scope
        original = self.parent.to_dict()
        invalid = [original | {'private': 'DO_NOT_ECHO'},
                   {k: v for k, v in original.items() if k != 'risk_ceiling'},
                   original | {'operation_classes': ['read', 'read']},
                   original | {'operation_classes': ['read', {'read': 'write'}]},
                   original | {'risk_ceiling': 'UNKNOWN'},
                   original | {'target_scope': ['a', 'b']}, None, [], object()]
        for wire in invalid:
            with self.subTest(wire=wire), self.assertRaises(ContractValidationError) as caught:
                attenuate_scope(self.parent, wire)
            self.assertNotIn('DO_NOT_ECHO', str(caught.exception))
        self.assertEqual(attenuate_scope(original, original), self.parent)
        with self.assertRaises(ContractValidationError):
            attenuate_scope(original | {'operation_classes': ['read', 'read']}, original)

    def test_siblings_cannot_expand_each_other(self):
        from lab.archaioa.attenuation import attenuate_scope, validate_attenuation
        left = replace(self.parent, operation_classes=('read',))
        right = replace(self.parent, operation_classes=('write',))
        with self.assertRaises(ContractValidationError):
            attenuate_scope(left, right)
        for sibling in (left, right):
            with self.assertRaises(ContractValidationError):
                validate_attenuation(sibling, self.parent)
        import lab.archaioa.attenuation as api
        self.assertFalse(any('join' in name or 'union' in name or 'merge' in name for name in dir(api)))

    def test_revision_policy_attenuation(self):
        from lab.archaioa.attenuation import AuthorityBounds, attenuate_authority, validate_authority_attenuation
        strict = AuthorityBounds(self.parent, RevisionPolicy.REQUIRE)
        broad = AuthorityBounds(self.parent, RevisionPolicy.ALLOW_UNVERSIONED)
        with self.assertRaises(ContractValidationError):
            validate_authority_attenuation(strict, broad)
        validate_authority_attenuation(broad, strict)
        self.assertEqual(attenuate_authority(strict, broad), strict)
        self.assertEqual(attenuate_authority(broad, strict), strict)
        self.assertEqual(AuthorityBounds.from_json(strict.to_json()), strict)
        with self.assertRaises(FrozenInstanceError):
            strict.revision_policy = RevisionPolicy.ALLOW_UNVERSIONED
        for wire in (strict.to_dict() | {'unknown': 1},
                     {k: v for k, v in strict.to_dict().items() if k != 'revision_policy'},
                     strict.to_dict() | {'revision_policy': None}):
            with self.assertRaises(ContractValidationError):
                AuthorityBounds.from_dict(wire)

    def test_generated_1200_cases_and_chains(self):
        from lab.archaioa.attenuation import (attenuate_scope, scope_contains, AuthorityBounds,
                                               attenuate_authority, validate_authority_attenuation)
        rng = random.Random(3003)
        human_root = replace(self.parent, risk_ceiling=RiskLevel.CRITICAL,
                             monetary_ceiling=Money(Decimal('100'), 'EUR'))
        for case in range(1200):
            parent = replace(human_root, monetary_ceiling=Money(Decimal(rng.randrange(1, 100)), 'EUR'),
                             risk_ceiling=rng.choice(tuple(RiskLevel)))
            restriction = replace(parent, operation_classes=rng.choice((('read',), ('write',), ('read', 'write'))),
                                  monetary_ceiling=Money(Decimal(rng.randrange(100)), 'EUR'),
                                  risk_ceiling=rng.choice(tuple(RiskLevel)),
                                  not_before=parent.not_before + timedelta(seconds=rng.randrange(100)),
                                  expires_at=parent.expires_at - timedelta(seconds=rng.randrange(100)))
            child = attenuate_scope(parent, restriction)
            self.assertTrue(scope_contains(human_root, parent), case)
            self.assertTrue(scope_contains(parent, child), case)
            self.assertTrue(scope_contains(restriction, child), case)
            bounds = AuthorityBounds(parent, rng.choice(tuple(RevisionPolicy)))
            restricted_bounds = AuthorityBounds(restriction, rng.choice(tuple(RevisionPolicy)))
            child_bounds = attenuate_authority(bounds, restricted_bounds)
            validate_authority_attenuation(bounds, child_bounds)
            validate_authority_attenuation(restricted_bounds, child_bounds)
            self.assertEqual(attenuate_authority(child_bounds, restricted_bounds), child_bounds)
            self.assertEqual(attenuate_scope(child, restriction), child)
            self.assertEqual(attenuate_scope(parent, child), child)
            for _ in range(4):
                next_child = attenuate_scope(child, replace(restriction,
                    monetary_ceiling=Money(Decimal(rng.randrange(100)), 'EUR'),
                    risk_ceiling=rng.choice(tuple(RiskLevel)),
                    operation_classes=(child.operation_classes[0],),
                    not_before=child.not_before + timedelta(seconds=rng.randrange(10)),
                    expires_at=child.expires_at - timedelta(seconds=rng.randrange(10))))
                # Independent per-dimension oracle, including human root.
                self.assertLessEqual(set(next_child.operation_classes), set(child.operation_classes))
                self.assertEqual(next_child.target_scope, child.target_scope)
                self.assertEqual(next_child.owner_scope, child.owner_scope)
                self.assertEqual(next_child.task_scope, child.task_scope)
                self.assertEqual(next_child.monetary_ceiling.currency, child.monetary_ceiling.currency)
                self.assertLessEqual(next_child.risk_ceiling.rank, child.risk_ceiling.rank)
                self.assertLessEqual(next_child.monetary_ceiling.amount, child.monetary_ceiling.amount)
                self.assertGreaterEqual(next_child.not_before, child.not_before)
                self.assertLessEqual(next_child.expires_at, child.expires_at)
                self.assertTrue(scope_contains(parent, next_child))
                self.assertTrue(scope_contains(human_root, next_child))
                next_bounds = attenuate_authority(child_bounds, AuthorityBounds(
                    next_child, rng.choice(tuple(RevisionPolicy))))
                validate_authority_attenuation(child_bounds, next_bounds)
                child_bounds = next_bounds
                child = next_child

    def test_scope_roundtrip_immutability(self):
        from lab.archaioa.attenuation import attenuate_scope
        child = attenuate_scope(self.parent, self.parent)
        self.assertEqual(AuthorityScope.from_json(child.to_json()), child)
        with self.assertRaises(FrozenInstanceError):
            child.task_scope = 'other'

    def test_hash_seeds_and_import_isolation(self):
        code = '''
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('runtime', 'deploy', 'web', 'requests', 'socket'):
            raise AssertionError('forbidden import')
sys.meta_path.insert(0, Block())
from lab.archaioa.attenuation import AuthorityBounds, attenuate_authority
from lab.archaioa.decision_binding import bind_decision
from lab.archaioa.fixtures import contract_bundle
from lab.archaioa import RevisionPolicy
from dataclasses import replace
b = contract_bundle()
p = replace(b.warrant.authority_scope, operation_classes=tuple({'write', 'read'}))
a = AuthorityBounds(p, RevisionPolicy.REQUIRE)
c = attenuate_authority(a, a)
r = bind_decision(b.warrant, tuple(reversed(b.evidence_refs)))
for x in (c, r):
    print(x.to_json())
    print(x.contract_digest())
'''
        outputs = [subprocess.run([sys.executable, '-c', code], env=dict(os.environ, PYTHONHASHSEED=seed),
                                  check=True, capture_output=True, text=True, timeout=20).stdout
                   for seed in ('0', '1', '91')]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])

    def test_bounds_invalid_types_and_strict_nested_wire(self):
        from lab.archaioa.attenuation import AuthorityBounds, attenuate_authority, validate_authority_attenuation
        bounds = AuthorityBounds(self.parent, RevisionPolicy.REQUIRE)
        for invalid in (None, {}, self.parent, 'private-input'):
            with self.assertRaises(ContractValidationError):
                attenuate_authority(bounds, invalid)
            with self.assertRaises(ContractValidationError):
                validate_authority_attenuation(invalid, bounds)
        for wire in (bounds.to_dict() | {'schema_version': 2},
                     bounds.to_dict() | {'scope': self.parent.to_dict() | {'operation_classes': ['read', 'read']}},
                     bounds.to_dict() | {'scope': self.parent.to_dict() | {'revision_policy': 'ALLOW_UNVERSIONED'}}):
            with self.assertRaises(ContractValidationError):
                AuthorityBounds.from_dict(wire)

    def test_bounds_digest_domain_separation(self):
        from lab.archaioa.attenuation import AuthorityBounds
        from lab.archaioa import canonical_digest
        bounds = AuthorityBounds(self.parent, RevisionPolicy.REQUIRE)
        self.assertEqual(bounds.contract_digest(), canonical_digest('PCAF/AuthorityBounds/v1', bounds.to_dict()))
        self.assertNotEqual(bounds.contract_digest(), canonical_digest('PCAF/DecisionBinding/v1', bounds.to_dict()))
