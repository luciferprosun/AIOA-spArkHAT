"""Capability inspection must not initialize execution or semantic memory."""
import unittest
from unittest.mock import patch
import test_mobile_pairing as fixture
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind


class NativeCapabilityPreviewTests(unittest.TestCase):
    setUp=fixture.PairingTests.setUp
    start=fixture.PairingTests.start
    tearDown=fixture.PairingTests.tearDown

    def test_existing_contract_preview_is_pure_and_memory_backends_are_distinct(self):
        from runtime.meta_hackathon.native_tools import registry
        before=self.app.mobile._run(Capability.READ,lambda tx:len(tx.scan(RecordKind.OPERATION,limit=128)))
        with patch('runtime.providers.meta_model_api._https_once') as transport:
            value=registry(self.app)
            preview=value['cpl']['preview']
            self.assertEqual('cpl-1plus3plus1-v1',preview['contract'])
            self.assertEqual(5,preview['expected_generation_requests']);self.assertEqual(0,preview['provider_calls'])
            self.assertFalse(preview['execution_authorized']);self.assertEqual(3,len(preview['roles']))
            self.assertFalse(value['cpl']['enabled'])
            self.assertEqual('READ_ONLY_ADVISORY',value['cpl']['preview_status'])
            self.assertTrue(value['cpl']['preview_enabled'])
            self.assertEqual({'status':'BLOCKED_NATIVE_WORKER_NOT_CERTIFIED','enabled':False},value['worker'])
            self.assertEqual('INTEGRATED_INERT',value['memory']['status'])
            self.assertEqual('MEMORY_CONSENT_REQUIRED',value['memory']['blocking_reason'])
            self.assertFalse(value['memory']['save_knowledge'])
            self.assertEqual('CORE_RECORDS_SQLITE',value['memory']['core_records']['status'])
            self.assertFalse(value['memory']['semantic_memory']['enabled'])
            self.assertEqual('NOT_BOUND',value['memory']['cockroach']['status'])
            transport.assert_not_called()
        self.assertEqual(before,self.app.mobile._run(Capability.READ,lambda tx:len(tx.scan(RecordKind.OPERATION,limit=128))))


if __name__=='__main__':unittest.main()
