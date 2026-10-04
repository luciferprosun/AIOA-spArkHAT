import unittest
from dataclasses import replace
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.contracts import ContractValidationError


class DecisionRootTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.decision_root import DecisionDependencyRoot
        return DecisionDependencyRoot

    def refs(self):
        return (EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1'), EvidenceRef('e2', 'fixture', 'sha256:' + 'b' * 64, 'r1'))

    def test_dependency_order_and_exact_duplicates_do_not_change_root(self):
        Root = self.api()
        a, b = self.refs()
        left, right = Root([a, b]), Root([b, a, a])
        self.assertEqual(left, right)
        self.assertEqual(left.root_digest, right.root_digest)
        self.assertEqual(Root.from_json(left.to_json()), left)

    def test_each_relevant_change_changes_root(self):
        Root = self.api()
        a, b = self.refs()
        baseline = Root([a, b]).root_digest
        for refs in ([a], [a, replace(b, digest='sha256:' + 'c' * 64)], [a, replace(b, source_version='r2')], [a, replace(b, evidence_id='e3')]):
            with self.subTest(refs=refs):
                self.assertNotEqual(Root(refs).root_digest, baseline)

    def test_empty_set_is_explicit_and_deterministic(self):
        Root = self.api()
        self.assertEqual(Root([]), Root(()))
        self.assertTrue(Root(()).root_digest.startswith('sha256:'))
        self.assertNotEqual(Root(()).root_digest, Root(self.refs()).root_digest)

    def test_rejects_raw_refs_and_conflicting_identity(self):
        Root = self.api()
        a, _ = self.refs()
        for bad in ([{}], ['sha256:' + 'a' * 64], [a, replace(a, source_version='r2')], None, {a}):
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                Root(bad)

    def test_input_mutation_cannot_change_root(self):
        Root = self.api()
        refs = list(self.refs())
        value = Root(refs)
        before = value.root_digest
        refs.clear()
        self.assertEqual(value.root_digest, before)
