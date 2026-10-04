"""PRE-03 decision roots hash only explicitly selected evidence."""
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

from lab.archaioa import ContractValidationError, DecisionDependencyRoot, EvidenceRef
from lab.archaioa.fixtures import contract_bundle


class DecisionBindingTests(unittest.TestCase):
    def setUp(self):
        self.bundle = contract_bundle()
        self.warrant = self.bundle.warrant
        self.refs = self.bundle.evidence_refs

    def test_current_exact_binding(self):
        from lab.archaioa.decision_binding import bind_decision, DecisionState
        result = bind_decision(self.warrant, self.refs)
        self.assertIs(result.state, DecisionState.CURRENT)
        self.assertEqual(result.warrant_id, self.warrant.warrant_id)
        self.assertEqual(result.operation_hash, self.warrant.operation_hash)
        self.assertEqual(result.expected_root, self.warrant.decision_dependency_root)
        self.assertEqual(result.current_root, DecisionDependencyRoot(self.refs))

    def assert_stale(self, refs):
        from lab.archaioa.decision_binding import bind_decision, require_current_decision, DecisionState
        result = bind_decision(self.warrant, refs)
        self.assertIs(result.state, DecisionState.STALE)
        with self.assertRaises(ContractValidationError):
            require_current_decision(self.warrant, refs)

    def test_relevant_digest_change(self):
        self.assert_stale((replace(self.refs[0], digest='sha256:' + 'd' * 64), self.refs[1]))

    def test_relevant_source_version_change(self):
        self.assert_stale((replace(self.refs[0], source_version='r2'), self.refs[1]))

    def test_relevant_selected_addition(self):
        self.assert_stale(self.refs + (EvidenceRef('e3', 'fixture', 'sha256:' + 'd' * 64, 'r1'),))

    def test_relevant_selected_removal(self):
        self.assert_stale(self.refs[1:])
        self.assert_stale(())

    def test_relevant_valid_time_change(self):
        self.assert_stale((replace(self.refs[0], valid_time=self.warrant.issued_at), self.refs[1]))
        refs = (replace(self.refs[0], valid_time=self.warrant.issued_at), self.refs[1])
        self.warrant = replace(self.warrant, decision_dependency_root=DecisionDependencyRoot(refs))
        self.assert_stale((replace(refs[0], valid_time=self.warrant.issued_at + timedelta(seconds=1)), refs[1]))

    def test_relevant_transaction_time_change(self):
        self.assert_stale((replace(self.refs[0], transaction_time=self.warrant.issued_at), self.refs[1]))
        refs = (replace(self.refs[0], transaction_time=self.warrant.issued_at), self.refs[1])
        self.warrant = replace(self.warrant, decision_dependency_root=DecisionDependencyRoot(refs))
        self.assert_stale((replace(refs[0], transaction_time=self.warrant.issued_at + timedelta(seconds=1)), refs[1]))

    def test_reordering_and_exact_duplicates(self):
        from lab.archaioa.decision_binding import bind_decision, require_current_decision
        original = bind_decision(self.warrant, self.refs)
        self.assertEqual(bind_decision(self.warrant, tuple(reversed(self.refs)) + self.refs), original)
        self.assertEqual(require_current_decision(self.warrant, self.refs), original)

    def test_unrelated_evidence_and_hat_fixture_stability(self):
        from lab.archaioa.decision_binding import bind_decision
        # Selection is explicit: the helper never receives the ambient HAT state.
        hat = {'selected': self.refs, 'other': EvidenceRef('e9', 'fixture', 'sha256:' + '9' * 64, 'r1'),
               'task': {'private_payload': 'synthetic', 'status': 'open'}}
        before = bind_decision(self.warrant, hat['selected'])
        hat['other'] = replace(hat['other'], source_version='r9', digest='sha256:' + '8' * 64)
        hat['task'] = {'status': 'closed', 'additional': ['unrelated']}
        self.assertEqual(bind_decision(self.warrant, hat['selected']), before)
        del hat['other']
        self.assertEqual(bind_decision(self.warrant, hat['selected']), before)

    def test_conflicts_malformed_and_sanitized_errors(self):
        from lab.archaioa.decision_binding import bind_decision
        for refs in ((self.refs[0], replace(self.refs[0], source_version='private-value')), None, {}, ('bad',)):
            with self.assertRaises(ContractValidationError) as caught:
                bind_decision(self.warrant, refs)
            self.assertNotIn('private-value', str(caught.exception))
        with self.assertRaises(ContractValidationError):
            bind_decision({}, self.refs)

    def test_wire_immutability_and_no_bool(self):
        from lab.archaioa.decision_binding import bind_decision, DecisionBinding
        result = bind_decision(self.warrant, self.refs)
        self.assertEqual(DecisionBinding.from_json(result.to_json()), result)
        with self.assertRaises(FrozenInstanceError):
            result.warrant_id = 'other'
        for value in (result, bind_decision(self.warrant, ())):
            with self.assertRaises(TypeError):
                bool(value)
        for wire in (result.to_dict() | {'unknown': 1}, result.to_dict() | {'state': 'STALE'},
                     result.to_dict() | {'current_root': None}):
            with self.assertRaises(ContractValidationError):
                DecisionBinding.from_dict(wire)

    def test_binding_digest_domain_and_strict_versions(self):
        from lab.archaioa.decision_binding import bind_decision, DecisionBinding
        from lab.archaioa import canonical_digest
        result = bind_decision(self.warrant, self.refs)
        self.assertEqual(result.contract_digest(), canonical_digest('PCAF/DecisionBinding/v1', result.to_dict()))
        for wire in (result.to_dict() | {'schema_version': True},
                     result.to_dict() | {'operation_hash': 'private-input'},
                     {k: v for k, v in result.to_dict().items() if k != 'warrant_id'},
                     result.to_dict() | {'expected_root': result.expected_root.to_dict() | {'unknown': 1}}):
            with self.assertRaises(ContractValidationError):
                DecisionBinding.from_dict(wire)

    def test_binding_cannot_be_reused_for_another_candidate(self):
        from lab.archaioa.decision_binding import bind_decision, validate_decision_binding
        binding = bind_decision(self.warrant, self.refs)
        validate_decision_binding(self.warrant, binding)
        for warrant in (replace(self.warrant, warrant_id='warrant-2'),
                        replace(self.warrant, operation_hash='sha256:' + 'f' * 64),
                        replace(self.warrant, decision_dependency_root=DecisionDependencyRoot(())), None):
            with self.assertRaises(ContractValidationError):
                validate_decision_binding(warrant, binding)
        for invalid in (None, {}, bind_decision(self.warrant, ())):
            with self.assertRaises(ContractValidationError):
                validate_decision_binding(self.warrant, invalid)
