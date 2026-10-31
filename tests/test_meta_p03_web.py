"""P03 additive diagnostics and intent framing on existing authenticated API."""
import unittest
from unittest.mock import patch
import test_meta_web as p02


class MetaP03WebTests(unittest.TestCase):
    setUp=p02.MetaWebTests.setUp
    tearDown=p02.MetaWebTests.tearDown
    request=p02.MetaWebTests.request
    preview=p02.MetaWebTests.preview

    def test_status_r6_is_honest_and_keeps_p02_fields(self):
        status,value=self.request('GET','/api/meta/status')
        self.assertEqual(200,status)
        provider=value['provider']
        self.assertEqual('NOT_ATTEMPTED',provider['call_state'])
        self.assertEqual('UNVERIFIED',provider['billing_status'])
        self.assertFalse(provider['credits_confirmed'])
        self.assertIsNone(provider['last_live_receipt'])
        self.assertIsNone(provider['last_api_receipt'])
        self.assertEqual('not granted',provider['spend_permission'])

    def test_explicit_native_run_intent_still_requires_existing_core_owner_binding(self):
        preview=self.preview(mode='LIVE')
        with patch('runtime.providers.meta_model_api._https_once') as http:
            status,value=self.request('POST','/api/meta/run',{'task_id':preview['task_id'],
                'preview_digest':preview['preview_digest']},intent='meta-run-approved-v1')
        self.assertEqual(403,status)
        self.assertIn('OWNER_GO',value['error'])
        self.assertEqual(0,http.call_count)

    def test_http_cannot_submit_native_owner_authority_or_budget(self):
        preview=self.preview(mode='LIVE')
        for forged in ({'native_spend_binding':'BOUND'},{'operator_approved':True},{'budget_usd':'.05'}):
            with self.subTest(forged=forged):
                status,_=self.request('POST','/api/meta/run',{'task_id':preview['task_id'],
                    'preview_digest':preview['preview_digest'],**forged},intent='meta-run-approved-v1')
                self.assertEqual(400,status)


if __name__=='__main__':unittest.main()
