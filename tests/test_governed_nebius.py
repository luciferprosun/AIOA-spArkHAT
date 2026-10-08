"""Exact native Nebius port with offline transport fixture and durable governor."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import unittest

from runtime.memory_patch.contracts.serialization import canonical_sha256
import test_dual_governor as governor_fixtures
from test_nebius_routing import catalog_receipt, quote, route_budgets
from runtime.core_admission import Capability
from runtime.providers.exact import ProviderResult
from runtime.providers.nebius_routing import ModelRole, NebiusModelRouter, NebiusProviderPort
from runtime.providers.nvidia import ProviderError, ProviderRequest
from runtime.mission.lite_contracts import LiteBudget

MODEL = governor_fixtures.MODEL


class GovernedNebiusTests(unittest.TestCase):
    def setUp(self):
        self.fx=governor_fixtures.DualGovernorTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.calls=[];self.before=None;self.after=None;self.transport_fails=False
        fixture=self
        class ExactFixture:
            def __init__(self,**_kwargs):pass
            def generate_exact(self,request,*_args):
                fixture.calls.append(request)
                if fixture.transport_fails:raise TimeoutError()
                if fixture.after:fixture.after()
                return ProviderResult(content=json.dumps({'summary':'Fixture architecture advice','needs_attention':False}),
                    provider_connection_id='nebius',requested_model=MODEL,reported_model=MODEL,
                    identity_status='EXACT_MATCH',request_id='fixture-receipt',usage={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
                    finish_reason='stop',transport_scope='TEST',latency_ms=1)
        self.factory=ExactFixture
        self.route=NebiusModelRouter(catalog_receipt(),role_budgets=route_budgets()).select(ModelRole.FAST)
        self.request=ProviderRequest('wire-request','trace','nebius',MODEL,'Bounded untrusted fixture input','legacy-unit-reservation',128,20)

    def port(self,*,governed=True,input_rate='0.06',output_rate='0.24'):
        from runtime.mission.governor import GovernorBinding
        binding=GovernorBinding(self.fx.gov,self.fx.principal(),self.fx.epoch,'task1',1) if governed else None
        def fixture_key():
            if self.before:self.before()
            return 'fixture-not-a-real-key'
        return NebiusProviderPort(self.route,LiteBudget(max_output_tokens=128,request_timeout_seconds=20),quote(input_rate=input_rate,output_rate=output_rate),
            provider_factory=self.factory,secret_supplier=fixture_key,transport_scope='TEST',governor_binding=binding)

    def test_money_bound_is_exact_upward_integer_without_secret_or_transport(self):
        # Literal rational result: 1000 * (1*0.000001 + 1*0.000001) = 0.002 => ceil 1 nanoUSD.
        try:
            from runtime.providers.nebius_routing import conservative_nano_usd
        except ImportError:
            self.fail('Native port lacks fixed integer conservative money estimate')
        with localcontext() as context:
            context.prec=2
            self.assertEqual(1,conservative_nano_usd(1,1,Decimal('0.000001'),Decimal('0.000001')))
            self.assertEqual(243960,conservative_nano_usd(2018,512,Decimal('0.06'),Decimal('0.24')))
        self.assertEqual([],self.calls)

    def test_governed_port_reserves_money_and_risk_before_one_transport(self):
        port=self.port()
        estimate=port.estimated_money_nano(self.request)
        # Give this synthetic Core a sufficient monetary ceiling before any event exists.
        self.fx= self.with_money_policy(self.fx)
        port=self.port()
        response=port.request(self.request)
        self.assertEqual('ADVISORY_ONLY',response.authority)
        self.assertEqual(1,len(self.calls))
        state=self.fx.inspect()
        self.assertEqual('COMMITTED',state['reservations']['wire-request']['state'])
        self.assertEqual(estimate,state['exposure']['global']['money_nano'])
        self.assertEqual(1,state['exposure']['global']['risk_units'])
        with self.assertRaises(ProviderError):port.request(self.request)
        self.assertEqual(1,len(self.calls))

    def with_money_policy(self,fixture):
        # Isolated second native test backend, not a policy mutation of a live ledger.
        from test_dual_governor import core
        from nv03_support import DurableFactory
        from runtime.memory_patch.persistence.ports import TransactionRunner
        c=core();self.addCleanup(c.close)
        runner=TransactionRunner(c,DurableFactory(fixture.path.with_name('provider-native.json')));self.addCleanup(runner.close)
        fixture.core=c;fixture.runner=runner
        fixture.policy=replace(fixture.policy,task_limit=fixture.Limits(1000000,10),
            owner_provider_limit=fixture.Limits(1000000,15),global_limit=fixture.Limits(1000000,20))
        fixture.gov=fixture.Governor(c,runner,fixture.policy,clock=lambda:fixture.now)
        fixture.epoch=fixture.gov.start_epoch(c.local_operator(Capability.MANAGE))
        return fixture

    def test_kill_and_cost_bound_produce_zero_transport(self):
        port=self.port()
        with self.assertRaises((ValueError,ProviderError)):port.request(self.request)
        self.assertEqual([],self.calls)
        self.with_money_policy(self.fx)
        self.fx.gov.set_kill(self.fx.principal(Capability.MANAGE),True)
        with self.assertRaises((ValueError,ProviderError)):self.port().request(self.request)
        self.assertEqual([],self.calls)

    def test_late_kill_after_reservation_before_marker_produces_zero_transport(self):
        self.with_money_policy(self.fx)
        self.before=lambda:self.fx.gov.set_kill(self.fx.principal(Capability.MANAGE),True)
        with self.assertRaises((ValueError,ProviderError)):self.port().request(self.request)
        self.assertEqual([],self.calls)
        self.assertEqual(0,self.fx.inspect()['exposure']['global']['money_nano'])

    def test_provider_timeout_retains_money_risk_and_never_falls_back(self):
        self.with_money_policy(self.fx);self.transport_fails=True
        port=self.port()
        with self.assertRaises(ProviderError):port.request(self.request)
        state=self.fx.inspect()
        self.assertEqual('UNKNOWN',state['reservations']['wire-request']['state'])
        self.assertGreater(state['exposure']['global']['money_nano'],0)
        self.assertEqual(1,state['exposure']['global']['risk_units'])
        with self.assertRaises(ProviderError):port.request(self.request)
        self.assertEqual(1,len(self.calls))

    def test_native_money_estimate_rejects_invalid_amount_types_and_overflow(self):
        from runtime.providers.nebius_routing import conservative_nano_usd
        for value in (-1,True,2**63,1.5):
            with self.subTest(value=value),self.assertRaises(ProviderError):
                conservative_nano_usd(value,1,Decimal('1'),Decimal('1'))

    def test_extreme_decimal_exponents_are_rejected_before_integer_expansion(self):
        from runtime.providers.nebius_routing import conservative_nano_usd
        for rate in (Decimal('1e-100'),Decimal('Infinity'),Decimal('-1')):
            with self.subTest(rate=str(rate)),self.assertRaises(ProviderError):
                conservative_nano_usd(1,1,rate,Decimal('0'))

    def test_lost_dispatch_ack_is_provider_unknown_with_zero_transport_and_held_exposure(self):
        from test_memory_patch_persistence_ports import FakeFactory
        from runtime.memory_patch.persistence.ports import TransactionRunner
        self.with_money_policy(self.fx)
        factory=FakeFactory();runner=TransactionRunner(self.fx.core,factory);self.addCleanup(runner.close)
        self.fx.runner=runner
        self.fx.gov=self.fx.Governor(self.fx.core,runner,self.fx.policy,clock=lambda:self.fx.now)
        self.fx.epoch=self.fx.gov.start_epoch(self.fx.principal(Capability.MANAGE))
        self.before=lambda:factory.commit_faults.append('unknown_after_commit')
        port=self.port()
        with self.assertRaises(ProviderError) as caught:port.request(self.request)
        self.assertEqual('GOVERNOR_COMMIT_UNKNOWN',caught.exception.code)
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual([],self.calls)
        self.assertEqual('DISPATCHED',self.fx.inspect()['reservations']['wire-request']['state'])
        self.assertGreater(self.fx.inspect()['exposure']['global']['money_nano'],0)
        with self.assertRaises(ProviderError):port.request(self.request)
        self.assertEqual([],self.calls)

    def test_settlement_binds_full_native_response_receipt_without_storing_its_content(self):
        self.with_money_policy(self.fx)
        response=self.port().request(self.request)
        entry=self.fx.inspect()['reservations']['wire-request']
        self.assertEqual(canonical_sha256(response),entry['evidence_digest'])
        self.assertNotIn('Fixture architecture advice',json.dumps(entry))

    def test_known_governor_denial_releases_original_lite_journal_units_without_model_call(self):
        import test_nv02_lite as lite_fixtures
        from runtime.mission.contracts import MissionContext
        host=lite_fixtures.NV02Tests();host.setUp();self.addCleanup(host.doCleanups)
        host.context=MissionContext(self.fx.policy.scope,frozenset({'fixture'}),'CONTRACT_TEST')
        profile=replace(host.profile,owner_scope=self.fx.policy.scope,provider_id='nebius',model_id=MODEL,route_role='FAST',
            budget=LiteBudget(max_output_tokens=128,request_timeout_seconds=20))
        runtime=host.runtime(profile=profile,provider=self.port())
        host.changed(runtime)
        self.assertEqual('RELEASED',runtime._lite_scheduler.journal.reservations()[0]['status'])
        self.assertEqual(0,runtime.lite_status()['model_calls'])
        self.assertEqual([],self.calls)

    def _late_accounting_fault(self,mode):
        self.with_money_policy(self.fx)
        if mode == 'epoch':
            self.before=lambda:self.fx.gov.start_epoch(self.fx.principal(Capability.MANAGE))
        else:
            def unsafe_clock():self.fx.now+=self.fx.policy.max_clock_step_seconds+1
            self.before=unsafe_clock
        import test_nv02_lite as lite_fixtures
        from runtime.mission.contracts import MissionContext
        host=lite_fixtures.NV02Tests();host.setUp();self.addCleanup(host.doCleanups)
        host.context=MissionContext(self.fx.policy.scope,frozenset({'fixture'}),'CONTRACT_TEST')
        profile=replace(host.profile,owner_scope=self.fx.policy.scope,provider_id='nebius',model_id=MODEL,route_role='FAST',
            budget=LiteBudget(max_output_tokens=128,request_timeout_seconds=20))
        runtime=host.runtime(profile=profile,provider=self.port())
        host.changed(runtime)
        self.assertEqual('UNKNOWN',runtime._lite_scheduler.journal.reservations()[0]['status'])
        self.assertEqual(0,runtime.lite_status()['model_calls'])
        self.assertEqual([],self.calls)
        self.assertGreater(self.fx.inspect()['exposure']['global']['money_nano'],0)

    def test_late_epoch_cleanup_failure_keeps_unknown_with_zero_model_calls(self):
        self._late_accounting_fault('epoch')

    def test_late_clock_cleanup_failure_keeps_unknown_with_zero_model_calls(self):
        self._late_accounting_fault('clock')

    def _closed_native_fault(self,mode):
        from runtime.memory_patch.persistence.ports import TransactionRunner
        self.with_money_policy(self.fx);port=self.port()
        def expire():
            self.fx.core._clock=lambda:datetime(2030,1,1,tzinfo=timezone.utc)+timedelta(seconds=600)
        if mode == 'expired':expire()
        elif mode == 'late_expired':self.before=expire
        else:
            unconfigured=TransactionRunner(self.fx.core);self.addCleanup(unconfigured.close)
            self.fx.gov.runner=unconfigured
        import test_nv02_lite as lite_fixtures
        from runtime.mission.contracts import MissionContext
        host=lite_fixtures.NV02Tests();host.setUp();self.addCleanup(host.doCleanups)
        host.context=MissionContext(self.fx.policy.scope,frozenset({'fixture'}),'CONTRACT_TEST')
        profile=replace(host.profile,owner_scope=self.fx.policy.scope,provider_id='nebius',model_id=MODEL,route_role='FAST',
            budget=LiteBudget(max_output_tokens=128,request_timeout_seconds=20))
        runtime=host.runtime(profile=profile,provider=port);host.changed(runtime)
        self.assertEqual('UNKNOWN',runtime._lite_scheduler.journal.reservations()[0]['status'])
        self.assertEqual([],self.calls)
        self.assertEqual(0,runtime.lite_status()['model_calls'])

    def test_expired_native_principal_denies_before_transport_without_counting_model(self):
        self._closed_native_fault('expired')

    def test_native_backend_unconfigured_denies_before_transport_without_counting_model(self):
        self._closed_native_fault('backend')

    def test_native_principal_expiry_at_marker_keeps_unknown_without_counting_model(self):
        self._closed_native_fault('late_expired')

    def test_native_principal_expiry_after_transport_is_typed_unknown_and_holds_exposure(self):
        self.with_money_policy(self.fx)
        self.after=lambda:setattr(self.fx.core,'_clock',lambda:datetime(2030,1,1,tzinfo=timezone.utc)+timedelta(seconds=600))
        with self.assertRaises(ProviderError) as caught:self.port().request(self.request)
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertTrue(caught.exception.transport_attempted)
        self.assertEqual(1,len(self.calls))
        self.assertEqual('DISPATCHED',self.fx.inspect()['reservations']['wire-request']['state'])
        self.assertGreater(self.fx.inspect()['exposure']['global']['money_nano'],0)
