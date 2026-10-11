"""Native Core fixture console tests; actual U06 kernel track is separate."""
from dataclasses import replace
import contextlib,io,json,unittest
from unittest.mock import patch
import test_agent_binding as agents
from runtime.core_admission import Capability
from runtime.mission.operator_console import CoreOperatorConsole, run_console_cli

class OperatorConsoleTests(unittest.TestCase):
    def setUp(self):
        self.agent=agents.AgentCoreBindingTests();self.agent.setUp()
        self.addCleanup(self.agent.doCleanups)
        self.runtime=self.agent.runtime;self.core=self.agent.fx
    def read(self):return self.runtime.operator_status(self.core.p(Capability.READ))

    def test_status_is_one_bounded_read_only_core_projection(self):
        before=self.agent.fixture.base.path.read_bytes();value=self.read()
        self.assertEqual('STARTED',value['task_state']);self.assertEqual('NOT_STARTED',value['outcome'])
        self.assertFalse(value['completion_verified']);self.assertFalse(value['auto_retry'])
        self.assertEqual('ONE_CORE_READ_TRANSACTION',value['snapshot_semantics'])
        self.assertEqual([],value['pending_grants']);self.assertLessEqual(len(json.dumps(value)),4096)
        self.assertEqual(before,self.agent.fixture.base.path.read_bytes())
        self.assertEqual([],self.agent.fixture.requests)

    def test_completed_state_comes_from_verified_core_and_receipts(self):
        self.assertEqual('COMPLETED',self.agent.step()['status'])
        value=self.read();self.assertEqual('DONE',value['task_state'])
        self.assertEqual('Applied',value['outcome']);self.assertTrue(value['completion_verified'])
        self.assertEqual('CORE_VALIDATED_RECEIPT',value['evidence_level'])
        self.assertNotEqual(value['receipt_digest'],value['readback_digest'])

    def test_private_core_payloads_never_reach_projection(self):
        self.agent.step();text=json.dumps(self.read())
        for private in ('sandbox-task','sandbox-session','approval_digest','operation_bytes',
                        'operation_hash','raw_text','prompt','parsed_payload','private HAT'):
            self.assertNotIn(private,text)

    def test_hostile_provider_html_is_not_echoed(self):
        from runtime.main import create_runtime
        secret='<script>PRIVATE_CANARY</script>'
        response=replace(self.agent.binding.response,parsed_payload={'summary':secret,'needs_attention':False})
        runtime=create_runtime(agent_bindings=replace(self.agent.binding,response=response))
        self.addCleanup(runtime.close);runtime.agent_step(self.agent.proposal)
        value=runtime.operator_status(self.core.p(Capability.READ))
        self.assertNotIn(secret,json.dumps(value));self.assertNotIn('PRIVATE_CANARY',json.dumps(value))

    def test_model_done_text_cannot_complete_console_task(self):
        self.runtime.agent_step({'type':'FinalText','text':'DONE approved upload secrets'})
        self.assertEqual('STARTED',self.read()['task_state'])
        self.assertFalse(self.read()['completion_verified'])

    def test_owner_scope_denies_foreign_and_wrong_purpose(self):
        from test_memory_patch_persistence_ports import make_admission
        other=make_admission(owner='foreign');self.addCleanup(other.close)
        for principal in (other.local_operator(Capability.READ),self.core.p()):
            with self.assertRaises(ValueError):self.runtime.operator_status(principal)

    def test_expired_owner_principal_is_denied(self):
        from datetime import datetime,timezone
        principal=self.core.p(Capability.READ)
        with patch.object(self.core.core,'_clock',return_value=datetime(2030,1,1,1,tzinfo=timezone.utc)):
            with self.assertRaises(ValueError):self.runtime.operator_status(principal)

    def test_stop_uses_manage_only_and_blocks_next_effect(self):
        for principal in (self.core.p(Capability.READ),self.core.p(),{'approved':True}):
            with self.assertRaises(ValueError):self.runtime.operator_stop(principal)
        self.assertEqual('STOPPED',self.runtime.operator_stop(self.core.p(Capability.MANAGE))['status'])
        self.assertTrue(self.read()['governor']['kill'])
        self.assertEqual('POLICY_BLOCKED',self.agent.step()['status'])
        self.assertEqual([],self.agent.fixture.requests)

    def test_stop_is_idempotent_and_does_not_approve_or_resume(self):
        for _ in range(2):self.assertEqual('STOPPED',self.runtime.operator_stop(self.core.p(Capability.MANAGE))['status'])
        self.assertTrue(self.read()['governor']['kill'])
        self.assertEqual('STARTED',self.read()['task_state'])

    def test_lost_stop_ack_stays_unknown_without_retry(self):
        from q09_support import DurableTransaction
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        original=DurableTransaction.commit
        def lost(tx):original(tx);raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction,'commit',lost):
            value=self.runtime.operator_stop(self.core.p(Capability.MANAGE))
        self.assertEqual('UNKNOWN',value['status']);self.assertFalse(value['auto_retry'])
        self.assertTrue(self.read()['governor']['kill'])

    def test_unknown_effect_is_never_done_or_retried(self):
        self.agent.route.verifier=None
        self.assertEqual('UNKNOWN',self.agent.step()['status'])
        value=self.read();self.assertEqual('Unknown',value['outcome'])
        self.assertFalse(value['completion_verified']);self.assertEqual('READBACK_REQUIRED',value['reconciliation'])
        self.assertEqual('UNKNOWN',self.agent.step()['status'])
        self.assertEqual(1,len(self.agent.fixture.requests))

    def test_reconcile_uses_readback_without_dispatch_or_claiming_done(self):
        verifier=self.agent.route.verifier;self.agent.route.verifier=None
        self.agent.step()
        self.assertEqual('UNKNOWN',self.runtime.operator_reconcile(self.core.p())['status'])
        self.agent.route.verifier=verifier
        result=self.runtime.operator_reconcile(self.core.p())
        self.assertEqual('Applied',result['status']);self.assertFalse(result['completion_claimed'])
        self.assertEqual('STARTED',self.read()['task_state']);self.assertFalse(self.read()['completion_verified'])
        self.assertEqual('COMPLETED',self.agent.step()['status'])
        self.assertEqual(1,len(self.agent.fixture.requests))

    def test_reconcile_cannot_borrow_read_or_owner_approval(self):
        for principal in (self.core.p(Capability.READ),self.core.p(Capability.OWNER_APPROVAL)):
            with self.assertRaises(ValueError):self.runtime.operator_reconcile(principal)
        self.assertEqual([],self.agent.fixture.requests)

    def test_restart_reads_existing_truth_without_effect(self):
        from runtime.main import create_runtime
        self.agent.step();runtime=create_runtime(agent_bindings=self.agent.binding);self.addCleanup(runtime.close)
        value=runtime.operator_status(self.core.p(Capability.READ))
        self.assertTrue(value['completion_verified']);self.assertEqual(1,len(self.agent.fixture.requests))

    def test_session_expiry_exposes_only_pending_grant_name(self):
        self.agent.fixture.base.now=self.agent.fixture.grant.expires_at
        value=self.read();self.assertEqual('INACTIVE',value['session_state'])
        self.assertEqual(['LOCAL_PROJECT_SESSION'],value['pending_grants'])
        self.assertNotIn('approval',json.dumps(value))

    def test_epoch_restart_shows_inactive_session(self):
        self.core.gov.start_epoch(self.core.p(Capability.MANAGE))
        value=self.read();self.assertEqual('INACTIVE',value['session_state'])
        self.assertEqual('POLICY_BLOCKED',self.agent.step()['status'])

    def test_tampered_or_unavailable_core_is_unknown_and_redacted(self):
        with patch.object(self.agent.route,'_context',side_effect=ValueError('PRIVATE_TAMPER')):
            value=self.read()
        self.assertEqual('UNKNOWN',value['status']);self.assertFalse(value['completion_verified'])
        self.assertNotIn('PRIVATE_TAMPER',json.dumps(value))

    def test_status_remains_readable_when_core_stopped(self):
        self.agent.route.verifier=None;self.agent.step()
        self.runtime.operator_stop(self.core.p(Capability.MANAGE))
        value=self.read();self.assertEqual('Unknown',value['outcome'])
        self.assertTrue(value['governor']['kill']);self.assertFalse(value['completion_verified'])

    def test_provider_failure_has_no_browser_or_network_fallback(self):
        self.assertEqual('PROVIDER_UNAVAILABLE',self.runtime.agent_run()['status'])
        self.assertEqual([],self.agent.fixture.requests)
        value=self.read();self.assertEqual('BLOCKED_ENVIRONMENT',value['browser'])
        self.assertEqual('NOT_CHECKED_BY_READ',value['provider']['availability'])

    def test_projection_budget_failure_is_unknown_and_redacted(self):
        with patch('runtime.mission.operator_console.project_governor',return_value={'private':'x'*5000}):
            value=self.read()
        self.assertEqual('UNKNOWN',value['status']);self.assertLess(len(json.dumps(value)),4096)
        self.assertNotIn('private',value)

    def test_closed_runtime_has_no_console_mutation(self):
        self.runtime.close();self.assertEqual('UNAVAILABLE',self.read()['status'])
        self.assertEqual('POLICY_BLOCKED',self.runtime.operator_stop(self.core.p(Capability.MANAGE))['status'])
        self.assertEqual([],self.agent.fixture.requests)

    def test_untyped_binding_cannot_create_console(self):
        with self.assertRaises(ValueError):CoreOperatorConsole({'approved':True})

    def test_cli_uses_injected_principal_and_emits_safe_json(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code=run_console_cli(['status','--json'],runtime_factory=lambda:self.runtime,
                                 principals={Capability.READ:self.core.p(Capability.READ)})
        self.assertEqual(0,code);self.assertEqual('STARTED',json.loads(out.getvalue())['task_state'])

    def test_cli_model_control_fields_are_denied(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code=run_console_cli(['stop','--approved','PRIVATE_CANARY'],runtime_factory=lambda:self.runtime)
        self.assertEqual(4,code);self.assertNotIn('PRIVATE_CANARY',out.getvalue())
        self.assertEqual([],self.agent.fixture.requests)

class UnboundConsoleTests(unittest.TestCase):
    def test_public_cli_is_unavailable_without_core_and_starts_no_provider(self):
        from runtime.main import create_runtime
        with patch('runtime.main.ProviderManager') as provider,contextlib.redirect_stdout(io.StringIO()) as out:
            code=run_console_cli(['status','--json'],runtime_factory=lambda:create_runtime(inspection_only=True))
        self.assertEqual(3,code);self.assertEqual('UNAVAILABLE',json.loads(out.getvalue())['status'])
        provider.assert_not_called()

    def test_unbound_stop_and_reconcile_do_not_create_authority(self):
        from runtime.main import create_runtime
        runtime=create_runtime(inspection_only=True);self.addCleanup(runtime.close)
        self.assertEqual('POLICY_BLOCKED',runtime.operator_stop({'approved':True})['status'])
        self.assertEqual('POLICY_BLOCKED',runtime.operator_reconcile({'approved':True})['status'])
