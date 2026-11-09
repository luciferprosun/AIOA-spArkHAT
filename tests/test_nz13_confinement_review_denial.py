"""A confinement fixture must prove denial without bypassing coding review."""
import copy
import unittest
from types import SimpleNamespace

import nz11_kernel_acceptance as kernel

from runtime.mission.repair import semantic_review


def denied_view():
    states = ('QUEUED', 'RUNNING', 'VALIDATING', 'REPAIRING', 'VALIDATING', 'DENIED')
    return {
        'state': 'DENIED', 'capsule_digest': None, 'authority': 'NONE',
        'effects_registered': False, 'effect_verified': False, 'receipt_count': 6,
        'receipts': [{'receipt': {'state': state}} for state in states],
        'run_result': {
            'status': 'DENIED', 'failure_code': 'REVIEW_FIXTURE_BYPASS', 'final_patchset': None,
            'history': ['PATCH_POLICY', 'FAST_TESTS', 'REPAIRING', 'PATCH_POLICY',
                        'FAST_TESTS', 'TARGETED_TESTS', 'FINAL_TESTS', 'INDEPENDENT_REVIEW'],
            'attempts': [
                {'status': 'FAIL', 'cleanup_orphans': 0,
                 'steps': [{'stage': 'FAST_TESTS', 'status': 'FAIL', 'exit_code': 1,
                            'core_warrant_digest': 'sha256:' + 'a' * 64, 'evidence_digest': 'b' * 64}]},
                {'status': 'DENIED', 'cleanup_orphans': 0,
                 'steps': [{'stage': stage, 'status': 'PASS', 'exit_code': 0,
                            'core_warrant_digest': 'sha256:' + str(index + 1) * 64,
                            'evidence_digest': str(index + 4) * 64}
                           for index, stage in enumerate(('FAST_TESTS', 'TARGETED_TESTS', 'FINAL_TESTS'))]},
            ],
        },
    }


class ConfinementReviewDenialTests(unittest.TestCase):
    def setUp(self):
        self.review_contract = getattr(kernel, 'review_denial_contract', None)
        self.assertTrue(callable(self.review_contract), 'Missing explicit negative acceptance contract')

    def contract(self, value, code='REVIEW_FIXTURE_BYPASS'):
        return self.review_contract(value, expected_failure_code=code)

    def test_exact_denial_reports_isolation_only_and_never_a_coding_success(self):
        value = denied_view()
        before = copy.deepcopy(value)
        report = self.contract(value)
        self.assertEqual(value, before)
        self.assertEqual(report['status'], 'EXPECTED_REVIEW_DENIAL')
        self.assertFalse(report['git_actuation'])
        self.assertFalse(report['coding_success'])
        self.assertEqual(report['verified_oracle_stages'], 3)

    def test_unknown_expected_failure_selector_cannot_open_negative_mode(self):
        for code in ('', None, True, 'ANY_DENIAL', 'SANDBOX_FAILURE'):
            with self.subTest(code=code), self.assertRaises(AssertionError):
                self.contract(denied_view(), code)

    def test_success_unknown_and_blocked_states_are_not_the_expected_denial(self):
        for state in ('REVIEW_REQUIRED', 'UNKNOWN', 'DONE', 'BLOCKED'):
            with self.subTest(state=state), self.assertRaises(AssertionError):
                value = denied_view()
                value['state'] = state
                self.contract(value)

    def test_capsule_effect_or_authority_cannot_survive_the_negative_fixture(self):
        for field, replacement in (('capsule_digest', 'a' * 64), ('authority', 'OWNER'),
                                   ('effects_registered', True), ('effect_verified', True),
                                   ('effects_registered', 0), ('effect_verified', 0)):
            with self.subTest(field=field, replacement=replacement), self.assertRaises(AssertionError):
                value = denied_view()
                value[field] = replacement
                self.contract(value)

    def test_wrong_failure_or_a_retained_patch_cannot_be_accepted(self):
        for field, replacement in (('failure_code', 'SOURCE_DRIFT'), ('status', 'PATCH_READY'),
                                   ('final_patchset', {})):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                value = denied_view()
                value['run_result'][field] = replacement
                self.contract(value)

    def test_missing_repair_attempt_and_extra_attempts_are_rejected(self):
        for count in (0, 1, 3):
            with self.subTest(count=count), self.assertRaises(AssertionError):
                value = denied_view()
                values = value['run_result']['attempts']
                value['run_result']['attempts'] = (values + values)[:count]
                self.contract(value)

    def test_incomplete_wrongly_ordered_or_unknown_final_oracles_are_rejected(self):
        for mutation in ('missing', 'reverse', 'unknown'):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                value = denied_view()
                steps = value['run_result']['attempts'][-1]['steps']
                if mutation == 'missing':
                    steps.pop()
                elif mutation == 'reverse':
                    steps.reverse()
                else:
                    steps[1]['status'] = 'UNKNOWN'
                self.contract(value)

    def test_orphans_nonzero_exit_and_missing_provenance_are_rejected(self):
        for mutation in ('orphan', 'exit', 'first-exit', 'warrant', 'evidence', 'duplicate'):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                value = denied_view()
                attempt = value['run_result']['attempts'][-1]
                if mutation == 'orphan':
                    attempt['cleanup_orphans'] = 1
                elif mutation == 'exit':
                    attempt['steps'][0]['exit_code'] = 1
                elif mutation == 'first-exit':
                    value['run_result']['attempts'][0]['steps'][0]['exit_code'] = 0
                elif mutation == 'warrant':
                    attempt['steps'][0]['core_warrant_digest'] = ''
                elif mutation == 'evidence':
                    attempt['steps'][0]['evidence_digest'] = ''
                else:
                    attempt['steps'][1]['evidence_digest'] = attempt['steps'][0]['evidence_digest']
                self.contract(value)

    def test_missing_independent_review_cannot_be_labelled_as_its_denial(self):
        value = denied_view()
        value['run_result']['history'].pop()
        with self.assertRaises(AssertionError):
            self.contract(value)

    def test_noncanonical_controller_history_and_receipt_counts_are_rejected(self):
        for mutation in ('count', 'state', 'missing'):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                value = denied_view()
                if mutation == 'count':
                    value['receipt_count'] = 5
                elif mutation == 'state':
                    value['receipts'][-1]['receipt']['state'] = 'APPROVED'
                else:
                    value['receipts'].pop()
                self.contract(value)

    def test_product_constant_fixture_review_guard_remains_enabled(self):
        patchset = SimpleNamespace(verify_digest=lambda: None,
                                   canonical_diff='--- a/src/app.py\n+++ b/src/app.py\n+    return 7\n')
        self.assertEqual(semantic_review(patchset), 'REVIEW_FIXTURE_BYPASS')
