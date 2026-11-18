"""Finite actual Native startup conformance; no implicit fixture or authority."""
import hashlib
import json
import unittest

FIXTURE_FACTORY = None


class NativeStartupAcceptance(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(FIXTURE_FACTORY), 'EXPLICIT_OWNED_STARTUP_FIXTURE_REQUIRED')
        self.fx = FIXTURE_FACTORY(self)

    def _read(self, reference):
        from pathlib import Path

        raw = self.fx.context['safe'].read(Path(reference['path']), maximum=4 * 1024 * 1024)
        self.assertEqual((reference['bytes'], reference['sha256']),
                         (len(raw), hashlib.sha256(raw).hexdigest()))
        return json.loads(raw)

    def _old_history(self, before):
        old = self._read(self.fx.handoff['old_business'])
        self.assertTrue(all(value == before['business_rows'].get(key)
                            for key, value in old['business_rows'].items()))
        self.assertEqual(3, len(set(before['business_rows']) - set(old['business_rows'])))
        for field in ('governor', 'jobs', 'target', 'coding'):
            self.assertEqual(old[field], before[field])
        self.assertEqual(old['audit_events'], before['audit_events'][:-1])

    def test_normal_main_optin_signed_readiness_preserves_unbound(self):
        observed = self.fx.normal_main_startup_observation(self)
        before, after = (self._read(observed['snapshots'][name]) for name in ('before', 'after'))
        cold = self._read(observed['snapshots']['before_auth'])
        self._old_history(cold)
        self.assertTrue(all(value == before['rows'].get(key) for key, value in cold['rows'].items()),
                        'NATIVE_MAIN_AUTH_MUST_PRESERVE_OLD_ROWS')
        for field in ('governor', 'jobs', 'target', 'coding'):
            self.assertEqual(cold[field], before[field])
        self.assertEqual(before, after, 'NATIVE_MAIN_READINESS_READ_MUST_NOT_WRITE')
        self.assertTrue(observed['native_cli_tail_present_in_actual_orig_argv'])
        self.assertEqual('CAPACITY_ADMIN', observed['phase_before'])
        self.assertEqual(observed['phase_before'], observed['phase_after'])
        self.assertNotEqual(observed['old_instance_id'], observed['instance_id'])
        self.assertEqual(self.fx.handoff['old_source'], observed['source'])
        self.assertEqual(observed['source'], observed['source_after'])
        self.assertEqual(self.fx.handoff['identity_spki_sha256'], observed['identity_spki_sha256'])
        self.assertEqual(self.fx.handoff['host_config'], observed['actual_host_spec'])
        self.assertTrue(observed['actual_offline_candidates_none'])
        self.assertTrue(observed['actual_coding_tasks_none'])
        self.assertTrue(observed['tls_verified'])
        self.assertTrue(observed['client_returned'])
        self.assertEqual(0, observed['model_calls'])
        self.assertEqual(200, observed['http']['devices']['status'])
        self.assertEqual(['Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/'],
                         observed['http']['devices']['cookie_flags'])
        self.assertEqual({'status': 200, 'coding_profile': False, 'csrf_present': True},
                         observed['http']['session'])
        self.assertEqual(403, observed['http']['delivery_replay_status'])
        response = observed['http']['readiness']
        if response['status'] != 200:
            self.assertEqual(403, response['status'], 'UNEXPECTED_NATIVE_MAIN_HTTP_STATUS')
            self.assertEqual('NATIVE_ROUTE_DENIED', response['body']['error'],
                             'UNEXPECTED_NATIVE_MAIN_HTTP_DENIAL')
        self.assertEqual(200, response['status'], 'NATIVE_NORMAL_MAIN_SIGNED_READINESS_UNWIRED')
        self.assertTrue(observed['readiness_signature_verified'])
        value = response['body']['observation']
        self.assertEqual('aioa.native-startup-observation.v1', value['schema'])
        self.assertEqual('NONE', value['authority'])
        self.assertEqual('NOT_CERTIFIED', value['model_certification'])
        self.assertEqual(observed['actual_pid'], value['pid'])
        self.assertEqual(observed['actual_orig_argv_sha256'], value['process']['argv_digest'])
        self.assertTrue(value['process']['isolated'])
        self.assertTrue(value['process']['dont_write_bytecode'])
        self.assertEqual(self.fx.origin, value['origin'])
        self.assertEqual(observed['actual_host_spec_digest'], value['composition_digest'])
        self.assertEqual(value['composition_digest'], value['startup_config_digest'])
        self.assertEqual('CAPACITY_ADMIN', value['admission']['phase'])
        self.assertEqual('FIXTURE_OS_ADMISSION', value['admission']['method'])
        self.assertEqual('UNBOUND', value['coding_state'])
        self.assertEqual('UNBOUND', value['portable_state'])
        self.assertEqual('UNBOUND', value['safe_effective_config']['worker'])
        self.assertEqual(0, value['safe_effective_config']['model_calls'])
        self.assertEqual('DISABLED', value['safe_effective_config']['external'])
        self.assertEqual('DISABLED', value['safe_effective_config']['aws'])
        self.assertEqual('OFF', value['safe_effective_config']['guest_network'])
        self.assertIs(False, value['safe_effective_config']['automatic_retry'])
        self.assertTrue(value['tls']['qualified'])

    def test_owned_tls_recover_in_capacity_admin_requires_control(self):
        observed, before, after = self.fx.http_recover_startup_observation(self)
        self._old_history(before)
        self.assertEqual('CAPACITY_ADMIN', observed['phase_before'])
        self.assertEqual(observed['phase_before'], observed['phase_after'])
        self.assertTrue(observed['same_core'] and observed['same_coding_tasks'])
        self.assertNotEqual(observed['old_instance_id'], observed['instance_id'])
        self.assertEqual(observed['old_source'], observed['source'])
        self.assertEqual(observed['source'], observed['source_after'])
        self.assertEqual([], observed['jobs'])
        for field in ('model_calls', 'active_count', 'effects', 'owned_work'):
            self.assertEqual(0, observed[field])
        for field in ('status', 'receipts'):
            self.assertEqual(200, observed['http'][field]['status'])
            self.assertEqual('RUNNING', observed['http'][field]['body']['state'])
        response = observed['http']['recover']
        if response['status'] != 200:
            self.assertEqual(403, response['status'], 'UNEXPECTED_NATIVE_RECOVER_HTTP_STATUS')
            self.assertEqual('CORE_ADMISSION_DENIED', response['body']['error'],
                             'UNEXPECTED_NATIVE_RECOVER_HTTP_DENIAL')
            self.assertEqual(before, after, 'DENIED_NATIVE_HTTP_RECOVER_WROTE_HISTORY')
        self.assertEqual(200, response['status'], 'NATIVE_HTTP_RECOVER_REQUIRES_CONTROL_CAPTURE')
        self.assertEqual('UNKNOWN', response['body']['state'])
        self.assertEqual('UNKNOWN', after['coding'][observed['task_id']]['state'])
        for field in ('governor', 'jobs', 'target'):
            self.assertEqual(before[field], after[field])
        key = observed['coding_identity']
        old_rows, new_rows = before['rows'], after['rows']
        changed = {name for name in old_rows if old_rows[name] != new_rows.get(name)}
        added = set(new_rows) - set(old_rows)
        self.assertEqual({key}, changed)
        self.assertEqual(2, len(added))
        self.assertEqual({'audit', 'outbox'}, {name.partition(':')[0] for name in added})
        self.assertEqual(old_rows[key]['revision'] + 1, new_rows[key]['revision'])
        old_receipts = old_rows[key]['payload']['receipts']
        new_receipts = new_rows[key]['payload']['receipts']
        self.assertEqual(old_receipts, new_receipts[:-1])
        self.assertEqual('UNKNOWN', new_receipts[-1]['receipt']['state'])
        self.assertEqual(before['audit_events'], after['audit_events'][:-1])
        audit = after['audit_bindings'][-1]
        self.assertEqual('CODING_INTAKE', audit['event_type'])
        self.assertEqual(key.partition(':')[2], audit['resource'])
        self.assertEqual(('RUNNING', 'UNKNOWN'), (audit['state_before'], audit['state_after']))
        self.assertEqual(new_rows[key]['payload_digest'], audit['content_hashes']['content'])
        outbox = new_rows[next(name for name in added if name.startswith('outbox:'))]['payload']
        self.assertEqual(audit['id'], outbox['event_id'])
        self.assertEqual(audit['event_hash'], outbox['event_digest'])
