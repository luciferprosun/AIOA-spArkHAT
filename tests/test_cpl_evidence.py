"""Manifest-relative tamper detection and exclusive runtime ownership."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from critical_loop.evidence import CPLTraceStore
from critical_loop.service import CriticalPromptLoopService
from providers.exact import ExactCallError


class FixtureManager:
    fixture_base_url = 'http://127.0.0.1:1/api/v1'


class CPLEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = CPLTraceStore(self.root / 'trace', known_secrets=('synthetic-private-credential',))
        self.run = 'cpl-' + 'a' * 32
        self.store.create(self.run)
        for phase in ['PLANNED', 'DRAFTING', 'COMPLETED']:
            self.manifest = self.store.append(self.run, phase, {'run_id': self.run, 'execution_status': phase,
                'draft': 'synthetic-private-credential', 'final_answer': None})
        self.log = self.store.root / self.run / 'provenance/provenance_log.jsonl'
        self.original = self.log.read_text()

    def tearDown(self):
        self.temp.cleanup()

    def test_T13_modified_reordered_missing_foreign_and_truncated_events(self):
        entries = [json.loads(line) for line in self.original.splitlines()]
        cases = {}
        changed = copy.deepcopy(entries)
        changed[1]['payload']['view']['draft'] = 'changed'
        cases['modified'] = changed
        cases['reordered'] = [entries[1], entries[0], entries[2]]
        cases['removed_middle'] = [entries[0], entries[2]]
        foreign = copy.deepcopy(entries)
        foreign[1]['payload']['run_id'] = 'cpl-' + 'b' * 32
        cases['foreign_run'] = foreign
        cases['truncated_tail'] = entries[:-1]
        for label, data in cases.items():
            with self.subTest(label=label):
                self.log.write_text(''.join(json.dumps(item) + '\n' for item in data))
                self.assertFalse(self.store.verify(self.run, self.manifest)['ok'])
        self.log.write_text(self.original[:-50])
        with self.assertRaises(ExactCallError):
            self.store.verify(self.run, self.manifest)

    def test_T13_rewritten_local_manifest_needs_retained_external_anchor(self):
        entries = [json.loads(line) for line in self.original.splitlines()][:-1]
        self.log.write_text(''.join(json.dumps(item) + '\n' for item in entries))
        rewritten = {**self.manifest, 'event_count': 2, 'terminal_hash': entries[-1]['entry_hash']}
        (self.log.parent.parent / 'manifest.json').write_text(json.dumps(rewritten))
        self.assertTrue(self.store.verify(self.run)['ok'])  # Explicit limitation, not a truth seal.
        self.assertFalse(self.store.verify(self.run, self.manifest)['ok'])

    def test_T14_secrets_redacted_before_shared_chain_and_manifest(self):
        self.assertNotIn('synthetic-private-credential', self.original)
        self.assertIn('[REDACTED]', self.original)
        self.assertTrue(self.store.verify(self.run, self.manifest)['ok'])
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_T07_second_owner_cannot_interrupt_active_peer(self):
        first = CriticalPromptLoopService(FixtureManager(), self.root / 'owned')
        try:
            with self.assertRaisesRegex(ExactCallError, 'CPL_STATE_ROOT_IN_USE'):
                CriticalPromptLoopService(FixtureManager(), self.root / 'owned')
        finally:
            first.close()
        second = CriticalPromptLoopService(FixtureManager(), self.root / 'owned')
        second.close()

    def test_T18_symlink_root_and_run_are_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.store.root, target_is_directory=True)
        for path in [link, link / 'descendant']:
            with self.assertRaises(ExactCallError):
                CPLTraceStore(path)
        foreign = 'cpl-' + 'b' * 32
        (self.store.root / foreign).symlink_to(self.log.parent.parent, target_is_directory=True)
        with self.assertRaises(ExactCallError):
            self.store.verify(foreign)


if __name__ == '__main__':
    unittest.main()
