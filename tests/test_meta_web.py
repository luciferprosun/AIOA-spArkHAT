"""Existing WebRuntimeService + real Core + fixture provider/browser."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import runtime  # Register the existing runtime import surface before webapp.
from webapp import WebRuntimeService, make_server


class MetaWebTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(WebRuntimeService, 'meta_request'), 'Meta routes not wired into existing web service')
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.host = OfflineMetaComposition(Path(self.tmp.name), delay_seconds=.15,
                                          source_probe=lambda: ('1'*40, 'a'*64))
        self.service = WebRuntimeService(runtime=self.host.runtime, meta_missions=self.host.missions,
                                        meta_owner=self.host)
        self.server = make_server('127.0.0.1', 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.token = self.request('GET', '/api/session', token=False)[1]['token']

    def tearDown(self):
        if hasattr(self, 'server'):
            self.server.shutdown(); self.server.server_close(); self.thread.join(2)
            self.service.close()

    def request(self, method, path, payload=None, *, token=True, intent=None, **headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json', **headers}
        if token: headers['X-AIOA-Session-Token'] = self.token
        if intent: headers['X-AIOA-Intent'] = intent
        conn.request(method, path, None if payload is None else json.dumps(payload), headers)
        response = conn.getresponse(); raw = response.read(); conn.close()
        return response.status, json.loads(raw)

    def preview(self, **changes):
        status, result = self.request('POST', '/api/meta/preview', {'instruction': 'Read public fixture.',
            'mode': 'OFFLINE_FIXTURE', 'target_url': 'https://docs.example.org/offline-fixture', **changes},
            intent='meta-preview-v1')
        self.assertEqual(200, status, result)
        return result

    def test_all_meta_routes_reject_missing_session_or_cross_origin(self):
        for method, path, data in (('GET', '/api/meta/status', None),
            ('GET', '/api/meta/evidence/meta-forged', None), ('POST', '/api/meta/preview', {}),
            ('POST', '/api/meta/run', {}), ('POST', '/api/meta/stop', {})):
            with self.subTest(path=path):
                self.assertEqual(403, self.request(method, path, data, token=False)[0])
                self.assertEqual(403, self.request(method, path, data, Origin='https://evil.example')[0])
        self.assertEqual(0, self.host.driver.read_count)

    def test_preview_run_evidence_same_app_and_same_core(self):
        preview = self.preview()
        status, run = self.request('POST', '/api/meta/run', {'task_id': preview['task_id'],
            'preview_digest': preview['preview_digest']}, intent='meta-run-fixture-v1')
        self.assertEqual(202, status, run)
        for _ in range(100):
            status, result = self.request('GET', '/api/meta/evidence/'+preview['task_id'])
            if result['state'] != 'RUNNING': break
            time.sleep(.02)
        self.assertEqual('OFFLINE_FIXTURE', result['state'])
        self.assertEqual('OFFLINE_LINKED_UNVERIFIED', result['result']['status'])
        self.assertEqual(preview['correlation_id'], result['correlation_id'])
        self.assertFalse(result['live_verified'])
        self.assertEqual(1, self.host.driver.read_count)

    def test_exact_intent_and_fields_required_and_no_owner_override(self):
        self.assertEqual(403, self.request('POST', '/api/meta/preview', {})[0])
        self.assertEqual(400, self.request('POST', '/api/meta/preview', {'approved': True}, intent='meta-preview-v1')[0])
        self.assertEqual(400, self.request('GET', '/api/meta/status?owner=other')[0])
        preview = self.preview()
        self.assertEqual(400, self.request('POST', '/api/meta/run', {'task_id': preview['task_id'],
            'preview_digest': preview['preview_digest'], 'owner': 'forged'}, intent='meta-run-fixture-v1')[0])
        self.assertEqual(0, self.host.driver.read_count)

    def test_live_is_blocked_without_spending_and_status_has_metadata_only(self):
        preview = self.preview(mode='LIVE')
        status, result = self.request('POST', '/api/meta/run', {'task_id': preview['task_id'],
            'preview_digest': preview['preview_digest']}, intent='meta-run-fixture-v1')
        self.assertEqual(403, status); self.assertIn('OWNER_GO', result['error'])
        status, result = self.request('GET', '/api/meta/status')
        self.assertEqual(200, status)
        self.assertEqual('unverified', result['provider']['credit_balance'])
        self.assertEqual('not granted', result['provider']['spend_permission'])
        self.assertIsNone(result['provider']['last_api_receipt'])
        self.assertEqual(0, self.host.driver.read_count)

    def test_stop_works_during_run_and_replay_is_rejected(self):
        preview = self.preview(); self.host.driver.delay_seconds = .7
        payload = {'task_id': preview['task_id'], 'preview_digest': preview['preview_digest']}
        self.assertEqual(202, self.request('POST', '/api/meta/run', payload, intent='meta-run-fixture-v1')[0])
        status, result = self.request('POST', '/api/meta/stop', {'task_id': preview['task_id']}, intent='meta-stop-v1')
        self.assertEqual(200, status); self.assertEqual('STOPPED', result['state'])
        self.assertEqual(409, self.request('POST', '/api/meta/run', payload, intent='meta-run-fixture-v1')[0])

    def test_meta_profile_keeps_legacy_effect_routes_closed(self):
        self.assertEqual(403, self.request('POST', '/api/chat', {'prompt': 'exec shell'})[0])


if __name__ == '__main__': unittest.main()
