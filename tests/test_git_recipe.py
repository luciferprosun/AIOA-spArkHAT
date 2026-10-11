"""Inert U09 plans; Git executes only in separately reviewed U06 fixtures."""
from dataclasses import FrozenInstanceError, replace
import json
import unittest
from runtime.mission.git_recipe import SyntheticGitPlan, SyntheticGitSeed


class SyntheticGitRecipeTests(unittest.TestCase):
    def plan(self, **changes):
        data = dict(repo_ref='synthetic:tiny', expected_revision=1, base=b'value=4\n',
                    replacement=b'value=5\n', branch='fixture/approved-tiny')
        return SyntheticGitPlan(**(data | changes))

    def test_preview_and_recipe_are_inert_immutable_values(self):
        plan = self.plan()
        with self.assertRaises(FrozenInstanceError):
            plan.branch = 'main'
        preview = plan.commit_preview()
        self.assertEqual('NONE', preview['authority'])
        self.assertEqual(plan.base_head, preview['expected_head'])
        self.assertEqual(plan.commit_head, preview['proposed_commit'])
        self.assertIn(b'-value=4\n+value=5\n', plan.diff_bytes())
        spec = plan.recipe_spec(SyntheticGitSeed('synthetic:tiny', 1, b'value=4\n'))
        self.assertEqual(plan.result_bytes(), spec['expected']['git-result.json'])
        spec['files']['after.txt'] = b'forged'
        self.assertEqual(b'value=5\n', plan.recipe_spec(SyntheticGitSeed('synthetic:tiny', 1, b'value=4\n'))['files']['after.txt'])

    def test_base_head_revision_and_diff_are_bound(self):
        plan = self.plan()
        other = replace(plan, base=b'value=3\n')
        self.assertNotEqual(plan.base_head, other.base_head)
        self.assertNotEqual(plan.target_fingerprint, other.target_fingerprint)
        self.assertNotEqual(plan.digest, replace(plan, replacement=b'value=6\n').digest)
        changed_branch = replace(plan, branch='fixture/approved-other')
        self.assertEqual(plan.commit_head, changed_branch.commit_head)
        self.assertNotEqual(plan.digest, changed_branch.digest)
        self.assertEqual(40, len(plan.base_head))
        self.assertEqual(40, len(plan.commit_head))

    def test_only_fresh_synthetic_repository_and_branch_are_allowed(self):
        for repo in ('luciferprosun/AIOA-spArkHAT', '/tmp/repo', 'synthetic:../x', 'synthetic:a/b', True):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                self.plan(repo_ref=repo)
        for branch in ('main', 'origin/main', '../x', 'fixture/approved-x.lock', 'fixture/approved-x\n', 'fixture/base'):
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                self.plan(branch=branch)
        for revision in (0, 2, True, '1'):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.plan(expected_revision=revision)

    def test_fixed_source_and_nonempty_change(self):
        for code in (b'import os\nos._exit(0)\n', b'value=5', b'value=05\n', b'value=True\n', bytearray(b'value=5\n')):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.plan(replacement=code)
        with self.assertRaises(ValueError):
            self.plan(replacement=b'value=4\n')

    def test_seed_is_independent_and_no_execution_fields_exist(self):
        plan = self.plan()
        spec = plan.recipe_spec(SyntheticGitSeed('synthetic:foreign', 1, b'value=9\n'))
        self.assertEqual('synthetic:foreign', json.loads(spec['files']['seed.json'])['repo_ref'])
        self.assertEqual(b'value=9\n', spec['files']['before.txt'])
        with self.assertRaises(ValueError):
            plan.recipe_spec({'owner_approved': True})
        with self.assertRaises(TypeError):
            SyntheticGitPlan('synthetic:tiny', 1, b'value=4\n', b'value=5\n', 'fixture/approved-tiny', argv=['git', 'push'])

    def test_github_preview_has_no_remote_authority(self):
        preview = self.plan().github_preview()
        self.assertEqual('PREVIEW_ONLY', preview['action'])
        self.assertEqual('NONE', preview['authority'])
        self.assertEqual(0, preview['remote_effects'])
        self.assertEqual('INERT_FIXTURE', preview['ci']['status'])


if __name__ == '__main__':
    unittest.main()
