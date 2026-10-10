"""Synthetic transport data, real Core admission, no provider/effect calls."""
from dataclasses import replace
import json
import unittest
from runtime.core_admission import CoreAdmission, LocalOwnerAssignment, OwnerScope, Capability, AdmissionError
from runtime.providers.nvidia import ProviderRequest
from runtime.mcp_bridge import build_task, TaskResult, TaskState
from runtime.mcp_bridge.contracts import ContractError
from runtime.mcp_bridge.typed_advisory import ReadAdvisoryAdapter, SCHEMA

MODEL='nvidia/Nemotron-3_5-Lightning'
class TypedAdvisoryTests(unittest.TestCase):
 def setUp(self):
  self.core=CoreAdmission(LocalOwnerAssignment(OwnerScope('tenant','owner','space','slot'),frozenset({Capability.READ}),frozenset({'hat'}),frozenset({MODEL}),operator_approved=True))
  self.p=self.core.local_operator(Capability.READ)
  self.a=ReadAdvisoryAdapter(self.core)
  self.t=build_task('git.status',{},task_id='task-fixture',idempotency_key='idem-fixture')
  self.r=ProviderRequest('request-fixture','trace-fixture','nebius',MODEL,'SYNTHETIC_CONTEXT', 'reservation-fixture',128,20)
  self.b=self.a.bind(self.t,self.r,self.p)
 def result(self, **updates):
  metadata=dict(schema=SCHEMA,binding_ref=self.b,task_fingerprint=self.t.fingerprint,model_id=MODEL,finish_reason='stop',mode='OFFLINE_FIXTURE',response_sha256='1'*64,artifacts=[],questions=[])
  metadata.update(updates)
  return TaskResult(self.t.task_id,TaskState.DONE,'PRIVATE_HAT_SENTINEL',audit_refs=('PRIVATE_AUDIT_SENTINEL',),changed_files=('PRIVATE_PATH_SENTINEL',),metadata=metadata)
 def test_valid_projection_is_minimal_and_never_effect_authority(self):
  result=self.a.admit(self.b,self.result(),self.p)
  view=result.to_dict(); text=json.dumps(view)
  self.assertEqual('ADVISORY_ONLY',view['authority']);self.assertFalse(view['can_authorize_effects'])
  self.assertEqual('TRANSPORT_EVIDENCE_ONLY',view['provenance']);self.assertEqual('OFFLINE_FIXTURE',view['mode'])
  self.assertNotIn('PRIVATE_',text);self.assertNotIn('SYNTHETIC_CONTEXT',text)
 def test_task_fingerprint_mismatch_rejected(self):
  with self.assertRaises(ContractError):self.a.admit(self.b,self.result(task_fingerprint='0'*64),self.p)
 def test_task_identity_mismatch_rejected(self):
  with self.assertRaises(ContractError):self.a.admit(self.b,replace(self.result(),task_id='other'),self.p)
 def test_unknown_schema_authority_and_private_extensions_rejected(self):
  for fields in ({'schema':'future'},{'approved':True},{'hat':'PRIVATE_HAT_SENTINEL'}):
   with self.subTest(fields=fields),self.assertRaises(ContractError):self.a.admit(self.b,self.result(**fields),self.p)
 def test_exact_model_complete_stop_and_fixture_mode_required(self):
  for fields in ({'model_id':'nvidia/other'},{'finish_reason':'length'},{'mode':'LIVE'}):
   with self.subTest(fields=fields),self.assertRaises(ContractError):self.a.admit(self.b,self.result(**fields),self.p)
 def test_duplicate_delivery_is_denied(self):
  self.a.admit(self.b,self.result(),self.p)
  with self.assertRaises(ContractError):self.a.admit(self.b,self.result(),self.p)
 def test_rejected_result_does_not_consume_binding(self):
  with self.assertRaises(ContractError):self.a.admit(self.b,self.result(response_sha256='bad'),self.p)
  self.assertFalse(self.a.admit(self.b,self.result(),self.p).to_dict()['can_authorize_effects'])
 def test_forged_binding_and_foreign_core_principal_denied(self):
  with self.assertRaises(ContractError):self.a.admit('0'*64,self.result(),self.p)
  other=CoreAdmission(self.core._assignment)
  with self.assertRaises(AdmissionError):self.a.admit(self.b,self.result(),other.local_operator(Capability.READ))
 def test_mutated_task_cannot_reuse_same_native_request(self):
  self.t.payload['short']=True
  with self.assertRaises(ContractError):self.a.bind(self.t,self.r,self.p)
 def test_approval_status_and_effectful_tasks_stay_blocked(self):
  for op in ('approval.status','patch.request_apply'):
   from runtime.mcp_bridge import TaskEnvelope,RiskClass
   t=TaskEnvelope('x','commander',op,RiskClass.READ,{},'i')
   with self.assertRaises(ContractError):self.a.bind(t,self.r,self.p)
 def test_native_request_bounds_and_exact_model_scope(self):
  for fields in ({'input_text':'x'*4097},{'max_output_tokens':True},{'request_timeout':21},{'model_id':'nvidia/other'}):
   with self.subTest(fields=fields),self.assertRaises(ContractError):self.a.bind(self.t,replace(self.r,**fields),self.p)
 def test_artifact_refs_use_existing_slice_limits_and_no_plaintext(self):
  ref={'artifact_id':'00000000-0000-4000-8000-000000000001','sha256':'2'*64,'offset':0,'max_bytes':400,'max_lines':12}
  raw=replace(self.result(artifacts=[ref]),artifact_ids=(ref['artifact_id'],))
  self.assertEqual(400,self.a.admit(self.b,raw,self.p).to_dict()['artifacts'][0]['max_bytes'])
  for field,value in [('offset',1048577),('max_bytes',401),('max_lines',13),('sha256','plaintext')]:
   a=ReadAdvisoryAdapter(self.core);b=a.bind(self.t,self.r,self.p)
   with self.subTest(field=field),self.assertRaises(ContractError):a.admit(b,replace(self.result(binding_ref=b,artifacts=[dict(ref,**{field:value})]),artifact_ids=(ref['artifact_id'],)),self.p)
 def test_questions_only_allow_codes_and_digest_references(self):
  q={'code':'MISSING_EVIDENCE','evidence_digest':'3'*64}
  self.assertEqual(q,self.a.admit(self.b,self.result(questions=[q]),self.p).to_dict()['questions'][0])
  a=ReadAdvisoryAdapter(self.core);b=a.bind(self.t,self.r,self.p)
  with self.assertRaises(ContractError):a.admit(b,self.result(binding_ref=b,questions=[dict(q,prompt='PRIVATE_HAT_SENTINEL')]),self.p)
 def test_nonterminal_or_mutated_result_fails_closed(self):
  for raw in (replace(self.result(),state=TaskState.RUNNING), {'summary':'x'}):
   with self.assertRaises(ContractError):self.a.admit(self.b,raw,self.p)

if __name__=='__main__':unittest.main()
