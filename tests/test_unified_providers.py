"""U7 truthful provider choices; no key loading or real network transport."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.core_admission import Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition


class UnifiedProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:('1'*40,'a'*64))
        self.addCleanup(self.host.close)
        self.reader=self.host.core.local_operator(Capability.READ)

    def catalog(self):
        self.assertTrue(callable(getattr(self.host.missions,'provider_catalog',None)),'single provider catalog missing')
        return self.host.missions.provider_catalog(self.reader)

    def test_catalog_preserves_identity_and_cannot_enable_live_or_fallback(self):
        with patch('runtime.providers.meta_model_api.load_private_key',side_effect=AssertionError('key load')):
            catalog=self.catalog()
        rows={r['provider_id']:r for r in catalog['providers']}
        self.assertEqual('muse-spark-1.3',rows['meta_model_api']['model_id'])
        self.assertEqual('OFFLINE_FIXTURE',rows['meta_model_api']['mode'])
        self.assertTrue(rows['meta_model_api']['selectable'])
        self.assertFalse(rows['meta_model_api']['live_enabled']);self.assertFalse(catalog['automatic_fallback'])
        self.assertEqual('nvidia/nemotron-3-super-120b-a12b',rows['nebius']['model_id'])
        self.assertFalse(rows['nebius']['selectable']);self.assertFalse(rows['local_llama']['selectable'])
        self.assertIsNone(rows['meta_model_api']['last_invocation'])

    def test_existing_fixture_invocation_is_recorded_as_fixture_not_live(self):
        self.catalog()
        self.host.missions.preview({'instruction':'Read public fixture','mode':'OFFLINE_FIXTURE',
            'target_url':'https://docs.example.org/offline-fixture'},self.reader)
        meta=self.catalog()['providers'][0]
        self.assertEqual('OFFLINE_FIXTURE',meta['last_invocation']['mode'])
        self.assertFalse(meta['last_invocation']['live_verified'])
        self.assertEqual(0,meta['paid_api_calls_verified'])

    def test_catalog_has_no_network_or_live_billing_assumption(self):
        with patch('socket.create_connection',side_effect=AssertionError('network')):
            catalog=self.catalog()
        for row in catalog['providers']:
            self.assertFalse(row['live_enabled'])
            self.assertEqual('UNVERIFIED',row['billing_status'])


if __name__=='__main__':unittest.main()
