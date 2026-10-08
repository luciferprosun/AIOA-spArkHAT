"""One existing reversible target, independent readback and selected evidence."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes,canonical_sha256
from runtime.memory_patch.errors import MemoryPatchError
from runtime.service_guard.contracts import GuardError
from runtime.service_guard.service import CoreServiceGuard
import nv09_support as service_fixtures
import test_memory_patch_retrieval as retrieval_fixtures

class ShadowDeltaPresenceTests(unittest.TestCase):
    def test_native_shadow_delta_and_selected_dependency_projection_exist(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.memory_patch.retrieval.dependencies'))
        self.assertTrue(callable(getattr(CoreServiceGuard,'shadow_delta',None)))

class ShadowDeltaTests(unittest.TestCase):
    def setUp(self):
        from runtime.memory_patch.retrieval.dependencies import CoreSelectedContextReader
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.target=service_fixtures.LocalTarget(self.root/'target');self.addCleanup(self.target.close)
        self.fx=service_fixtures.GuardFixture(self.root/'guard',self.target.client,extra_hat_ids=('test-hat',))
        self.addCleanup(self.fx.close)
        self.memory=retrieval_fixtures.RetrievalFixture(core=self.fx.core)
        self.a=self.memory.candidate(source_id='selected-source')
        self.memory.sources.values=(self.memory.ranked_input(self.a),)
        self.context=CoreSelectedContextReader(self.memory.service,self.memory.request,(('selected-source','chunk-one'),))
        self.guard=CoreServiceGuard(self.fx.core,self.fx.runner,self.fx.policy,self.target.client,
            clock=self.fx.clock,decision_context_reader=self.context)
        self.fx.guard=self.guard
        self.fx.bindings=replace(self.fx.bindings,service_guard=replace(self.fx.bindings.service_guard,guard=self.guard))
        # The existing scheduler owns the supplied bindings; replace its same
        # GuardLoopBinding explicitly, never bypass EffectAuthorization.consume.
        self.fx.runtime._lite_scheduler.bindings=self.fx.bindings

    def reader(self):return self.fx.core.local_operator(Capability.READ)
    def certificate(self):return self.guard.shadow_delta(self.reader(),self.fx.operation_id)
    def apply(self):
        self.fx.approve();result=self.fx.tick();self.assertEqual('VERIFIED',result['status'])
        return result

    def test_single_core_context_root_is_bound_to_existing_human_approval(self):
        before=self.context.current(self.reader())
        approval=self.fx.approve()
        self.assertEqual(before.dependency_digest,approval['decision_context_root'])
        self.assertIs(self.context.core,self.fx.core)
        self.assertEqual('NONE',before.as_dict()['authority'])

    def test_expected_delta_is_literal_and_independent_readback_matches_once(self):
        self.apply();before=self.target.client.read();value=self.certificate().as_dict()
        self.assertEqual('VERIFIED_FIXTURE_DELTA',value['status']);self.assertEqual('FIXTURE',value['mode'])
        self.assertEqual('NONE',value['authority']);self.assertFalse(value['execution_authority'])
        self.assertEqual({'revision':2,'effect_count':1,'mode':'MAINTENANCE'},value['expected'])
        self.assertEqual(value['expected'],value['observed'])
        self.assertEqual([],value['discrepancies']);self.assertFalse(value['dependent_completion_blocked'])
        self.assertEqual(before,self.target.client.read())
        self.assertLessEqual(len(canonical_json_bytes(value)),8192)

    def test_certificate_replay_digest_is_exact_and_does_not_redispatch(self):
        self.apply();first=self.certificate().as_dict();raw=(self.fx.root/'native-fixture.json').read_bytes()
        second=self.certificate().as_dict()
        self.assertEqual(first,second);self.assertEqual(1,self.target.client.read()['effect_count'])
        self.assertEqual(raw,(self.fx.root/'native-fixture.json').read_bytes())

    def test_changed_selected_version_blocks_before_effect_and_completion(self):
        self.fx.approve()
        changed=self.memory.candidate(source_id='selected-source',version='revision-new',content='Changed reviewed rule')
        self.memory.sources.values=(self.memory.ranked_input(changed),)
        result=self.fx.tick()
        self.assertEqual('BLOCKED',result['status']);self.assertFalse(result['dispatch_attempted'])
        self.assertEqual('STALE_DECISION_CONTEXT',result['reason'])
        self.assertEqual(0,self.target.client.read()['effect_count'])
        value=self.certificate().as_dict()
        self.assertEqual('UNKNOWN',value['status']);self.assertTrue(value['dependent_completion_blocked'])

    def test_unrelated_registry_churn_preserves_selected_comparison_root(self):
        before=self.context.current(self.reader());approval=self.fx.approve()
        # Newly admitted current selection, changed ambient registry metadata;
        # native binding remains checked, selected identity/content unchanged.
        self.a=replace(self.a,registry_digest='9'*64)
        self.memory.sources.approve(self.a)
        other=self.memory.candidate(source_id='unselected-source',content='Unrelated fixture context')
        self.memory.sources.values=(self.memory.ranked_input(self.a),self.memory.ranked_input(other,rank=2))
        after=self.context.current(self.reader())
        self.assertEqual(before.dependency_digest,after.dependency_digest)
        self.assertNotEqual(before.bundle_ref,after.bundle_ref)
        self.assertEqual(approval['decision_context_root'],after.dependency_digest)
        self.assertEqual('VERIFIED',self.fx.tick()['status'])

    def test_withdrawn_selected_evidence_never_counts_as_current(self):
        self.fx.approve();self.memory.catalog.receipts.clear()
        result=self.fx.tick()
        self.assertEqual('BLOCKED',result['status']);self.assertFalse(result['dispatch_attempted'])
        self.assertEqual('DECISION_CONTEXT_ADMISSION_FAILED',result['reason'])
        self.assertEqual(0,self.target.client.read()['effect_count'])
        self.assertEqual('UNKNOWN',self.certificate().as_dict()['status'])

    def test_missing_readback_or_foreign_measurement_stays_unknown(self):
        self.apply()
        for value in (None,{'target_id':'foreign','scope':[],'mode':'MAINTENANCE','revision':2,'effect_count':1}):
            with self.subTest(value=bool(value)):
                with patch.object(type(self.target.client),'read',return_value=value):
                    result=self.certificate().as_dict()
                    self.assertEqual('UNKNOWN',result['status']);self.assertTrue(result['dependent_completion_blocked'])


    def test_missing_receipt_or_causal_proof_is_unknown_without_second_effect(self):
        self.apply();path=self.fx.root/'native-fixture.json';rows=json.loads(path.read_text())
        key=self.guard._key(self.fx.operation_id,'receipt')
        rows=[row for row in rows if json.loads(row[0])['record_id']!=key]
        path.write_text(json.dumps(rows))
        result=self.certificate().as_dict()
        self.assertEqual('UNKNOWN',result['status']);self.assertTrue(result['dependent_completion_blocked'])
        self.assertEqual(1,self.target.client.read()['effect_count'])

    def test_foreign_core_principal_and_unsupported_target_do_not_export(self):
        from test_memory_patch_persistence_ports import make_admission
        foreign=make_admission(owner='foreign');self.addCleanup(foreign.close)
        with self.assertRaises(ValueError):self.guard.shadow_delta(foreign.local_operator(Capability.READ),self.fx.operation_id)
        with self.assertRaises(GuardError):CoreServiceGuard(self.fx.core,self.fx.runner,self.fx.policy,
            type('ForeignPort',(),{'scope':self.fx.policy.scope,'target_id':self.fx.policy.target_id,
                'read':lambda *a:None,'receipt':lambda *a:None,'dispatch':lambda *a:None})(),
            decision_context_reader=self.context)

    def test_selected_revision_changed_at_final_boundary_has_zero_effect(self):
        original=CoreServiceGuard._boundary_check
        def boundary(guard,*args,**kwargs):
            changed=self.memory.candidate(source_id='selected-source',version='boundary-new',content='Changed at boundary')
            self.memory.sources.values=(self.memory.ranked_input(changed),)
            return original(guard,*args,**kwargs)
        self.fx.approve()
        with patch.object(CoreServiceGuard,'_boundary_check',boundary):result=self.fx.tick()
        self.assertEqual('BLOCKED',result['status']);self.assertFalse(result['dispatch_attempted'])
        self.assertEqual(0,self.target.client.read()['effect_count'])
        self.assertEqual('UNKNOWN',self.certificate().as_dict()['status'])

    def test_changed_selected_context_after_effect_is_unknown_not_redispatched(self):
        self.apply()
        changed=self.memory.candidate(source_id='selected-source',version='after-new',content='Changed after effect')
        self.memory.sources.values=(self.memory.ranked_input(changed),)
        certificate=self.certificate().as_dict()
        self.assertEqual('UNKNOWN',certificate['status'])
        self.assertIn('SELECTED_EVIDENCE_REVISION_MISMATCH',certificate['discrepancies'])
        self.assertEqual('REPLAY',self.fx.tick()['status'])
        self.assertEqual(1,self.target.client.read()['effect_count'])

    def test_unrelated_other_hat_churn_keeps_selected_root(self):
        from runtime.memory_patch.retrieval.contracts import HybridRetrievalRequest
        before=self.context.current(self.reader());self.fx.approve()
        other=HybridRetrievalRequest.admitted(self.fx.core,self.reader(),hat_id='disposable-service',query='unrelated')
        # A genuine second admitted HAT request does not become a selected fact.
        self.assertNotEqual(other.hat_scope_id,self.context.request.hat_scope_id)
        from test_memory_patch_evidence_promotion import source_spec
        spec,data=source_spec(hat_id='disposable-service',source_id='unrelated-other-hat')
        intent=self.memory.evidence.approve_capture(self.memory.capture_actor,spec)
        captured=self.memory.evidence.capture(self.memory.capture_actor,intent,source_bytes=data,artifact_bytes=data)
        self.assertIsNotNone(captured.evidence_id)
        self.assertEqual(before.dependency_digest,self.context.current(self.reader()).dependency_digest)
        self.assertEqual('VERIFIED',self.fx.tick()['status'])

    def test_missing_native_outbox_cannot_certify_complete_proof(self):
        self.apply();path=self.fx.root/'native-fixture.json';rows=json.loads(path.read_text())
        key=self.guard._key(self.fx.operation_id,'receipt')
        rows=[row for row in rows if not (json.loads(row[0])['kind']=='outbox' and json.loads(row[0])['record_id']=='nv09-outbox-'+key)]
        path.write_text(json.dumps(rows))
        self.assertEqual('UNKNOWN',self.certificate().as_dict()['status'])
        self.assertEqual(1,self.target.client.read()['effect_count'])

class ShadowProjectionContractTests(unittest.TestCase):
    def test_rehashed_agreeing_bad_delta_is_not_literal_expected_transition(self):
        import test_service_receipt_graph as graph_fixtures
        from runtime.service_guard.shadow_delta import project_shadow_delta
        fixture=graph_fixtures.ReceiptGraphTests();fixture.setUp()
        approval={**fixture.outcomes['approval'],'decision_context_root':'a'*64}
        fixture.outcomes['approval']=approval;fixture._store('approval',approval,200)
        intent={**fixture.outcomes['intent'],'approval_digest':canonical_sha256(approval)}
        intent['request_digest']=canonical_sha256({k:v for k,v in intent.items() if k!='request_digest'})
        fixture._store('intent',intent,202)
        receipt={**fixture.outcomes['receipt'],**intent,'new_revision':3,'effect_count':2}
        fixture._store('receipt',receipt,203)
        measured={**fixture.outcomes['verified']['measurement'],'revision':3,'effect_count':2}
        verified={**fixture.outcomes['verified'],'request_digest':intent['request_digest'],
            'receipt_digest':canonical_sha256(receipt),'measurement':measured,'measurement_digest':canonical_sha256(measured)}
        fixture._store('verified',verified,204)
        value=project_shadow_delta(fixture.records,fixture.audits,policy=fixture.policy,operation_id=fixture.operation,
            readback=measured,current_dependency=None).as_dict()
        self.assertEqual('UNKNOWN',value['status'])
        self.assertEqual({'revision':2,'effect_count':1,'mode':'MAINTENANCE'},value['expected'])
        self.assertIn('INDEPENDENT_READBACK_EXPECTED_DELTA_MISMATCH',value['discrepancies'])

    def test_certificate_rejects_unknown_authority_fields_even_with_valid_labels(self):
        from runtime.service_guard.shadow_delta import ShadowDeltaCertificate
        payload={'schema':'aioa.shadow-delta-certificate.v1','mode':'FIXTURE','authority':'NONE',
            'execution_authority':False,'status':'UNKNOWN','dependent_completion_blocked':True,'approved':True}
        with self.assertRaises(GuardError):ShadowDeltaCertificate(payload)

    def test_selected_snapshot_rechecks_shape_after_rehashed_tamper(self):
        from runtime.memory_patch.retrieval.dependencies import SelectedCanonicalSnapshot
        value=SelectedCanonicalSnapshot('a'*64,'b'*64,(('c'*64,'d'*64,'e'*64,0,1),),'f'*64,'0'*64,'1'*64)
        object.__setattr__(value,'selected',(('c'*64,'d'*64,'e'*64,False,1),))
        object.__setattr__(value,'dependency_digest',value._digest())
        with self.assertRaises(MemoryPatchError):value.as_dict()

    def test_changed_native_request_is_part_of_selected_dependency_root(self):
        from runtime.memory_patch.retrieval.dependencies import SelectedCanonicalSnapshot
        value=SelectedCanonicalSnapshot('a'*64,'b'*64,(('c'*64,'d'*64,'e'*64,0,1),),'f'*64,'0'*64,'1'*64)
        changed=replace(value,request_ref='2'*64)
        self.assertNotEqual(value.dependency_digest,changed.dependency_digest)
