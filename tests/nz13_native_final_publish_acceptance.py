"""Explicit Native staging-boundary regressions; never ordinary discovery.

Uses the existing owned fixture factory. Synthetic OS admission and zero model
calls do not qualify a production Native target or a kernel-enforced write TTL.
"""
import hashlib
import json
import os
import stat
import time
import unittest
from contextlib import ExitStack, contextmanager
from functools import wraps
from pathlib import Path
from unittest.mock import patch

import nz13_native_coding_acceptance as acceptance
from nonzero_cloudops.state import files

from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
from runtime.mission.portable_target import CorePortableWriteRelease
from runtime.mission.warrant import WarrantError


class _PassiveNativeTiming:
    """Private fixture observations only; no permission, retries or decisions."""

    def __init__(self):
        self.events = []
        self.next_call = 0
        self.dropped = False
        self.recording_error = False

    def record(self, call_id, label, event, detail=None):
        # No serialization, filesystem access, source checks or Core calls here.
        try:
            if len(self.events) < 4096:
                self.events.append((call_id, label, event, time.time(), time.monotonic(), detail))
            else:
                self.dropped = True
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            # Observation must not replace a product result or exception.
            self.recording_error = True

    def invoke(self, label, original, *args, **kwargs):
        call_id = self.next_call
        self.next_call += 1
        self.record(call_id, label, 'enter')
        try:
            result = original(*args, **kwargs)
        except BaseException as error:
            self.record(call_id, label, 'exception', error)
            raise
        self.record(call_id, label, 'return', result)
        return result

    def materialize(self):
        # Called only after the observed method has unwound and hooks are restored.
        import traceback

        def error_detail(error):
            chain, seen = [], set()
            while error is not None and id(error) not in seen and len(chain) < 8:
                seen.add(id(error))
                chain.append({
                    'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error),
                    'frames': [
                        {'file': frame.filename, 'function': frame.name, 'line': frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__, limit=32)
                    ],
                })
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return chain

        values = []
        for call_id, label, event, wall, monotonic, detail in self.events:
            value = {'call_id': call_id, 'label': label, 'event': event,
                     'wall': wall, 'monotonic': monotonic}
            if event == 'exception':
                value['errors'] = error_detail(detail)
            elif event in ('return', 'staged_ready'):
                value['return_type'] = type(detail).__name__
                if label == 'governor.claim_job' and event == 'return':
                    value['claim'] = {
                        key: getattr(detail, key)
                        for key in ('task_id', 'worker_id', 'envelope_digest',
                                    'governor_epoch', 'fence', 'lease_until')
                    }
                elif label == 'governor.begin_job' and type(detail) is dict:
                    value['begin_result'] = {
                        key: detail[key] for key in ('state', 'local_step_now') if key in detail
                    }
                elif label == 'route.authorize_exact':
                    value['warrant_window'] = {
                        'issued_at': detail.issued_at.isoformat(),
                        'expires_at': detail.expires_at.isoformat(),
                    }
            values.append(value)
        return {
            'schema': 'nz13.passive-native-boundary-timing.v1',
            'authority': 'NONE', 'fixture_only': True, 'qualification': False,
            'clock_changed': False, 'TTL_changed': False,
            'snapshot_algorithm_changed': False, 'includes_observer_overhead': True,
            'event_limit': 4096, 'events_dropped': self.dropped,
            'recording_error': self.recording_error, 'events': values,
        }


