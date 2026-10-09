"""One native Core, offline exact Nebius, policy and independent target readback."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from runtime.core_admission import Capability

class UnifiedPresenceTests(unittest.TestCase):
    def test_existing_reviewer_can_run_one_core_nebius_fixture(self):
        self.assertIsNotNone(importlib.util.find_spec('nv13_unified'))

class UnifiedMetadataGateTests(unittest.TestCase):
    """A missing/stale CSR receipt must fail the reviewer, never certify it."""
    def run_review(self, replacement=None):
        from unittest.mock import patch
        from nv13_unified import run_unified
        from runtime.mission.verification import CoreCommitSelectReveal
        with tempfile.TemporaryDirectory() as temp:
            if replacement is None:
                return run_unified(Path(temp))
            with patch.object(CoreCommitSelectReveal, 'inspect', replacement):
                return run_unified(Path(temp))

    def test_unknown_csr_metadata_cannot_pass_unified_reviewer(self):
        result = self.run_review(lambda *args: {'status': 'UNKNOWN', 'authority': 'NONE'})
        self.assertEqual('FAIL', result['status'])

    def test_missing_or_non_boolean_presence_cannot_pass_unified_reviewer(self):
        from runtime.mission.verification import CoreCommitSelectReveal
        original = CoreCommitSelectReveal.inspect
        for field in ('selection_present', 'receipt_present'):
            for value in (False, 1):
                with self.subTest(field=field, value=value):
                    def incomplete(service, principal, task, field=field, value=value):
                        row = original(service, principal, task)
                        row[field] = value
                        return row
                    self.assertEqual('FAIL', self.run_review(incomplete)['status'])

    def test_commit_metadata_must_bind_the_existing_advisory_receipt(self):
        from runtime.mission.verification import CoreCommitSelectReveal
        original = CoreCommitSelectReveal.inspect
        def mismatched(service, principal, task):
            row = original(service, principal, task)
            row['commit_digest'] = '0' * 64
            return row
        self.assertEqual('FAIL', self.run_review(mismatched)['status'])

    def test_restart_metadata_change_cannot_pass_unified_reviewer(self):
        from runtime.mission.verification import CoreCommitSelectReveal
        original = CoreCommitSelectReveal.inspect
        reads = []
        def changed(service, principal, task):
            row = original(service, principal, task)
            reads.append(row)
            if len(reads) > 1:
                row['commit_digest'] = '0' * 64
            return row
        self.assertEqual('FAIL', self.run_review(changed)['status'])

    def test_reviewer_exports_only_bounded_non_authorizing_csr_metadata(self):
        result = self.run_review()
        self.assertEqual('PASS', result['status'])
        self.assertIn('verification_metadata', result)
        row = result['verification_metadata']
        self.assertEqual('COMMITTED', row['status'])
        self.assertIs(True, row['selection_present'])
        self.assertIs(True, row['receipt_present'])
        self.assertLessEqual(len(json.dumps(row).encode()), 1024)
        self.assertEqual('NONE', result['authority'])
        self.assertNotIn('The reviewed policy', json.dumps(row))
        self.assertNotIn('approval', row)
        self.assertIs(True, result['checks']['csr_metadata_replay_stable'])

class UnifiedSliceTests(unittest.TestCase):
    def setUp(self):
        from nv13_unified import UnifiedFixture
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fx=UnifiedFixture(Path(self.temp.name));self.addCleanup(self.fx.close)
    def test_one_core_native_exact_provider_binds_bounded_capsule_before_human_gate(self):
        result=self.fx.prepare()
        self.assertEqual('BLOCKED',result['status']);self.assertEqual(0,self.fx.target.client.read()['effect_count'])
        self.assertEqual(1,len(self.fx.provider_calls));request=self.fx.provider_calls[0]
        self.assertEqual('nvidia/Nemotron-3_5-Lightning',request.requested_model)
        prompt=json.loads(request.messages[-1].content)
        self.assertEqual(self.fx.capsule.capsule_hash,prompt['context_capsule']['capsule_hash'])
        for component in (self.fx.gov,self.fx.guard,self.fx.protocol,self.fx.memory.service):self.assertIs(self.fx.core,component.core)
        self.assertEqual('SUPPORTED',self.fx.verdict['status']);self.assertEqual('NONE',self.fx.verdict['authority'])
        self.assertNotIn('approval',prompt['context_capsule']);self.assertFalse(self.fx.verdict['execution_authority'])
    def test_one_effect_human_binding_restart_and_replay_are_exact(self):
        self.fx.prepare();approval=self.fx.approve();self.assertEqual(self.fx.context.current(self.fx.reader).dependency_digest,approval['decision_context_root'])
        self.assertEqual('VERIFIED',self.fx.execute()['status']);before=self.fx.target.client.read()
        self.fx.reopen();self.assertEqual('REPLAY',self.fx.execute()['status'])
        self.assertEqual(before,self.fx.target.client.read());self.assertEqual(1,before['effect_count']);self.assertEqual(1,len(self.fx.provider_calls))
        self.assertEqual('VERIFIED_FIXTURE_DELTA',self.fx.guard.shadow_delta(self.fx.reader,self.fx.operation_id).as_dict()['status'])
    def test_revoked_human_approval_has_zero_effect_even_with_supported_verifier(self):
        self.fx.prepare();self.fx.approve();self.fx.guard.revoke(self.fx.core.local_operator(Capability.OWNER_APPROVAL),self.fx.operation_id)
        self.assertEqual('BLOCKED',self.fx.execute()['status']);self.assertEqual(0,self.fx.target.client.read()['effect_count'])
    def test_changed_selected_evidence_invalidates_approval_before_dispatch(self):
        self.fx.prepare();self.fx.approve();self.fx.change_source()
        self.assertEqual('BLOCKED',self.fx.execute()['status']);self.assertEqual(0,self.fx.target.client.read()['effect_count'])
    def test_wrong_target_revision_cannot_use_prior_approval(self):
        self.fx.prepare();self.fx.approve()
        from unittest.mock import patch
        from runtime.service_guard.target import LoopbackTargetClient
        original=LoopbackTargetClient.read
        def changed(client):
            row=original(client);row['revision']+=1;return row
        with patch.object(LoopbackTargetClient,'read',changed):result=self.fx.execute()
        self.assertEqual('BLOCKED',result['status']);self.assertEqual(0,self.fx.target.client.read()['effect_count'])
    def test_ui_snapshot_is_read_only_exact_and_not_authority(self):
        self.fx.prepare();self.fx.approve();self.fx.execute();before=self.fx.path.read_bytes();calls=len(self.fx.provider_calls)
        value=self.fx.console.read(self.fx.reader)
        self.assertEqual('VERIFIED_FIXTURE_DELTA',value['readback']['status']);self.assertEqual('NONE',value['authority'])
        self.assertFalse(value['execution_authority']);self.assertEqual(before,self.fx.path.read_bytes());self.assertEqual(calls,len(self.fx.provider_calls))
        self.assertNotIn(self.fx.claim,json.dumps(value));self.assertNotIn('nv09-test-owner',json.dumps(value))
    def test_lost_ack_reconciles_under_kill_without_second_dispatch(self):
        self.fx.close()
        from nv13_unified import UnifiedFixture
        self.fx=UnifiedFixture(Path(self.temp.name)/'lost',drop_ack=True);self.addCleanup(self.fx.close)
        self.fx.prepare();self.fx.approve();self.assertEqual('UNKNOWN',self.fx.execute()['status'])
        state=self.fx.gov.inspect(self.fx.reader);self.assertEqual(4,state['exposure']['global']['risk_units'])
        self.fx.gov.set_kill(self.fx.core.local_operator(Capability.MANAGE),True)
        self.assertEqual('VERIFIED',self.fx.execute()['status']);self.assertEqual(1,self.fx.target.client.read()['effect_count'])
        self.assertEqual(1,len(self.fx.provider_calls))
    def test_advisory_disagreement_never_becomes_human_authority(self):
        self.fx.fixture_claim='Unsupported model claim'
        result=self.fx.prepare();self.assertEqual('REVIEW_REQUIRED',self.fx.verdict['status'])
        self.assertEqual('BLOCKED',result['status']);self.assertEqual(0,self.fx.target.client.read()['effect_count'])
    def test_fixture_close_reaps_only_its_owned_disposable_target(self):
        process=self.fx.target.process;self.fx.close()
        self.assertIsNotNone(process.poll());self.assertTrue(process.stdout.closed);self.assertTrue(process.stderr.closed)
    def test_native_scheduler_and_journal_share_exact_nebius_profile(self):
        self.fx.prepare();scheduler=self.fx.fx.runtime._lite_scheduler
        self.assertEqual(scheduler.profile,scheduler.journal.profile)
        self.assertEqual(scheduler.profile.digest,scheduler.journal.state['manifest_digest'])
        for r in scheduler.journal.reservations():
            self.assertEqual('nebius',r['provider_id']);self.assertEqual('nvidia/Nemotron-3_5-Lightning',r['model_id'])
    def test_stable_unknown_shadow_certificate_cannot_pass_reviewer(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from runtime.service_guard.service import CoreServiceGuard
        from nv13_unified import run_unified
        row={'status':'UNKNOWN','mode':'FIXTURE','dependent_completion_blocked':True,'certificate_digest':'a'*64,'next_action':'RECONCILE_READ_ONLY_NO_REDISPATCH'}
        unknown=SimpleNamespace(certificate_digest='a'*64,as_dict=lambda:row)
        with patch.object(CoreServiceGuard,'shadow_delta',return_value=unknown):result=run_unified(Path(self.temp.name)/'unknown')
        self.assertEqual('FAIL',result['status'])
    def test_used_fixture_effect_handle_cannot_dispatch_twice(self):
        from unittest.mock import patch
        from runtime.service_guard.target import LoopbackTargetClient
        from runtime.service_guard.contracts import GuardError
        captured=[];original=LoopbackTargetClient.dispatch
        def capture(client,command,authorization=None):
            captured.append((command,authorization));return original(client,command,authorization)
        self.fx.prepare();self.fx.approve()
        with patch.object(LoopbackTargetClient,'dispatch',capture):self.assertEqual('VERIFIED',self.fx.execute()['status'])
        self.assertEqual(1,len(captured))
        with self.assertRaises(GuardError):original(self.fx.target.client,*captured[0])
        self.assertEqual(1,self.fx.target.client.read()['effect_count'])
