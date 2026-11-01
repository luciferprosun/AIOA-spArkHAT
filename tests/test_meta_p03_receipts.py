"""P03 native-shaped calls use synthetic credentials/HTTPS, never Meta API."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import test_meta_model_api as p02
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.providers.exact import CancellationToken


class MetaReceiptTests(unittest.TestCase):
    setUp = p02.MetaModelAPITests.setUp
    live_binding = p02.MetaModelAPITests.live_binding
    response = p02.MetaModelAPITests.response

    def live(self):
        request, binding = self.live_binding()
        body = self.response()
        body['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(request.plan_fields())
        provider = self.api.MetaModelProvider(mode='LIVE')
        return request, binding, provider, json.dumps(body).encode()

    def invoke(self, request, binding, provider, *, status=200, raw=b'', error=None):
        with patch.object(self.api, 'load_private_key', return_value='SYNTHETIC_PROVIDER_TEST_KEY'), \
             patch.object(self.api, '_https_once', side_effect=error, return_value=(status, raw)) as transport:
            result = provider.plan(request, CancellationToken(), live_binding=binding)
        return result, transport.call_count

    def test_default_diagnostics_are_unattempted_and_do_not_claim_billing(self):
        value = self.api.MetaModelProvider().diagnostics()
        self.assertEqual('NOT_ATTEMPTED', value.get('call_state'))
        self.assertEqual('UNVERIFIED', value['billing_status'])
        self.assertFalse(value['credits_confirmed'])
        self.assertIsNone(value['last_live_receipt'])
        self.assertIsNone(value['settled_cost'])

    def test_completed_receipt_is_scoped_durable_and_does_not_reauthorize_spend(self):
        request, binding, provider, raw = self.live()
        result, calls = self.invoke(request, binding, provider, raw=raw)
        self.assertEqual(1, calls)
        value = provider.diagnostics()
        self.assertEqual('COMPLETED', value.get('call_state'))
        receipt = value['last_live_receipt']
        self.assertEqual(result.request_digest, receipt['request_digest'])
        self.assertEqual(request.correlation_id, receipt['binding']['correlation_id'])
        self.assertEqual(binding.warrant.lease_epoch, receipt['policy_epoch'])
        self.assertEqual(1, receipt['attempt'])
        self.assertEqual('not granted', value['spend_permission'])
        self.assertEqual('UNVERIFIED', value['billing_status'])
        self.assertFalse(value['credits_confirmed'])
        self.assertIsNone(value['settled_cost'])
        view = provider.receipt_view
        restarted = self.api.MetaModelProvider(receipt_view=view)
        self.assertEqual(receipt, restarted.diagnostics()['last_live_receipt'])
        self.assertNotIn('SYNTHETIC_PROVIDER_TEST_KEY', json.dumps(value))
        self.assertNotIn(request.instruction, json.dumps(value))

    def test_timeout_is_durable_unknown_without_second_post(self):
        request, binding, provider, _ = self.live()
        with self.assertRaisesRegex(self.api.MetaAPIError, 'TIMEOUT_UNKNOWN'):
            self.invoke(request, binding, provider, error=TimeoutError())
        self.assertEqual('UNKNOWN', provider.diagnostics().get('call_state'))
        restarted = self.api.MetaModelProvider(mode='LIVE', receipt_view=provider.receipt_view)
        self.assertEqual('UNKNOWN', restarted.diagnostics()['call_state'])
        with patch.object(self.api, '_https_once') as http, patch.object(self.api, 'load_private_key') as key:
            with self.assertRaises(Exception): restarted.plan(request, CancellationToken(), live_binding=binding)
        self.assertEqual(0, http.call_count)
        self.assertEqual(0, key.call_count)

    def test_http_failures_are_recorded_redacted_and_not_retried(self):
        for status in (401, 402, 403, 429, 503):
            with self.subTest(status=status):
                request, binding, provider, _ = self.live()
                with self.assertRaises(self.api.MetaAPIError):
                    self.invoke(request, binding, provider, status=status, raw=b'private response')
                value = provider.diagnostics()
                self.assertEqual('FAILED', value.get('call_state'))
                self.assertEqual(status, value['last_attempt']['http_status'])
                self.assertIsNone(value['last_live_receipt'])
                self.assertNotIn('private response', json.dumps(value))

    def test_malformed_model_outcome_is_unknown_not_a_live_receipt(self):
        request, binding, provider, raw = self.live()
        with self.assertRaisesRegex(self.api.MetaAPIError, 'MODEL_MISMATCH'):
            self.invoke(request, binding, provider, raw=raw.replace(b'muse-spark-1.3', b'other-model'))
        value = provider.diagnostics()
        self.assertEqual('UNKNOWN', value.get('call_state'))
        self.assertIsNone(value['last_live_receipt'])

    def test_changed_source_capsule_or_epoch_hides_stale_receipt(self):
        request, binding, provider, raw = self.live()
        self.invoke(request, binding, provider, raw=raw)
        view = provider.receipt_view
        from runtime.providers.meta_receipts import MetaReceiptView
        for source in [('2'*40, request.capsule_digest), (request.task.source_sha, 'b'*64)]:
            altered = MetaReceiptView(binding.ledger, governor=binding.governor, source_reader=lambda:source)
            value = provider.diagnostics(receipt_view=altered)
            self.assertEqual('UNKNOWN', value['call_state'])
            self.assertIsNone(value['last_live_receipt'])
        binding.governor.start_epoch(binding.ledger.core.local_operator(Capability.MANAGE))
        self.assertEqual('UNKNOWN', provider.diagnostics(receipt_view=view)['call_state'])
        self.assertIsNone(provider.diagnostics(receipt_view=view)['last_live_receipt'])

    def test_crash_inflight_projects_unknown_on_restart_and_never_resends(self):
        request, binding, provider, _ = self.live()
        with self.assertRaises(KeyboardInterrupt):
            self.invoke(request, binding, provider, error=KeyboardInterrupt())
        restarted = self.api.MetaModelProvider(mode='LIVE', receipt_view=provider.receipt_view)
        self.assertEqual('UNKNOWN', restarted.diagnostics()['call_state'])
        with patch.object(self.api, '_https_once') as http:
            with self.assertRaises(Exception): restarted.plan(request, CancellationToken(), live_binding=binding)
        self.assertEqual(0, http.call_count)

    def test_completion_ack_loss_is_unknown_and_never_automatic_retry(self):
        request, binding, provider, raw = self.live()
        def respond(*_):
            binding.ledger.runner._factory.commit_faults[:] = ['unknown_after_commit']
            return 200, raw
        with self.assertRaises(self.api.MetaAPIError):
            self.invoke(request, binding, provider, error=respond)
        self.assertEqual('UNKNOWN', provider.diagnostics().get('call_state'))
        self.assertIsNone(provider.diagnostics()['last_live_receipt'])

    def test_late_response_is_unknown_even_if_transport_ignores_timeout(self):
        request, binding, provider, raw = self.live()
        with patch.object(self.api.time, 'monotonic', side_effect=[10., 30., 30.]):
            with self.assertRaisesRegex(self.api.MetaAPIError, 'TIMEOUT_UNKNOWN'):
                self.invoke(request, binding, provider, raw=raw)
        self.assertEqual('UNKNOWN', provider.diagnostics().get('call_state'))

    def test_stopped_transport_leaves_stopped_attempt_with_unknown_budget(self):
        request, binding, provider, raw = self.live()
        cancel = CancellationToken()
        def stopped(*_): cancel.cancel(); return 200, raw
        with patch.object(self.api, 'load_private_key', return_value='SYNTHETIC_PROVIDER_TEST_KEY'), \
             patch.object(self.api, '_https_once', side_effect=stopped):
            with self.assertRaisesRegex(self.api.MetaAPIError, 'STOPPED'):
                provider.plan(request, cancel, live_binding=binding)
        self.assertEqual('STOPPED', provider.diagnostics().get('call_state'))
        state=binding.governor.inspect(binding.ledger.core.local_operator(Capability.READ))
        self.assertEqual('UNKNOWN',state['reservations']['meta-spend']['state'])

    def test_deleted_owner_approval_cannot_be_presented_as_verified_receipt(self):
        request,binding,provider,raw=self.live()
        self.invoke(request,binding,provider,raw=raw)
        from runtime.memory_patch.persistence.ports import RecordKind
        factory=binding.ledger.runner._factory
        key=(binding.ledger.scope.binding(),RecordKind.OPERATION,binding.ledger._key(binding.warrant))
        del factory.state[key]  # Synthetic storage corruption, not an operator action.
        value=provider.diagnostics()
        self.assertEqual('UNKNOWN',value['call_state'])
        self.assertIsNone(value['last_live_receipt'])

    def test_corrupt_stored_usage_cannot_be_projected_as_live_receipt(self):
        request,binding,provider,raw=self.live()
        self.invoke(request,binding,provider,raw=raw)
        from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord
        factory=binding.ledger.runner._factory
        key=(binding.ledger.scope.binding(),RecordKind.RECEIPT,'meta-api-'+request.digest)
        row=factory.state[key];value=json.loads(canonical_json_bytes(row.payload))
        value['usage']['completion_tokens']=-1
        factory.state[key]=StoredRecord(RecordKind.RECEIPT,row.record_id,row.scope,row.revision,value)
        projected=provider.diagnostics()
        self.assertEqual('UNKNOWN',projected['call_state'])
        self.assertIsNone(projected['last_live_receipt'])

    def test_new_core_session_reads_durable_receipt_without_reauthorizing(self):
        request,binding,provider,raw=self.live()
        self.invoke(request,binding,provider,raw=raw)
        from runtime.core_admission import CoreAdmission
        from runtime.memory_patch.persistence.ports import TransactionRunner
        from runtime.mission.warrant import CoreWarrantLedger
        from runtime.mission.governor import CoreDualGovernor
        from runtime.providers.meta_receipts import MetaReceiptView
        from test_memory_patch_persistence_ports import FakeFactory
        core=CoreAdmission(binding.ledger.core._assignment,clock=binding.ledger.clock)
        self.addCleanup(core.close)
        runner=TransactionRunner(core,FakeFactory(state=binding.ledger.runner._factory.state))
        self.addCleanup(runner.close)
        ledger=CoreWarrantLedger(core,runner,binding.ledger.scope,clock=binding.ledger.clock)
        governor=CoreDualGovernor(core,runner,binding.governor.policy,clock=binding.governor.clock)
        view=MetaReceiptView(ledger,governor=governor,source_reader=binding.source_reader)
        after=self.api.MetaModelProvider(receipt_view=view).diagnostics()
        self.assertEqual('COMPLETED',after['call_state'])
        self.assertEqual(request.digest,after['last_live_receipt']['request_digest'])
        self.assertEqual('not granted',after['spend_permission'])

    def corrupt(self,binding,kind,identity,change):
        from runtime.memory_patch.persistence.ports import StoredRecord
        factory=binding.ledger.runner._factory
        key=(binding.ledger.scope.binding(),kind,identity);row=factory.state[key]
        data=json.loads(canonical_json_bytes(row.payload));change(data)
        factory.state[key]=StoredRecord(kind,identity,row.scope,row.revision,data)

    def test_review_r1_unknown_receipt_fields_and_invalid_cost_never_escape(self):
        from runtime.memory_patch.persistence.ports import RecordKind
        for mutation in ('extra_receipt','invalid_cost'):
            with self.subTest(mutation=mutation):
                request,binding,provider,raw=self.live();self.invoke(request,binding,provider,raw=raw)
                if mutation=='extra_receipt':
                    self.corrupt(binding,RecordKind.RECEIPT,'meta-api-'+request.digest,
                                 lambda value:value.update(Authorization='LEAK_MARKER_PRIVATE'))
                else:
                    self.corrupt(binding,RecordKind.OPERATION,'meta-api-attempt-'+request.digest,
                                 lambda value:value.update(cost_estimate='LEAK_MARKER_PRIVATE'))
                projected=provider.diagnostics()
                self.assertNotIn('LEAK_MARKER_PRIVATE',json.dumps(projected))
                self.assertEqual('UNKNOWN',projected['call_state'])
                self.assertIsNone(projected['last_live_receipt'])

    def test_review_r2_coordinated_public_binding_substitution_is_not_approved(self):
        from runtime.memory_patch.persistence.ports import RecordKind
        request,binding,provider,raw=self.live();self.invoke(request,binding,provider,raw=raw)
        def mutate(data):
            data['binding']['correlation_id']='another-correlation'
            data['binding']['allowed_origins']=['https://evil.example']
        self.corrupt(binding,RecordKind.OPERATION,'meta-api-attempt-'+request.digest,mutate)
        self.corrupt(binding,RecordKind.RECEIPT,'meta-api-'+request.digest,mutate)
        value=provider.diagnostics()
        self.assertEqual('UNKNOWN',value['call_state'])
        self.assertIsNone(value['last_live_receipt'])

    def test_review_r3_last_receipt_survives_new_failed_attempt_and_restart(self):
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.warrant import approval_digest
        for failure in (401,'timeout'):
            with self.subTest(failure=failure):
                first,binding,provider,raw=self.live();self.invoke(first,binding,provider,raw=raw)
                second=replace(first,task=replace(first.task,task_id='meta-second'),correlation_id='second-correlation')
                operation={'operation_class':binding.warrant.operation_class,
                    'target_fingerprint':'sha256:'+canonical_sha256(self.api.ENDPOINT),
                    'expected_target_revision':second.task.source_sha,
                    'payload':{'request_digest':second.digest,'task_digest':second.task.digest,
                        'owner_scope_digest':second.task.owner_scope_digest,'model_id':self.api.MODEL,
                        'provider_id':self.api.PROVIDER,'endpoint':self.api.ENDPOINT,'max_attempts':1}}
                if binding.warrant.operation_class=='META_MODEL_PLAN_V2':
                    operation['payload']['public_binding_digest']=canonical_sha256(second.public_binding())
                reservation=replace(binding.reservation,request_id='second-spend',task_id='meta-second',
                                    request_digest=canonical_sha256(operation))
                binding.governor.reserve(binding.principal,reservation,binding.warrant.lease_epoch)
                warrant=replace(binding.warrant,warrant_id='second-warrant',task_id='meta-second',nonce='second-nonce',
                    operation_class=operation['operation_class'],operation_hash='sha256:'+canonical_sha256(operation),
                    authority_scope=replace(binding.warrant.authority_scope,operation_classes=(operation['operation_class'],),task_scope='meta-second'),
                    money_reservation_id=reservation.request_id,risk_reservation_id=reservation.request_id)
                warrant=replace(warrant,approval_digest=approval_digest(warrant))
                binding.ledger.approve(binding.ledger.core.local_operator(Capability.OWNER_APPROVAL),warrant)
                next_binding=replace(binding,warrant=warrant,reservation=reservation)
                with self.assertRaises(Exception):
                    self.invoke(second,next_binding,provider,status=401 if failure==401 else 200,
                                error=TimeoutError() if failure=='timeout' else None)
                restarted=self.api.MetaModelProvider(receipt_view=provider.receipt_view)
                projected=restarted.diagnostics()
                self.assertEqual('FAILED' if failure==401 else 'UNKNOWN',projected['call_state'])
                self.assertEqual(second.digest,projected['last_attempt']['request_digest'])
                self.assertIsNotNone(projected['last_live_receipt'])
                self.assertEqual(first.digest,projected['last_live_receipt']['request_digest'])
                self.assertEqual('not granted',projected['spend_permission'])

    def test_review_m2_non_usd_warrant_is_rejected_before_credentials(self):
        from lab.archaioa.authority import Money
        from decimal import Decimal
        from runtime.mission.warrant import approval_digest
        request,binding,provider,raw=self.live()
        warrant=replace(binding.warrant,warrant_id='euro-warrant',nonce='euro-nonce',
            authority_scope=replace(binding.warrant.authority_scope,monetary_ceiling=Money(Decimal('.05'),'EUR')))
        warrant=replace(warrant,approval_digest=approval_digest(warrant))
        binding.ledger.approve(binding.ledger.core.local_operator(Capability.OWNER_APPROVAL),warrant)
        with patch.object(self.api,'load_private_key') as key,patch.object(self.api,'_https_once') as http:
            with self.assertRaisesRegex(self.api.MetaAPIError,'CURRENCY'):
                provider.plan(request,CancellationToken(),live_binding=replace(binding,warrant=warrant))
        self.assertEqual(0,key.call_count);self.assertEqual(0,http.call_count)


if __name__ == '__main__': unittest.main()