def _native_fixture_timing(method):
    """Observe the original method once and save only after its critical scope."""
    @wraps(method)
    def measured(self, *args, **kwargs):
        from nonzero_cloudops.adapters import portable as portable_module

        fx, h, observer = self.fx, self.fx.host, _PassiveNativeTiming()
        route, store, foundation = h.portable_release_route, h.portable_store, h.foundation

        def ordinary(original, label):
            @wraps(original)
            def wrapped(*values, **named):
                return observer.invoke(label, original, *values, **named)
            return wrapped

        def transaction_scope(original, label):
            @wraps(original)
            def wrapped(principal, purpose, callback):
                # Callback metadata is DATA; pass the identical callback onward.
                name = getattr(callback, '__qualname__', type(callback).__name__)
                return observer.invoke(label + ':' + name, original, principal, purpose, callback)
            return wrapped

        original_staging = portable_module.staged_private_json
        @contextmanager
        def staged(*values, **named):
            call_id = observer.next_call
            observer.next_call += 1
            observer.record(call_id, 'storage.staging', 'enter')
            try:
                with original_staging(*values, **named) as value:
                    observer.record(call_id, 'storage.staging', 'staged_ready', value)
                    yield value
            except BaseException as error:
                observer.record(call_id, 'storage.staging', 'exception', error)
                raise
            finally:
                observer.record(call_id, 'storage.staging', 'scope_closed')

        try:
            with ExitStack() as patches:
                for owner, name, label in (
                        (fx, '_portable_task', 'fixture.task_creation'),
                        (foundation.governor, 'claim_job', 'governor.claim_job'),
                        (foundation.governor, 'begin_job', 'governor.begin_job'),
                        (route, 'create_session', 'route.create_session'),
                        (route, 'authorize_exact', 'route.authorize_exact'),
                        (fx, '_portable_no_release_snapshot', 'fixture.full_snapshot'),
                        (route, '_retained', 'route.retained'),
                        (route, '_probe_target', 'route.probe'),
                        (route, '_check', 'route.check'),
                        (route, '_native_job', 'route.native_job'),
                        (foundation.access, 'capture', 'native.capture'),
                        (CorePortableWriteRelease, 'authorize_write', 'release.authorize_write'),
                        (CorePortableWriteRelease, 'consume_write_ack', 'release.consume_write_ack'),
                        (CorePortableWriteRelease, '_consume_write_ack', 'release.consume_ack_inner'),
                        (CorePortableWriteRelease, 'publish_write_ack', 'release.terminal_publication'),
                        (type(store), '_check_target_guard', 'storage.guard_identity'),
                        (files._StagedPrivateJson, 'require_ready', 'storage.stage_identity'),
                        (files._StagedPrivateJson, 'publish', 'storage.publish')):
                    original = getattr(owner, name)
                    patches.enter_context(patch.object(owner, name, new=ordinary(original, label)))
                for name in ('_run', '_legacy_run'):
                    original = getattr(route, name)
                    patches.enter_context(patch.object(
                        route, name, new=transaction_scope(original, 'route.' + name)))
                patches.enter_context(patch.object(
                    portable_module, 'staged_private_json', new=staged))
                return observer.invoke('fixture.' + method.__name__, method, self, *args, **kwargs)
        finally:
            # Product callbacks, transactions and the measured test have unwound.
            # Saving telemetry must never replace their original return/exception.
            try:
                payload = observer.materialize()
                payload['case'] = self._testMethodName
                fx.retained['passive_native_timing'] = fx.legacy_capacity_save(
                    'native-passive-timing-' + self._testMethodName + '.json', payload)
            except BaseException as error:
                if not isinstance(error, Exception):
                    raise
                fx.retained['passive_native_timing_save_error'] = {
                    'type': type(error).__name__, 'code': str(error),
                    'measurement_qualified': False,
                }
    return measured


@contextmanager
def deferred_before_snapshot_save(fx, basename):
    """Keep the exact immutable snapshot and defer only its slow artifact write."""
    original = fx.legacy_capacity_save
    pending = []
    def flush():
        while pending:
            name, raw, reference = pending[0]
            result = original(name, json.loads(raw))
            reference.clear()
            reference.update(result)
            pending.pop(0)
    def save(name, value):
        if name == basename:
            if pending:
                raise AssertionError('DUPLICATE_DEFERRED_BEFORE_SNAPSHOT')
            raw = json.dumps(value, sort_keys=True).encode()
            reference = {'pending_snapshot_write': True,
                         'immutable_snapshot_sha256': hashlib.sha256(raw).hexdigest()}
            pending.append((name, raw, reference))
            return reference
        # The next artifact is written after the critical dispatch/observation.
        flush()
        return original(name, value)
    try:
        with patch.object(fx, 'legacy_capacity_save', new=save):
            yield
    finally:
        flush()


