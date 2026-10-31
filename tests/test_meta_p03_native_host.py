"""Trusted host port over existing Core; synthetic HTTPS only."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_meta_model_api as p02
from runtime.browser_agent.chrome_read_adapter import ChromeReadAdapter, FixtureReadDriver
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.meta_hackathon.contracts import BrowserTaskV1
from runtime.meta_hackathon.mission_service import MissionService
from runtime.mission.warrant import approval_digest
from runtime.providers.config import ProviderManager
from runtime.providers.meta_model_api import MetaModelProvider, MetaPlanRequest


class NativeHostTests(unittest.TestCase):
    live_binding = p02.MetaModelAPITests.live_binding

    def setUp(self):
        p02.MetaModelAPITests.setUp(self)
        _, self.initial = self.live_binding()
        self.manager = ProviderManager(Path(self.tmp.name), meta_only=True)
        self.manager.configure_meta(MetaModelProvider(mode='LIVE'))
        self.driver = FixtureReadDriver()
        self.source = ['1'*40, '0'*64]
        self.service = MissionService(self.initial.ledger, self.manager, ChromeReadAdapter(self.driver),
                                      lambda:tuple(self.source))
        self.addCleanup(self.service.close)
        self.instruction = 'Read the public fixture.'
        self.preview = self.service.preview({'mode':'LIVE','instruction':self.instruction,
            'target_url':'https://docs.example.org/offline-fixture'},
            self.initial.ledger.core.local_operator(Capability.READ))

    def approve(self, request=None):
        task = BrowserTaskV1.parse(self.preview['task'])
        request = request or MetaPlanRequest(task, self.instruction, self.preview['correlation_id'],
                                            '.05', capsule_digest=self.preview['capsule_digest'])
        operation = {'operation_class':'META_MODEL_PLAN_V1',
            'target_fingerprint':'sha256:'+canonical_sha256(self.api.ENDPOINT),
            'expected_target_revision':request.task.source_sha,
            'payload':{'request_digest':request.digest,'task_digest':request.task.digest,
                'owner_scope_digest':request.task.owner_scope_digest,'model_id':self.api.MODEL,
                'provider_id':self.api.PROVIDER,'endpoint':self.api.ENDPOINT,'max_attempts':1}}
        b=self.initial
        reservation=replace(b.reservation,request_id='p03-spend',task_id=task.task_id,
                            request_digest=canonical_sha256(operation))
        b.governor.reserve(b.principal,reservation,b.warrant.lease_epoch)
        authority=replace(b.warrant.authority_scope, task_scope=task.task_id)
        warrant=replace(b.warrant,warrant_id='p03-warrant',task_id=task.task_id,
            operation_hash='sha256:'+canonical_sha256(operation),authority_scope=authority,
            money_reservation_id=reservation.request_id,risk_reservation_id=reservation.request_id,
            nonce='p03-native-nonce')
        warrant=replace(warrant,approval_digest=approval_digest(warrant))
        b.ledger.approve(b.ledger.core.local_operator(Capability.OWNER_APPROVAL),warrant)
        return request,replace(b,warrant=warrant,reservation=reservation,
            source_reader=lambda:tuple(self.source))

    def owner(self): return self.initial.ledger.core.local_operator(Capability.OWNER_APPROVAL)

    def wait(self):
        for _ in range(100):
            result=self.service.evidence(self.preview['task_id'],self.initial.ledger.core.local_operator(Capability.READ))
            if result['state']!='RUNNING':return result
            time.sleep(.01)
        self.fail('worker timeout')

    def test_without_native_binding_run_never_reads_key_or_calls_http(self):
        with patch.object(self.api,'load_private_key') as key,patch.object(self.api,'_https_once') as http:
            with self.assertRaisesRegex(ValueError,'OWNER_GO'):
                self.service.run(self.preview['task_id'],self.preview['preview_digest'],self.owner())
        self.assertEqual((0,0),(key.call_count,http.call_count))

    def test_exact_bound_request_uses_existing_manager_core_and_durable_receipt(self):
        request,binding=self.approve()
        bound=self.service.bind_live_request(self.preview['task_id'],request,binding)
        self.assertEqual('BOUND',bound['native_spend_binding'])
        self.assertNotEqual(self.preview['preview_digest'],bound['preview_digest'])
        body=p02.MetaModelAPITests.response(self)
        body['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(request.plan_fields())
        with patch.object(self.api,'load_private_key',return_value='SYNTHETIC_PROVIDER_TEST_KEY'), \
             patch.object(self.api,'_https_once',return_value=(200,json.dumps(body).encode())) as http:
            self.service.run(bound['task_id'],bound['preview_digest'],self.owner())
            result=self.wait()
        self.assertEqual(1,http.call_count)
        self.assertEqual('BLOCKED',result['state'])
        self.assertEqual('CHROME_LIVE_BLOCKED_CONTAINMENT',result['error'])
        self.assertFalse(result['live_verified'])
        self.assertEqual(0,self.driver.read_count,'LIVE model must never dispatch a fake browser')
        status=self.service.status(binding.ledger.core.local_operator(Capability.READ))
        self.assertEqual('COMPLETED',status['provider']['call_state'])
        self.assertEqual(request.digest,status['provider']['last_live_receipt']['request_digest'])
        with self.assertRaises(ValueError):self.service.run(bound['task_id'],bound['preview_digest'],self.owner())

    def test_changed_instruction_arguments_or_capsule_cannot_bind(self):
        task=BrowserTaskV1.parse(self.preview['task'])
        request=MetaPlanRequest(task,'different payload',self.preview['correlation_id'],'.05',capsule_digest=self.source[1])
        request,binding=self.approve(request)
        with patch.object(self.api,'load_private_key') as key:
            with self.assertRaises(ValueError):self.service.bind_live_request(self.preview['task_id'],request,binding)
        self.assertEqual(0,key.call_count)

    def test_another_core_with_same_scope_is_not_a_native_binding(self):
        request,binding=self.approve()
        _,other=self.live_binding()
        with self.assertRaises(ValueError):
            self.service.bind_live_request(self.preview['task_id'],request,replace(binding,ledger=other.ledger))

    def test_stop_after_binding_prevents_model_and_preserves_no_read_effect(self):
        request,binding=self.approve();bound=self.service.bind_live_request(self.preview['task_id'],request,binding)
        self.service.stop(bound['task_id'],binding.ledger.core.local_operator(Capability.READ))
        with patch.object(self.api,'_https_once') as http:
            with self.assertRaises(ValueError):self.service.run(bound['task_id'],bound['preview_digest'],self.owner())
        self.assertEqual(0,http.call_count);self.assertEqual(0,self.driver.read_count)

    def test_live_preview_is_single_active_and_restart_does_not_resume(self):
        with self.assertRaisesRegex(ValueError,'ACTIVE'):
            self.service.preview({'mode':'LIVE','instruction':self.instruction,
                'target_url':'https://docs.example.org/offline-fixture'},
                self.initial.ledger.core.local_operator(Capability.READ))
        self.service.close()
        restarted=MissionService(self.initial.ledger,self.manager,ChromeReadAdapter(self.driver),lambda:tuple(self.source))
        self.addCleanup(restarted.close)
        state=restarted.evidence(self.preview['task_id'],self.initial.ledger.core.local_operator(Capability.READ))
        self.assertEqual('UNKNOWN',state['state'])


if __name__ == '__main__':unittest.main()
