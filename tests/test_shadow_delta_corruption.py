import unittest
from unittest.mock import patch
import test_shadow_delta as native_fixture
import test_service_receipt_graph as gf
from runtime.memory_patch.persistence.ports import TransactionView,StoredRecord,RecordKind
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.service_guard.shadow_delta import project_shadow_delta
class ShadowCorruptionTests(unittest.TestCase):
 def test_malformed_native_operation_is_unknown(self):
  fx=native_fixture.ShadowDeltaTests();fx.setUp();self.addCleanup(fx.doCleanups);fx.apply()
  original=TransactionView.get;key=fx.guard._key(fx.fx.operation_id,'receipt')
  def get(tx,kind,record_id):
   record=original(tx,kind,record_id)
   if kind is RecordKind.OPERATION and record_id==key:
    return StoredRecord(record.kind,record.record_id,record.scope,record.revision,{'operation_kind':'nv09-receipt'})
   return record
  with patch.object(TransactionView,'get',get):value=fx.certificate().as_dict()
  self.assertEqual('UNKNOWN',value['status']);self.assertTrue(value['dependent_completion_blocked'])
  self.assertEqual(1,fx.target.client.read()['effect_count'])
 def test_malformed_rehashed_context_root_is_unknown(self):
  f=gf.ReceiptGraphTests();f.setUp()
  approval={**f.outcomes['approval'],'decision_context_root':'bad'};f._store('approval',approval,200)
  intent={**f.outcomes['intent'],'approval_digest':canonical_sha256(approval)}
  intent['request_digest']=canonical_sha256({k:v for k,v in intent.items() if k!='request_digest'});f._store('intent',intent,202)
  receipt={**f.outcomes['receipt'],**intent};f._store('receipt',receipt,203)
  verified={**f.outcomes['verified'],'request_digest':intent['request_digest'],'receipt_digest':canonical_sha256(receipt)};f._store('verified',verified,204)
  value=project_shadow_delta(f.records,f.audits,policy=f.policy,operation_id=f.operation,readback=verified['measurement'],current_dependency=None).as_dict()
  self.assertEqual('UNKNOWN',value['status']);self.assertIsNone(value['decision_context_before'])
if __name__=='__main__':unittest.main(verbosity=2)
