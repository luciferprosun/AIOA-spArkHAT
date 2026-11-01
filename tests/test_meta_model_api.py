"""P02 provider contract against injected mock HTTP, never the actual API."""
from dataclasses import replace
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.providers.exact import CancellationToken


class MetaModelAPITests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.providers.meta_model_api'),
                             'bounded Meta provider missing')
        self.api = importlib.import_module('runtime.providers.meta_model_api')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.request = self.api.MetaPlanRequest.fixture()

    def response(self):
        return {'id': 'chatcmpl-fixture', 'model': 'muse-spark-1.3', 'choices': [{
            'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
            'content': None, 'tool_calls': [{'id': 'call_fixture', 'type': 'function', 'function': {
                'name': 'navigate_read', 'arguments': json.dumps(self.request.plan_fields())}}]}}],
            'usage': {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80}}

    def provider(self, response=None, status=200):
        response = self.response() if response is None else response
        def transport(payload, cancel, timeout):
            self.calls.append(payload)
            return status, json.dumps(response).encode()
        return self.api.MetaModelProvider(mode='MOCK', transport=transport,
                                         key_path=Path(self.tmp.name)/'not-present')

    def test_mock_roundtrip_keeps_identity_usage_and_never_loads_key(self):
        with patch.object(self.api, 'load_private_key', side_effect=AssertionError('key read')):
            result = self.provider().plan(self.request, CancellationToken())
        self.assertEqual('call_fixture', result.call.call_id)
        self.assertEqual('muse-spark-1.3', result.model_id)
        self.assertEqual('META_API_MOCK', result.environment)
        self.assertFalse(result.live_verified)
        self.assertEqual(80, result.usage['total_tokens'])
        self.assertEqual(1, len(self.calls))
        self.assertEqual('https://docs.example.org/offline-fixture',
                         json.loads(self.calls[0]['messages'][-1]['content'])['target_url'])

    def test_receipt_binds_public_mission_context_without_instruction(self):
        receipt = self.provider().plan(self.request, CancellationToken()).receipt()
        self.assertIn('binding', receipt)
        binding = receipt['binding']
        self.assertEqual(self.request.task.digest, binding['task_digest'])
        self.assertEqual(self.request.correlation_id, binding['correlation_id'])
        self.assertEqual(self.request.task.allowed_origins, tuple(binding['allowed_origins']))
        self.assertNotIn(self.request.instruction, json.dumps(receipt))

    def test_disabled_provider_rejects_before_transport_or_key(self):
        provider = self.api.MetaModelProvider(transport=lambda *_: self.fail('transport'))
        with patch.object(self.api, 'load_private_key', side_effect=AssertionError('key read')):
            with self.assertRaisesRegex(self.api.MetaAPIError, 'OWNER_GO'): provider.plan(self.request, CancellationToken())

    def test_model_substitution_and_malformed_json_are_unknown(self):
        result = self.response(); result['model'] = 'nvidia/nemotron'
        with self.assertRaisesRegex(self.api.MetaAPIError, 'MODEL_MISMATCH'): self.provider(result).plan(self.request, CancellationToken())
        provider = self.api.MetaModelProvider(mode='MOCK', transport=lambda *_: (200, b'{bad'))
        with self.assertRaises(self.api.MetaAPIError): provider.plan(self.request, CancellationToken())

    def test_host_rejects_write_extra_approval_and_changed_task(self):
        for name, change in (('write_file', {}), ('navigate_read', {'approved': True}),
                             ('navigate_read', {'target_url': 'https://evil.example/path'})):
            body = self.response(); call = body['choices'][0]['message']['tool_calls'][0]
            call['function'] = {'name': name, 'arguments': json.dumps({**self.request.plan_fields(), **change})}
            with self.subTest(name=name, change=change), self.assertRaises(self.api.MetaAPIError):
                self.provider(body).plan(self.request, CancellationToken())

    def test_incomplete_missing_usage_duplicate_calls_and_invalid_totals_deny(self):
        for mutation in ('length', 'usage', 'duplicate', 'total'):
            body = self.response()
            if mutation == 'length': body['choices'][0]['finish_reason'] = 'length'
            elif mutation == 'usage': body.pop('usage')
            elif mutation == 'total': body['usage']['total_tokens'] = 1
            else: body['choices'][0]['message']['tool_calls'] *= 2
            with self.subTest(mutation=mutation), self.assertRaises(self.api.MetaAPIError):
                self.provider(body).plan(self.request, CancellationToken())

    def test_http_auth_billing_rate_and_server_errors_are_redacted_and_not_retried(self):
        for status, expected in ((401, 'AUTH'), (403, 'AUTH'), (402, 'BILLING'),
                                 (429, 'RATE'), (503, 'UNAVAILABLE')):
            self.calls.clear()
            with self.subTest(status=status), self.assertRaises(self.api.MetaAPIError) as caught:
                self.provider({'error': {'message': 'Bearer SYNTHETIC_PRIVATE_MARKER'}}, status).plan(self.request, CancellationToken())
            self.assertIn(expected, caught.exception.code)
            self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(caught.exception))
            self.assertEqual(1, len(self.calls))

    def test_budget_before_transport_and_stop_before_dispatch(self):
        provider = self.provider()
        cancel = CancellationToken(); cancel.cancel()
        with self.assertRaisesRegex(self.api.MetaAPIError, 'STOPPED'): provider.plan(self.request, cancel)
        with self.assertRaisesRegex(self.api.MetaAPIError, 'BUDGET'):
            provider.plan(replace(self.request, budget_usd='0.000001'), CancellationToken())
        self.assertEqual([], self.calls)

    def test_timeout_is_unknown_with_one_attempt(self):
        calls = []
        def fail(*_): calls.append(1); raise TimeoutError('private body')
        provider = self.api.MetaModelProvider(mode='MOCK', transport=fail)
        with self.assertRaisesRegex(self.api.MetaAPIError, 'TIMEOUT_UNKNOWN'): provider.plan(self.request, CancellationToken())
        self.assertEqual([1], calls)

    def test_real_key_loader_rejects_symlink_and_public_permissions(self):
        key = Path(self.tmp.name)/'synthetic-key'; key.write_text('synthetic-private-test-key'); key.chmod(0o600)
        link = key.with_name('link'); link.symlink_to(key)
        with self.assertRaises(self.api.MetaAPIError): self.api.load_private_key(link)
        key.chmod(0o644)
        with self.assertRaises(self.api.MetaAPIError): self.api.load_private_key(key)

    def test_existing_manager_routes_typed_meta_without_fallback(self):
        from runtime.providers.config import ProviderManager
        with patch('runtime.providers.config.load_api_environment', side_effect=AssertionError('secret environment')):
            manager = ProviderManager(Path(self.tmp.name), meta_only=True)
        manager.configure_meta(self.provider())
        status = manager.provider_status()[0]
        self.assertTrue(status['available'])
        self.assertEqual('MOCK', status['transport'])
        self.assertFalse(status['live_verified'])
        result = manager.generate_meta_plan(self.request, CancellationToken())
        self.assertEqual('meta_model_api', result.provider_id)
        with self.assertRaisesRegex(Exception, 'TYPED_MISSION'): manager.generate('hello')
        self.assertEqual(1, len(self.calls))

    def test_usage_cannot_exceed_independent_request_input_bound(self):
        body = self.response(); body['usage'] = {'prompt_tokens': 50000, 'completion_tokens': 30, 'total_tokens': 50030}
        with self.assertRaisesRegex(self.api.MetaAPIError, 'USAGE'):
            self.provider(body).plan(replace(self.request, budget_usd='0'), CancellationToken())

    def live_binding(self, *, deadline=None, admitted_model='muse-spark-1.3', approved=True):
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal
        from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
        from lab.archaioa.decision_root import DecisionDependencyRoot
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
        from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import TransactionRunner
        from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits, ReservationRequest
        from runtime.mission.warrant import CoreWarrantLedger, approval_digest
        from test_memory_patch_persistence_ports import FakeFactory
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        scope = OwnerScope('fixture-tenant','fixture-owner','fixture-space','fixture-slot')
        core = CoreAdmission(LocalOwnerAssignment(scope, frozenset(Capability), frozenset({'fixture'}),
            frozenset({admitted_model}), operator_approved=True), clock=lambda:now)
        self.addCleanup(core.close)
        runner = TransactionRunner(core, FakeFactory()); self.addCleanup(runner.close)
        ledger = CoreWarrantLedger(core, runner, scope, clock=lambda:now)
        limits = Limits(100000000, 10)
        gov = CoreDualGovernor(core, runner, GovernorPolicy(scope,'meta-fixture',limits,limits,limits),clock=lambda:100)
        epoch = gov.start_epoch(core.local_operator(Capability.MANAGE))
        request = replace(self.request,task=replace(self.request.task,owner_scope_digest=canonical_sha256(scope)))
        if deadline is not None: request=replace(request,task=replace(request.task,deadline_utc=deadline))
        operation = {'operation_class':'META_MODEL_PLAN_V2',
            'target_fingerprint':'sha256:'+canonical_sha256('https://api.meta.ai/v1/chat/completions'),
            'expected_target_revision':request.task.source_sha,
            'payload':{'request_digest':request.digest,'task_digest':request.task.digest,
                'owner_scope_digest':request.task.owner_scope_digest,'model_id':'muse-spark-1.3',
                'provider_id':'meta_model_api','endpoint':'https://api.meta.ai/v1/chat/completions','max_attempts':1,
                'public_binding_digest':canonical_sha256(request.public_binding())}}
        reservation = ReservationRequest('meta-spend',request.task.task_id,'meta_model_api','muse-spark-1.3',
            canonical_sha256(operation),50000000,1)
        commit = core.local_operator(Capability.COMMIT)
        gov.reserve(commit,reservation,epoch)
        authority = AuthorityScope(operation_classes=('META_MODEL_PLAN_V2',),target_scope=operation['target_fingerprint'],
            risk_ceiling=RiskLevel.MODERATE,monetary_ceiling=Money(Decimal('.05'),'USD'),
            not_before=now,expires_at=now+timedelta(minutes=1),owner_scope=request.task.owner_scope_digest,task_scope=request.task.task_id)
        warrant = EffectWarrant(warrant_id='meta-warrant',task_id=request.task.task_id,
            owner_scope=request.task.owner_scope_digest,operation_class='META_MODEL_PLAN_V2',
            operation_hash='sha256:'+canonical_sha256(operation),target_fingerprint=operation['target_fingerprint'],
            expected_target_revision=request.task.source_sha,revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot((EvidenceRef('task','task','sha256:'+request.task.digest,'v1'),)),
            lease_epoch=epoch,authority_scope=authority,approval_digest='sha256:'+'0'*64,
            money_reservation_id='meta-spend',risk_reservation_id='meta-spend',nonce='meta-spend-nonce',
            issued_at=now,expires_at=now+timedelta(minutes=1))
        warrant=replace(warrant,approval_digest=approval_digest(warrant))
        if approved:ledger.approve(core.local_operator(Capability.OWNER_APPROVAL),warrant)
        binding=self.api.MetaLiveBinding(ledger,gov,commit,warrant,reservation,True,True)
        if hasattr(binding,'source_reader'):
            binding=replace(binding,source_reader=lambda: (request.task.source_sha,request.capsule_digest)
                if hasattr(request,'capsule_digest') else request.task.source_sha)
        return request,binding

    def test_live_shaped_mock_uses_real_core_budget_hold_before_http_and_rejects_replay(self):
        from runtime.core_admission import Capability
        request,binding = self.live_binding()
        body=self.response();body['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(request.plan_fields())
        provider=self.api.MetaModelProvider(mode='LIVE')
        def upstream(payload,key,cancel,timeout):
            self.assertIsNotNone(binding.ledger.inspect(binding.ledger.core.local_operator(Capability.READ),binding.warrant))
            state=binding.governor.inspect(binding.ledger.core.local_operator(Capability.READ))
            self.assertEqual('UNKNOWN',state['reservations']['meta-spend']['state'])
            return 200,json.dumps(body).encode()
        with patch.object(self.api,'load_private_key',return_value='SYNTHETIC_PROVIDER_TEST_KEY'), \
             patch.object(self.api,'_https_once',side_effect=upstream) as transport:
            result=provider.plan(request,CancellationToken(),live_binding=binding)
            self.assertTrue(result.live_verified)  # TEST transport only; never published as actual Meta proof.
            with self.assertRaises(Exception):provider.plan(request,CancellationToken(),live_binding=binding)
            self.assertEqual(1,transport.call_count)

    def test_missing_live_key_does_not_consume_warrant_or_call_http(self):
        from runtime.core_admission import Capability
        request,binding=self.live_binding()
        provider=self.api.MetaModelProvider(mode='LIVE',key_path=Path(self.tmp.name)/'missing-key')
        with patch.object(self.api,'_https_once',side_effect=AssertionError('HTTP')):
            with self.assertRaisesRegex(self.api.MetaAPIError,'KEY_UNAVAILABLE'):
                provider.plan(request,CancellationToken(),live_binding=binding)
        self.assertIsNone(binding.ledger.inspect(binding.ledger.core.local_operator(Capability.READ),binding.warrant))

    def test_live_gate_rejects_expired_task_unadmitted_model_and_source_drift(self):
        with self.assertRaises(ValueError):self.live_binding(admitted_model='other-model')
        request,binding=self.live_binding(deadline='2026-05-31T00:00:00Z')
        with patch.object(self.api,'load_private_key',side_effect=AssertionError('key read')):
            with self.assertRaises(self.api.MetaAPIError):binding.check(request)
        request,binding=self.live_binding()
        if not hasattr(binding,'source_reader'):self.fail('native binding lacks independent source reader')
        binding=replace(binding,source_reader=lambda:'2'*40)
        with self.assertRaises(self.api.MetaAPIError):binding.check(request)

    def test_missing_recorded_owner_approval_never_reads_key(self):
        request,binding=self.live_binding(approved=False)
        provider=self.api.MetaModelProvider(mode='LIVE')
        with patch.object(self.api,'load_private_key',return_value='SYNTHETIC_PROVIDER_TEST_KEY') as loader:
            with self.assertRaises(Exception):provider.plan(request,CancellationToken(),live_binding=binding)
        self.assertEqual(0,loader.call_count,'unapproved native binding reached credential loader')

    def test_same_commit_with_changed_capsule_is_not_authorized(self):
        request,binding=self.live_binding()
        self.assertTrue(hasattr(request,'capsule_digest'),'request lacks exact capsule commitment')
        binding=replace(binding,source_reader=lambda:(request.task.source_sha,'b'*64))
        with self.assertRaises(self.api.MetaAPIError):binding.check(request)

    def test_unicode_escaped_credential_echo_never_enters_receipt(self):
        request,binding=self.live_binding(); key='SYNTHETIC_PROVIDER_TEST_KEY'
        body=self.response();body['choices'][0]['message']['tool_calls'][0]['id']=key
        body['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(request.plan_fields())
        raw=json.dumps(body).replace(key,''.join('\\u%04x'%ord(c) for c in key)).encode()
        provider=self.api.MetaModelProvider(mode='LIVE')
        with patch.object(self.api,'load_private_key',return_value=key), \
             patch.object(self.api,'_https_once',return_value=(200,raw)):
            with self.assertRaisesRegex(self.api.MetaAPIError,'CREDENTIAL_ECHO'):
                provider.plan(request,CancellationToken(),live_binding=binding)


if __name__ == '__main__': unittest.main()
