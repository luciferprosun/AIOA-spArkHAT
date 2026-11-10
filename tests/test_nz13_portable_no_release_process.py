"""Fresh-exec SQLite recovery and the actual interprocess flock barrier."""
import json
import os
import select
import subprocess
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import test_nz13_portable_no_release as support

from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import LocalCoreTransaction, RecordKind


class PortableNoReleaseProcessTests(unittest.TestCase):
    def setUp(self):
        self.reference = support.PortableNoReleaseTests('runTest')
        self.reference.setUp()
        self.addCleanup(self.reference.doCleanups)
        self.f = self.reference.f
        self.helper = Path(__file__).with_name('nz13_no_release_process_r2.py')
        with self.f.store.target_guard():
            observed = self.f.store.observe_guarded_inventory()
        self.initial_roots = {key: getattr(observed, key) for key in ('state_root', 'resources_root', 'receipts_root')}

    def payload(self, mode):
        binding = asdict(self.f.port.binding)
        del binding['scope']
        return json.dumps({'root': str(self.f.base.path), 'binding': binding,
                           'warrant': self.f.warrant.to_dict(), 'mode': mode}) + '\n'

    def process(self):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.f.base.path), 'TMPDIR': os.environ['TMPDIR'],
               'LANG': 'C.UTF-8', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        child = subprocess.Popen([sys.executable, '-I', '-B', str(self.helper)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
            cwd=self.f.base.path, env=env, close_fds=True)
        def cleanup():
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        self.addCleanup(cleanup)
        return child

    def read_result(self, child, stdout, stderr):
        self.assertEqual(0, child.returncode, stderr[-3000:])
        lines = [json.loads(line) for line in stdout.splitlines() if line]
        self.assertEqual(1, len(lines))
        result = lines[0]
        self.assertEqual('result', result['event'])
        self.assertNotEqual(os.getpid(), result['pid'])
        self.assertEqual('NotApplied', result['outcome'])
        self.assertEqual('NONE', result['authority'])
        self.assertIs(result['grants_replay'], False)
        self.assertEqual(3, result['head_revision'])
        self.assertEqual(1, result['generation'])
        self.assertIsNone(result['in_flight'])
        self.assertEqual([0, 0, 0], result['executor_counters'])
        self.assertEqual(0, result['network_attempts'])
        self.assertIs(result['source_only_checkout'], True)
        self.assertIs(result['dont_write_bytecode_flag'], True)
        self.assertEqual('_SourceOnlyLoader', result['checkout_loader'])
        for key, expected in self.initial_roots.items():
            self.assertEqual(expected, result[key])
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        artifact_dir = os.environ.get('NO_RELEASE_PROCESS_EVIDENCE_DIR')
        if artifact_dir is not None:
            root = Path(artifact_dir)
            self.assertTrue(root.is_absolute() and root.is_dir() and not root.is_symlink())
            artifact = root / (self._testMethodName + '.json')
            payload = {'schema': 'nz13.no-release.process-evidence.v1', 'case': self._testMethodName,
                'parent_pid': os.getpid(), 'original_roots': self.initial_roots, 'child_result': result,
                'flock_probe': getattr(self, 'flock_probe', None), 'fixture_only': True,
                'copied_host_credentials': False, 'remote_operations': 0}
            descriptor = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, indent=2)
                stream.write('\n')
        return result

    def test_new_exec_reconciles_sqlite_after_old_core_and_runner_are_closed(self):
        self.reference.start_lost()
        self.f.base.runner.close()
        self.f.base.core.close()
        child = self.process()
        stdout, stderr = child.communicate(self.payload('reconcile'), timeout=30)
        self.read_result(child, stdout, stderr)

    def test_old_outer_guard_physically_blocks_fresh_process_until_original_lifetime_ends(self):
        with self.f.adapter.target_guard():
            self.reference.start_lost()
            child = self.process()
            child.stdin.write(self.payload('blocked_then_reconcile'))
            child.stdin.flush()
            ready, _, _ = select.select([child.stdout], [], [], 15)
            self.assertEqual([child.stdout], ready, 'CHILD_DID_NOT_REACH_ACTUAL_FLOCK_PROBE')
            event = json.loads(child.stdout.readline())
            self.assertEqual({'event': 'fresh_descriptor_lock_probe', 'blocked': True}, event)
            self.flock_probe = event
            self.assertIsNone(child.poll())
            self.assertEqual(0, self.f.head()[1]['generation'])
            self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        stdout, stderr = child.communicate(timeout=30)
        self.read_result(child, stdout, stderr)

    def test_committed_no_release_ack_loss_is_inspected_in_new_exec_without_another_settlement(self):
        self.reference.start_lost()
        commit = LocalCoreTransaction.commit
        lost = []
        def lose_final_ack(tx):
            row = tx.get(RecordKind.OPERATION, self.f.port.head_key)
            selected = row is not None and row.payload['generation'] == 1 and row.payload['in_flight'] is None
            commit(tx)
            if selected and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', new=lose_final_ack), \
                self.assertRaises(CommitOutcomeUnknown):
            self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.assertEqual([True], lost)
        self.f.base.runner.close()
        self.f.base.core.close()
        child = self.process()
        stdout, stderr = child.communicate(self.payload('inspect'), timeout=30)
        self.read_result(child, stdout, stderr)
