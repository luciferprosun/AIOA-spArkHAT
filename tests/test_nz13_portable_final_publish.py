"""Offline SQLite regressions for the canonical staged Portable write.

These deterministic fixture clocks are simulation coverage, not Native OS or
physical TTL qualification. Native real-clock coverage is a separate driver.
"""
import copy
import json
import os
import pickle
import stat
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import test_nz13_portable_core_route as route_fixture
from nonzero_cloudops.adapters import portable
from nonzero_cloudops.state import files

from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import _IN_TRANSACTION, LocalCoreTransaction
from runtime.mission.portable_target import CorePortableWriteRelease
from runtime.mission.warrant import WarrantError


class PortableFinalPublishTests(unittest.TestCase):
    def setUp(self):
        self.f = route_fixture.PortableCoreRouteTests(
            'test_actual_owned_mutation_and_complete_readback_use_one_existing_core_and_executor')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def _during_staging(self, change):
        f = self.f
        original = os.fsync
        calls = []
        def boundary(descriptor):
            info = os.fstat(descriptor)
            name = Path(os.readlink('/proc/self/fd/' + str(descriptor)))
            if (stat.S_ISREG(info.st_mode) and name.parent == f.path.parent
                    and name.name.startswith('.' + f.path.name + '.') and name.suffix == '.tmp'):
                self.assertFalse(_IN_TRANSACTION.get())
                calls.append(str(name))
                self.assertEqual(1, len(calls))
                change()
            return original(descriptor)
        with patch.object(files.os, 'fsync', new=boundary):
            result = f.dispatch()
        self.assertEqual(1, len(calls))
        self.assertFalse(Path(calls[0]).exists())
        return result

    def _assert_released_unknown_without_effect(self, result):
        f = self.f
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertEqual(f.before_bytes, f.path.read_bytes())
        self.assertEqual((1, 0, 0), f.executor.counters())
        head = f.head()[1]
        self.assertEqual('RELEASED', head['in_flight']['phase'])
        self.assertIsNotNone(head['in_flight']['write_observation'])
        self.assertIsNone(head['in_flight']['ack'])
        f.unknown()
        before = f.base.records()
        with self.assertRaisesRegex(WarrantError, '^INDEPENDENT_READBACK_UNAVAILABLE$'):
            f.route.reconcile(f.p(), f.warrant, 1)
        self.assertEqual(before, f.base.records())

    def test_claim_expiry_inside_staging_fsync_keeps_unknown_without_effect(self):
        result = self._during_staging(lambda: setattr(self.f.base.gov, 'clock', lambda: 131))
        self._assert_released_unknown_without_effect(result)

    def test_stop_inside_staging_fsync_keeps_unknown_without_effect(self):
        result = self._during_staging(
            lambda: self.f.base.gov.set_kill(self.f.p(Capability.MANAGE), True))
        self._assert_released_unknown_without_effect(result)

    def test_session_revoke_inside_staging_fsync_keeps_unknown_without_effect(self):
        result = self._during_staging(
            lambda: self.f.route.revoke_session(self.f.p(Capability.MANAGE), self.f.session_id))
        self._assert_released_unknown_without_effect(result)

    def test_warrant_revoke_inside_staging_fsync_keeps_unknown_without_effect(self):
        result = self._during_staging(
            lambda: self.f.base.ledger.revoke(self.f.p(Capability.OWNER_APPROVAL), self.f.warrant))
        self._assert_released_unknown_without_effect(result)

    def test_valid_staging_publishes_once_and_fresh_route_reads_applied(self):
        result = self._during_staging(lambda: None)
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), self.f.executor.counters())
        fresh = self.f.make_route()
        self.assertEqual('Applied', fresh.reconcile(self.f.p(), self.f.warrant, 1)['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_same_ack_cannot_publish_twice_within_its_live_scope(self):
        original = CorePortableWriteRelease.publish_write_ack
        denied = []
        def once(release, *args):
            value = original(release, *args)
            with self.assertRaisesRegex(WarrantError, '^PORTABLE_TERMINAL_WRITE_BINDING$'):
                original(release, *args)
            denied.append(True)
            return value
        with patch.object(CorePortableWriteRelease, 'publish_write_ack', new=once):
            self.f.dispatch()
        self.assertEqual([True], denied)
        self.assertEqual((1, 1, 0), self.f.executor.counters())
        self.assertEqual('Applied', self.f.route.reconcile(
            self.f.p(), self.f.warrant, 1)['outcome']['contract_type'])

    def test_untyped_staging_cannot_grant_publication(self):
        original = CorePortableWriteRelease.publish_write_ack
        def invalid(release, ack, store, before, candidate, staged):
            return original(release, ack, store, before, candidate, {'ready': True})
        with patch.object(CorePortableWriteRelease, 'publish_write_ack', new=invalid):
            result = self.f.dispatch()
        self._assert_released_unknown_without_effect(result)

    def test_terminal_sql_retry_has_no_file_io_and_publishes_only_once(self):
        f = self.f
        original_publish = CorePortableWriteRelease.publish_write_ack
        original_commit = LocalCoreTransaction.commit
        original_fsync, original_replace = os.fsync, os.replace
        inside_publish, conflicts, effects = [], [], []
        class Retry(Exception):
            sqlstate = '40001'
        def publish(release, *args):
            inside_publish.append(True)
            try:
                return original_publish(release, *args)
            finally:
                inside_publish.pop()
        def commit(tx):
            if inside_publish and not conflicts:
                conflicts.append(True)
                raise Retry()
            return original_commit(tx)
        def fsync(descriptor):
            self.assertFalse(_IN_TRANSACTION.get(), 'STAGING_OR_PUBLICATION_FSYNC_INSIDE_SQL')
            return original_fsync(descriptor)
        def replace(source, target, *args, **kwargs):
            self.assertFalse(_IN_TRANSACTION.get(), 'PUBLICATION_REPLACE_INSIDE_SQL')
            if Path(target) == f.path:
                effects.append(True)
            return original_replace(source, target, *args, **kwargs)
        with (patch.object(CorePortableWriteRelease, 'publish_write_ack', new=publish),
                patch.object(LocalCoreTransaction, 'commit', new=commit),
                patch.object(files.os, 'fsync', new=fsync),
                patch.object(files.os, 'replace', new=replace)):
            result = f.dispatch()
        self.assertEqual([True], conflicts)
        self.assertEqual([True], effects)
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), f.executor.counters())
        self.assertEqual('Applied', f.route.reconcile(f.p(), f.warrant, 1)['outcome']['contract_type'])

    def test_lost_ack_after_directory_fsync_retains_effect_until_fresh_readback(self):
        f = self.f
        original = os.fsync
        lost = []
        def fsync(descriptor):
            info = os.fstat(descriptor)
            name = Path(os.readlink('/proc/self/fd/' + str(descriptor)))
            value = original(descriptor)
            if stat.S_ISDIR(info.st_mode) and name == f.path.parent:
                lost.append(True)
                raise OSError('CONTROLLED_ACK_LOSS_AFTER_DIRECTORY_FSYNC')
            return value
        with patch.object(files.os, 'fsync', new=fsync):
            result = f.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertNotEqual(f.before_bytes, f.path.read_bytes())
        self.assertIsNone(f.head()[1]['in_flight']['ack'])
        f.unknown()
        fresh = f.make_route()
        self.assertEqual('Applied', fresh.reconcile(f.p(), f.warrant, 1)['outcome']['contract_type'])
        self.assertEqual(1, f.head()[1]['generation'])

    def test_stage_renders_the_single_immutable_snapshot_even_if_input_changes(self):
        path = self.f.base.path / 'immutable-stage-control.json'
        value = {'approved': ['original']}
        original = files.json.dumps
        changes = []
        def dumps(material, *args, **kwargs):
            raw = original(material, *args, **kwargs)
            if material is value:
                changes.append(True)
                value['approved'].append('late-mutation')
            return raw
        with (
            patch.object(files.json, 'dumps', new=dumps),
            files.staged_private_json(path, value) as staged,
        ):
            self.assertEqual({'approved': ['original']}, json.loads(staged.canonical_value))
            staged.require_ready(path)
            staged.publish()
        self.assertEqual([True], changes)
        self.assertEqual({'approved': ['original']}, files.read_private_json(path))
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_changed_staged_file_after_terminal_sql_is_not_published(self):
        f = self.f
        original = f.route._legacy_run
        changed = []
        def after_sql(principal, purpose, callback):
            result = original(principal, purpose, callback)
            if callback.__name__ == 'terminal_state':
                self.assertFalse(_IN_TRANSACTION.get())
                paths = list(f.path.parent.glob('.' + f.path.name + '.*.tmp'))
                self.assertEqual(1, len(paths))
                paths[0].write_bytes(b'{"substituted":true}\n')
                changed.append(str(paths[0]))
            return result
        with patch.object(f.route, '_legacy_run', new=after_sql):
            result = f.dispatch()
        self.assertEqual(1, len(changed))
        self.assertFalse(Path(changed[0]).exists())
        self._assert_released_unknown_without_effect(result)

    def test_changed_named_guard_after_terminal_sql_prevents_physical_write(self):
        f = self.f
        original = f.route._legacy_run
        changed = []
        def after_sql(principal, purpose, callback):
            result = original(principal, purpose, callback)
            if callback.__name__ == 'terminal_state':
                self.assertFalse(_IN_TRANSACTION.get())
                replacement = f.path.parent / 'replacement-private-fixture.lock'
                replacement.write_bytes(b'')
                replacement.chmod(0o600)
                os.replace(replacement, f.path.with_name(f.path.name + '.lock'))
                changed.append(True)
            return result
        with (patch.object(f.route, '_legacy_run', new=after_sql),
                self.assertRaises(portable.CloudAdapterUnavailableError)):
            f.dispatch()
        self.assertEqual([True], changed)
        self.assertEqual(f.before_bytes, f.path.read_bytes())
        self.assertEqual((1, 0, 0), f.executor.counters())
        self.assertEqual('RELEASED', f.head()[1]['in_flight']['phase'])
        self.assertIsNone(f.head()[1]['in_flight']['ack'])

    def test_stage_copy_pickle_and_foreign_thread_cannot_steal_cleanup(self):
        path = self.f.base.path / 'owned-stage-control.json'
        with files.staged_private_json(path, {'approved': True}) as staged:
            for copier in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.subTest(copier=copier.__name__), self.assertRaises(TypeError):
                    copier(staged)
            failures = []
            def foreign_cleanup():
                try:
                    staged.close()
                except files.StateIntegrityError as error:
                    failures.append(str(error))
            child = threading.Thread(target=foreign_cleanup)
            child.start()
            child.join(timeout=2)
            self.assertFalse(child.is_alive())
            self.assertEqual(['local staged cleanup owner changed'], failures)
            staged.require_ready(path)
            staged.publish()
        self.assertEqual({'approved': True}, files.read_private_json(path))

    def test_policy4_lost_directory_fsync_ack_reconciles_in_fresh_exec_then_inspects(self):
        import hashlib
        import subprocess
        import sys
        from dataclasses import asdict

        from nonzero_cloudops.models import LocalExecutionReceipt

        from runtime.memory_patch.contracts.serialization import canonical_sha256

        f = self.f
        helper = Path(__file__).with_name('nz13_no_release_process_r2.py')
        helper_sha = 'c6ed065ba1201653a38fbfd7a7df71879a1d3d6026a13ca113459bfb3468b5ae'
        self.assertEqual(helper_sha, hashlib.sha256(helper.read_bytes()).hexdigest())
        source_loader = helper.with_name('nz13_source_only_imports.py')
        self.assertEqual(
            '96343a70e27a780c40e975a275716045810a7ba22d73d46c1045727018e1105f',
            hashlib.sha256(source_loader.read_bytes()).hexdigest())
        evidence_name = os.environ.get('NO_RELEASE_PROCESS_EVIDENCE_DIR')
        self.assertIsNotNone(evidence_name, 'PRIVATE_PROCESS_EVIDENCE_DIR_REQUIRED')
        evidence_root = Path(evidence_name)
        self.assertTrue(evidence_root.is_absolute() and evidence_root.is_dir()
                        and not evidence_root.is_symlink())
        metadata = evidence_root.stat()
        self.assertEqual(os.getuid(), metadata.st_uid)
        self.assertEqual(0, stat.S_IMODE(metadata.st_mode) & 0o077)
        artifact = evidence_root / (self._testMethodName + '.json')
        proof = {
            'schema': 'nz13.policy4.write-lost-ack-fresh-exec.v1',
            'case': self._testMethodName, 'parent_pid': os.getpid(),
            'fixture_only': True, 'qualification': False,
            'copied_host_credentials': False, 'remote_operations': 0,
            'helper_sha256': helper_sha, 'children': [], 'phase': 'INITIAL',
        }
        original_fsync = os.fsync
        lost = []

        def fsync(descriptor):
            info = os.fstat(descriptor)
            name = Path(os.readlink('/proc/self/fd/' + str(descriptor)))
            result = original_fsync(descriptor)
            if stat.S_ISDIR(info.st_mode) and name == f.path.parent:
                self.assertFalse(_IN_TRANSACTION.get())
                lost.append(True)
                raise OSError('CONTROLLED_POLICY4_ACK_LOSS_AFTER_DIRECTORY_FSYNC')
            return result

        def fresh(mode):
            binding = asdict(f.port.binding)
            del binding['scope']
            request = json.dumps({
                'root': str(f.base.path), 'binding': binding,
                'warrant': f.warrant.to_dict(), 'mode': mode,
            }) + '\n'
            environment = {
                'PATH': '/usr/bin:/bin', 'HOME': str(f.base.path),
                'TMPDIR': os.environ['TMPDIR'], 'LANG': 'C.UTF-8',
                'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
            }
            argv = [sys.executable, '-I', '-B', str(helper)]
            child = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', cwd=f.base.path, env=environment, close_fds=True)
            observed = {'mode': mode, 'pid': child.pid, 'argv': argv,
                        'environment_keys': sorted(environment), 'reaped': False}
            proof['children'].append(observed)
            try:
                stdout, stderr = child.communicate(request, timeout=30)
                observed.update(returncode=child.returncode, reaped=child.returncode is not None,
                                stdout=stdout, stderr=stderr[-3000:])
                self.assertEqual(0, child.returncode, stderr[-3000:])
                lines = [json.loads(line) for line in stdout.splitlines() if line]
                self.assertEqual(1, len(lines))
                result = lines[0]
                observed['result'] = result
                self.assertEqual('result', result['event'])
                self.assertEqual(child.pid, result['pid'])
                self.assertNotEqual(os.getpid(), result['pid'])
                self.assertEqual('Applied', result['outcome'])
                self.assertEqual('NONE', result['authority'])
                self.assertIs(False, result['grants_replay'])
                self.assertEqual([0, 0, 0], result['executor_counters'])
                self.assertEqual(0, result['network_attempts'])
                self.assertTrue(result['source_only_checkout'])
                self.assertTrue(result['dont_write_bytecode_flag'])
                self.assertEqual('_SourceOnlyLoader', result['checkout_loader'])
                self.assertIsNone(result['in_flight'])
                self.assertEqual(expected_generation, result['generation'])
                self.assertEqual(expected_revision, result['head_revision'])
                for key, expected in expected_roots.items():
                    self.assertEqual(expected, result[key])
                self.assertEqual(after_bytes, f.path.read_bytes())
                payload, _ = files.open_local_payload(
                    files.read_private_json(f.path), payload_type='AIOA_SANDBOX_INVENTORY')
                self.assertEqual(after_payload, payload)
                self.assertEqual(receipt_data, {
                    item['idempotency_key']: item for item in payload['receipts']
                }[receipt.idempotency_key])
                return result
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                observed['reaped'] = child.returncode is not None
                observed['returncode'] = child.returncode
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()

        try:
            before_payload, _ = files.open_local_payload(
                files.read_private_json(f.path), payload_type='AIOA_SANDBOX_INVENTORY')
            with patch.object(files.os, 'fsync', new=fsync):
                dispatched = f.dispatch()
            self.assertEqual([True], lost)
            self.assertEqual('Unknown', dispatched['outcome']['contract_type'])
            after_bytes = f.path.read_bytes()
            self.assertNotEqual(f.before_bytes, after_bytes)
            row, head = f.head()
            self.assertEqual('RELEASED', head['in_flight']['phase'])
            self.assertIsNone(head['in_flight']['ack'])
            f.unknown()
            after_payload, _ = files.open_local_payload(
                files.read_private_json(f.path), payload_type='AIOA_SANDBOX_INVENTORY')
            before_receipts = {item['idempotency_key']: item for item in before_payload['receipts']}
            after_receipts = {item['idempotency_key']: item for item in after_payload['receipts']}
            added = set(after_receipts) - set(before_receipts)
            self.assertEqual(1, len(added))
            for key, previous in before_receipts.items():
                self.assertEqual(previous, after_receipts[key])
            receipt_data = after_receipts[next(iter(added))]
            receipt = LocalExecutionReceipt.model_validate(receipt_data)
            write = head['in_flight']['write_observation']
            self.assertEqual(f.warrant.digest(), write['warrant_digest'])
            self.assertEqual(f.warrant.operation_hash, write['operation_digest'])
            self.assertEqual(receipt.receipt_hash, write['receipt_digest'])
            self.assertEqual(canonical_sha256(receipt.idempotency_key), write['receipt_key_digest'])
            with f.store.target_guard():
                observation = f.store.observe_guarded_inventory()
            expected_roots = {key: getattr(observation, key)
                              for key in ('state_root', 'resources_root', 'receipts_root')}
            self.assertEqual(write['after_root'], expected_roots['state_root'])
            self.assertEqual(write['resources_root'], expected_roots['resources_root'])
            self.assertEqual(write['receipts_root'], expected_roots['receipts_root'])
            expected_generation, expected_revision = head['generation'] + 1, row.revision + 1
            proof.update(
                phase='PHYSICAL_WRITE_AND_UNKNOWN_CAPTURED', dispatch=dispatched,
                before_inventory_sha256=hashlib.sha256(f.before_bytes).hexdigest(),
                after_inventory_sha256=hashlib.sha256(after_bytes).hexdigest(),
                receipt=receipt_data, write_observation=write, expected_roots=expected_roots,
                expected_generation=expected_generation, expected_head_revision=expected_revision,
                parent_executor_counters=list(f.executor.counters()),
                parent_head_before_restart=head, parent_head_revision=row.revision)
            f.base.runner.close()
            f.base.core.close()
            proof['old_runner_and_core_closed'] = True
            first = fresh('reconcile')
            second = fresh('inspect')
            self.assertNotEqual(first['pid'], second['pid'])
            self.assertEqual(
                {key: value for key, value in first.items() if key != 'pid'},
                {key: value for key, value in second.items() if key != 'pid'})
            self.assertEqual(after_bytes, f.path.read_bytes())
            self.assertEqual(2, len(proof['children']))
            self.assertTrue(all(item['reaped'] for item in proof['children']))
            proof['phase'] = 'COMPLETE'
        except BaseException as error:
            proof['failure'] = {'type': type(error).__name__, 'code': str(error)}
            raise
        finally:
            raw = (json.dumps(proof, sort_keys=True, indent=2) + '\n').encode()
            descriptor = os.open(
                artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
