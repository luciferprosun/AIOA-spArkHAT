import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('oct6', Path(__file__).parents[1] / 'scripts/oct6_integration_preflight.py')
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.root / 'shared.txt').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.git('update-ref', 'refs/remotes/origin/main', self.base)
        self.git('checkout', '-b', 'nebius-personal-ai')
        (self.root / 'shared.txt').write_text('source\n')
        self.git('commit', '-am', 'source')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.DEVNULL)

    def report(self):
        return preflight.inspect(self.root, expected_main=self.base, evidence=[])

    def test_clean_source_and_immutability(self):
        before = self.git('show-ref')
        report = self.report()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['divergence'], {'source_unique': 1, 'main_unique': 0})
        self.assertEqual(len(report['unique_commits']), 1)
        self.assertEqual(before, self.git('show-ref'))
        self.assertFalse(report['dirty'])

    def test_dirty_metadata_never_prints_content(self):
        (self.root / 'private.env').write_text('sensitive-private-value')
        report = self.report()
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertIn('DIRTY_WORKTREE', report['blockers'])
        self.assertNotIn('sensitive-private-value', json.dumps(report))

    def test_main_drift_and_overlap(self):
        self.git('checkout', 'main')
        (self.root / 'shared.txt').write_text('target\n')
        self.git('commit', '-am', 'target')
        self.git('checkout', 'nebius-personal-ai')
        report = self.report()
        self.assertIn('MAIN_CHANGED', report['blockers'])
        self.assertEqual(report['changed_file_overlap'], ['shared.txt'])
        self.assertEqual(report['divergence']['main_unique'], 1)

    def test_wrong_branch(self):
        self.git('checkout', 'main')
        self.assertIn('WRONG_BRANCH', self.report()['blockers'])

    def test_missing_evidence(self):
        report = preflight.inspect(self.root, expected_main=self.base, evidence=['missing.json'])
        self.assertIn('MISSING_EVIDENCE', report['blockers'])

    def test_missing_ref_fails_closed(self):
        self.git('update-ref', '-d', 'refs/remotes/origin/main')
        with self.assertRaises(preflight.PreflightError):
            self.report()

    def test_reject_option_revision(self):
        with self.assertRaises(ValueError):
            preflight.inspect(self.root, expected_main='--help', evidence=[])

    def test_symlink_evidence_escape(self):
        (self.root / 'escape').symlink_to('/etc/passwd')
        report = preflight.inspect(self.root, expected_main=self.base, evidence=['escape'])
        self.assertFalse(report['evidence'][0]['valid'])

    def test_human_and_json_render(self):
        report = self.report()
        self.assertIn('Preflight: PASS', preflight.render_human(report))
        self.assertEqual(json.loads(json.dumps(report))['branch'], 'nebius-personal-ai')