class NativeFinalPublishAcceptance(unittest.TestCase):
    def setUp(self):
        acceptance.NativeOwnedAcceptance.setUp(self)

    @_native_fixture_timing
    def _at_staging(self, scenario):
        fx, h, f = self.fx, self.host, self.host.foundation
        managed, store = h._native_coding, h.portable_store
        proof = {
            'schema': 'nz13.native-portable-staged-publication.v1',
            'scenario': scenario, 'fixture_scope': 'FIXTURE_OS_ADMISSION',
            'qualification': False, 'model_certification': 'NOT_CERTIFIED',
            'claim_lease_seconds': 12, 'session_lease_seconds': 60,
            'clock_monkeypatch': False, 'real_wait_bound_seconds': 14,
            'snapshots': {}, 'cuts': [], 'dispatch_calls': 0,
            'replace_calls': 0, 'directory_fsync_calls': 0,
        }
        selected, tasks = {}, []
        original_consume = CorePortableWriteRelease.consume_write_ack
        original_fsync, original_replace = os.fsync, os.replace
        original_publish = CorePortableWriteRelease.publish_write_ack
        pending_snapshots = {}
        selected_name = None

        def flush_snapshots():
            for name, raw in list(pending_snapshots.items()):
                proof['snapshots'][name] = fx.legacy_capacity_save(
                    'portable-staged-' + scenario.lower() + '-' + name + '.json', json.loads(raw))
                del pending_snapshots[name]

        def snapshot(name):
            value = fx._portable_no_release_snapshot(tasks)
            if name == 'before-dispatch':
                # Preserve the complete observed snapshot, without fsync in the live TTL window.
                pending_snapshots[name] = json.dumps(value, sort_keys=True).encode()
                proof['snapshots'][name] = {
                    'pending_snapshot_write': True,
                    'immutable_snapshot_sha256': hashlib.sha256(pending_snapshots[name]).hexdigest()}
            else:
                flush_snapshots()
                proof['snapshots'][name] = fx.legacy_capacity_save(
                    'portable-staged-' + scenario.lower() + '-' + name + '.json', value)
            return value

        def times(release):
            return {
                'wall': time.time(), 'monotonic': time.monotonic(),
                'claim_until': task['claim'].lease_until,
                'session_until': task['facts']['grant']['expires_at'],
                'warrant_until': task['warrant'].expires_at.timestamp(),
                'envelope_until': task['facts']['envelope']['deadline_at'],
                'principal_until': release.principal.expires_at.timestamp(),
                'TLS_until': h._tls_expires, 'TLS_verified': h.tls_verified,
                'auth_until': h._auth_deadline,
            }

        def other_deadlines(value):
            return (all(value['wall'] < value[name] for name in (
                'session_until', 'warrant_until', 'envelope_until',
                'principal_until', 'TLS_until'))
                and value['monotonic'] < value['auth_until']
                and value['TLS_verified'] is True)

        def consume(release, ack, actual_store, before, candidate):
            value = original_consume(release, ack, actual_store, before, candidate)
            if actual_store is store and release.warrant is task['warrant']:
                self.assertFalse(selected, 'STAGING_ACK_CONSUMED_MORE_THAN_ONCE')
                selected.update(release=release, ack=ack)
                proof['ACK_consumed'] = ack.consumed
                proof['release_consumed'] = release._consumed
            return value

        def cut():
            release = selected['release']
            value = {'entry': times(release), 'outside_SQL': not bool(_IN_TRANSACTION.get()),
                     'ACK_consumed': selected['ack'].consumed,
                     'write_observation': release._write_observation.to_dict(),
                     'executor_before': list(h.portable_executor.counters())}
            proof['cuts'].append(value)
            self.assertTrue(value['outside_SQL'])
            self.assertLess(value['entry']['wall'], task['claim'].lease_until,
                            'STAGING_FIXTURE_ALREADY_EXPIRED_BEFORE_CUT')
            self.assertTrue(other_deadlines(value['entry']), 'STAGING_FIXTURE_OTHER_AUTHORITY_EXPIRED')
            if scenario == 'CLAIM_EXPIRE':
                end = time.monotonic() + 14
                while time.time() < task['claim'].lease_until:
                    self.assertLess(time.monotonic(), end, 'STAGING_REAL_WAIT_BOUND')
                    time.sleep(min(0.025, max(0.001, task['claim'].lease_until - time.time())))
            elif scenario == 'STOP':
                with managed.authority(Capability.MANAGE) as principal:
                    f.governor.set_kill(principal, True)
            elif scenario == 'SESSION_REVOKE':
                with managed.authority(Capability.MANAGE) as principal:
                    task['route'].revoke_session(principal, task['session_id'])
            elif scenario == 'WARRANT_REVOKE':
                with managed.authority(Capability.OWNER_APPROVAL) as principal:
                    f.ledger.revoke(principal, task['warrant'])
            value['exit'] = times(release)
            value['executor_after'] = list(h.portable_executor.counters())
            self.assertTrue(other_deadlines(value['exit']), 'STAGING_FIXTURE_OTHER_AUTHORITY_EXPIRED')
            self.assertEqual(value['executor_before'], value['executor_after'])
            if scenario == 'CLAIM_EXPIRE':
                self.assertGreaterEqual(value['exit']['wall'], task['claim'].lease_until)
            else:
                self.assertLess(value['exit']['wall'], task['claim'].lease_until,
                                'STAGING_FIXTURE_CLAIM_EXPIRED_DURING_NONEXPIRY_CUT')

        def publish(release, *args):
            selected_gate = release.adapter is h.portable_target and release.warrant is task['warrant']
            if not selected_gate:
                return original_publish(release, *args)
            self.assertNotIn('terminal_gate', proof, 'MULTIPLE_TERMINAL_PUBLICATION_ATTEMPTS')
            gate = {'entry': times(release), 'returned': False}
            proof['terminal_gate'] = gate
            try:
                value = original_publish(release, *args)
                gate['returned'] = True
                return value
            except BaseException as error:
                gate['error'] = {'type': type(error).__name__, 'code': str(error)}
                raise
            finally:
                gate['exit'] = times(release)

        def fsync(descriptor):
            nonlocal selected_name
            info = os.fstat(descriptor)
            name = Path(os.readlink('/proc/self/fd/' + str(descriptor)))
            if (selected and stat.S_ISREG(info.st_mode) and name.parent == store.path.parent
                    and name.name.startswith('.' + store.path.name + '.') and name.suffix == '.tmp'):
                self.assertIsNone(selected_name, 'MORE_THAN_ONE_STAGING_FILE')
                selected_name = str(name)
                # The real fsync is delayed; both before and after it remain outside SQL.
                cut()
                proof['staging_fsync_entry'] = times(selected['release'])
                result = original_fsync(descriptor)
                proof['staging_fsync_returned'] = times(selected['release'])
                return result
            if selected and stat.S_ISDIR(info.st_mode) and name == store.path.parent:
                self.assertFalse(_IN_TRANSACTION.get(), 'PUBLISH_DIRECTORY_FSYNC_IN_SQL')
                proof['directory_fsync_calls'] += 1
                proof['directory_fsync_entry'] = times(selected['release'])
                result = original_fsync(descriptor)
                proof['directory_fsync_exit'] = times(selected['release'])
                if scenario == 'LOST_ACK':
                    proof['durable_directory_fsync_completed'] = True
                    raise OSError('CONTROLLED_ACK_LOSS_AFTER_DIRECTORY_FSYNC')
                return result
            return original_fsync(descriptor)

        def replace(source, target, *args, **kwargs):
            if Path(target) == store.path:
                self.assertFalse(_IN_TRANSACTION.get(), 'PUBLISH_REPLACE_IN_SQL')
                proof['replace_calls'] += 1
                self.assertEqual(1, proof['replace_calls'], 'DUPLICATE_PHYSICAL_PUBLICATION')
                proof['replace_entry'] = times(selected['release'])
                value = original_replace(source, target, *args, **kwargs)
                proof['replace_exit'] = times(selected['release'])
                return value
            return original_replace(source, target, *args, **kwargs)

        def dispatch():
            proof['dispatch_calls'] += 1
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].dispatch(
                    principal, session_id=task['session_id'], warrant=task['warrant'],
                    operation=task['operation'], reservation=task['reservation'],
                    completion=task['completion'])

        def reconcile():
            with managed.authority(Capability.READ) as principal:
                epoch = f.governor.inspect(principal)['epoch']
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].reconcile(principal, task['warrant'], epoch)

        try:
            snapshot('baseline')
            _, domain = fx._portable_a6_release_domain()
            task = fx._portable_task(4, domain, claim_lease_seconds=12, session_lease_seconds=60)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = snapshot('before-dispatch')
            with (patch.object(CorePortableWriteRelease, 'consume_write_ack', new=consume),
                    patch.object(files.os, 'fsync', new=fsync),
                    patch.object(files.os, 'replace', new=replace),
                    patch.object(CorePortableWriteRelease, 'publish_write_ack', new=publish)):
                proof['dispatch'] = dispatch()
                if not selected:
                    raise RuntimeError('STAGING_FIXTURE_DISPATCH_NEVER_REACHED_CONSUMED_ACK')
                proof['after_dispatch_time'] = times(selected['release'])
            if scenario == 'CLAIM_EXPIRE':
                self.assertTrue(other_deadlines(proof['after_dispatch_time']),
                                'STAGING_FIXTURE_OTHER_AUTHORITY_EXPIRED_BEFORE_DISPATCH_RETURN')
            elif scenario == 'STOP':
                gate = proof['terminal_gate']
                proof['post_denial_claim_expired'] = (
                    proof['after_dispatch_time']['wall'] >= task['claim'].lease_until)
                self.assertLess(gate['entry']['wall'], task['claim'].lease_until,
                                'STAGING_FIXTURE_CLAIM_EXPIRED_BEFORE_TERMINAL_ENTRY')
                self.assertLess(proof['terminal_gate']['exit']['wall'], task['claim'].lease_until,
                                'STAGING_FIXTURE_CLAIM_EXPIRED_BEFORE_TERMINAL_DENIAL')
                self.assertIs(gate['returned'], False)
                self.assertEqual({'type': 'WarrantError', 'code': 'KILL_SWITCH'}, gate['error'])
                self.assertLessEqual(proof['cuts'][0]['exit']['monotonic'],
                                     gate['entry']['monotonic'],
                                     'STAGING_STOP_CUT_TO_TERMINAL_ORDER')
                self.assertLessEqual(gate['entry']['monotonic'], gate['exit']['monotonic'],
                                     'STAGING_STOP_TERMINAL_ENTRY_EXIT_ORDER')
                self.assertLessEqual(gate['exit']['monotonic'],
                                     proof['after_dispatch_time']['monotonic'],
                                     'STAGING_STOP_TERMINAL_TO_DISPATCH_RETURN_ORDER')
                for value in (gate['entry'], gate['exit'], proof['after_dispatch_time']):
                    self.assertTrue(other_deadlines(value),
                                    'STAGING_STOP_OTHER_AUTHORITY_EXPIRED_AT_DENIAL_OR_RETURN')
            elif scenario in ('SESSION_REVOKE', 'WARRANT_REVOKE'):
                self.assertLess(proof['terminal_gate']['exit']['wall'], task['claim'].lease_until,
                                'STAGING_FIXTURE_CLAIM_EXPIRED_BEFORE_TERMINAL_DENIAL')
                self.assertLess(proof['after_dispatch_time']['wall'], task['claim'].lease_until,
                                'STAGING_FIXTURE_CLAIM_EXPIRED_BEFORE_DISPATCH_RETURN')
                reason = {'STOP': 'KILL_SWITCH', 'SESSION_REVOKE': 'SESSION_INACTIVE',
                          'WARRANT_REVOKE': 'WARRANT_REVOKED'}[scenario]
                self.assertEqual(reason, proof['terminal_gate']['error']['code'])
            after = snapshot('after-dispatch')
            effect_expected = scenario in ('VALID', 'LOST_ACK')
            try:
                proof['reconcile'] = {'returned': True, 'value': reconcile()}
            except WarrantError as error:
                proof['reconcile'] = {'returned': False, 'error': str(error)}
                if effect_expected or str(error) != 'INDEPENDENT_READBACK_UNAVAILABLE':
                    raise
            final = snapshot('after-independent-readback')
            proof['physical_delta'] = [a - b for a, b in zip(
                after['executor_counters'], before['executor_counters'], strict=True)]
            proof['phase'] = 'FACTS_CAPTURED_BEFORE_ASSERTIONS'
            fx.retained['portable_staged_' + scenario.lower()] = fx.legacy_capacity_save(
                'native-portable-staged-' + scenario.lower() + '-before-assertions-proof.json', proof)
            self.assertEqual(1, len(proof['cuts']))
            self.assertEqual(1, proof['dispatch_calls'])
            self.assertTrue(proof['ACK_consumed'])
            self.assertTrue(proof['release_consumed'])
            self.assertEqual('Unknown', proof['dispatch']['outcome']['contract_type'])
            self.assertIsNotNone(selected_name)
            self.assertFalse(Path(selected_name).exists(), 'STAGING_TEMP_NOT_CLEANED')
            self.assertFalse(getattr(selected['release'], '_active', True))
            self.assertIsNone(getattr(selected['release'], '_native_capture', None))
            for value in (before, after, final):
                self.assertTrue(value['full_rows_match_summary'])
            if effect_expected:
                self.assertEqual(1, proof['replace_calls'])
                self.assertNotEqual(before['physical'], after['physical'])
                self.assertTrue(proof['reconcile']['returned'])
                self.assertEqual('Applied', proof['reconcile']['value']['outcome']['contract_type'])
                self.assertIsNone(final['head']['in_flight'])
                self.assertEqual(before['head']['generation'] + 1, final['head']['generation'])
                self.assertEqual('COMMITTED', final['governor']['reservations'][
                    task['warrant'].risk_reservation_id]['state'])
                self.assertEqual(after['physical'], final['physical'])
                if scenario == 'VALID':
                    self.assertEqual([1, 1, 0], proof['physical_delta'])
                else:
                    self.assertTrue(proof['durable_directory_fsync_completed'])
                    self.assertIsNone(after['head']['in_flight']['ack'])
            else:
                self.assertEqual(0, proof['replace_calls'])
                self.assertEqual([1, 0, 0], proof['physical_delta'])
                self.assertEqual(before['physical'], after['physical'])
                self.assertEqual('RELEASED', after['head']['in_flight']['phase'])
                self.assertIsNotNone(after['head']['in_flight']['write_observation'])
                self.assertIsNone(after['head']['in_flight']['ack'])
                self.assertFalse(proof['reconcile']['returned'])
                self.assertEqual(after['full_canonical_rows'], final['full_canonical_rows'])
                self.assertEqual(after['physical'], final['physical'])
                self.assertEqual('UNKNOWN', final['governor']['reservations'][
                    task['warrant'].risk_reservation_id]['state'])
                self.assertIsNone(final['tasks'][task['task_id']]['job']['completion_proof'])
            if scenario == 'STOP':
                for observed in (after, final):
                    reservation = observed['governor']['reservations'][
                        task['warrant'].risk_reservation_id]
                    self.assertEqual((0, 5), (reservation['money_nano'], reservation['risk_units']))
                    joined = observed['tasks'][task['task_id']]
                    self.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
                    self.assertIsNone(joined['intent']['resolution'])
                    self.assertEqual({'OPEN'}, {
                        entry['record']['status']
                        for entry in joined['liability']['entries'].values()})
            self.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        except BaseException as error:
            proof['failure'] = {'type': type(error).__name__, 'code': str(error)}
            raise
        finally:
            flush_snapshots()
            fx.retained['portable_staged_' + scenario.lower()] = fx.legacy_capacity_save(
                'native-portable-staged-' + scenario.lower() + '-proof.json', proof)

    def test_valid_original_claim_publishes_once_after_staging(self):
        self._at_staging('VALID')

    def test_original_claim_expiry_inside_staging_fsync_blocks_publication(self):
        self._at_staging('CLAIM_EXPIRE')

    def test_stop_during_staging_blocks_publication_and_keeps_unknown(self):
        self._at_staging('STOP')

    def test_session_revocation_during_staging_blocks_publication(self):
        self._at_staging('SESSION_REVOKE')

    def test_warrant_revocation_during_staging_blocks_publication(self):
        self._at_staging('WARRANT_REVOKE')

    def test_ack_lost_after_durable_replace_reconciles_applied(self):
        self._at_staging('LOST_ACK')

    @_native_fixture_timing
    def test_historical_final_guard_with_deferred_before_snapshot(self):
        # Preserve the historical regression code and every snapshot byte.
        with deferred_before_snapshot_save(
                self.fx, 'portable-final-store-guard-before-dispatch.json'):
            self.fx.portable_claim_expiry_in_final_store_guard_assertions(self)
