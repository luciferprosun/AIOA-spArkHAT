"""Remote START shares the existing Core journal and owner-wide liability gate."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from q09_support import Fixture
from lab.archaioa.authority import Money
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.governor import ReservationRequest
from runtime.mission.warrant import approval_digest


class RemoteZeroIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.fx=Fixture(Path(self.tmp.name)/'records.json');self.addCleanup(self.fx.close)
        self.fx.operation.update(operation_class='GITHUB_CREATE_COMMIT_PR_V1',payload={
            'schema':'aioa.github-remote-operation.v1','principal_session_id':self.fx.p().actor_session_id,
            'policy_epoch':1,'repository_id':1445911975,'operation_id':'a'*32})
        scope=replace(self.fx.warrant.authority_scope,operation_classes=('GITHUB_CREATE_COMMIT_PR_V1',),
            monetary_ceiling=Money(Decimal(0),'USD'))
        w=replace(self.fx.warrant,operation_class='GITHUB_CREATE_COMMIT_PR_V1',authority_scope=scope,
            money_reservation_id='NONE',operation_hash='sha256:'+canonical_sha256(self.fx.operation))
        self.fx.warrant=replace(w,approval_digest=approval_digest(w))
        self.fx.request=replace(self.fx.request,money_nano=0,request_digest=canonical_sha256(self.fx.operation))
        self.fx.init()

    def start(self):
        self.assertTrue(callable(getattr(self.fx.journal,'start_remote_zero',None)))
        return self.fx.journal.start_remote_zero(self.fx.p(),self.fx.warrant,self.fx.operation,self.fx.request)

    def test_start_is_exact_one_attempt_and_cannot_be_misclassified_local_or_fixture(self):
        self.assertTrue(self.start()['remote_step_now'])
        self.assertFalse(self.start()['remote_step_now'])
        self.assertEqual('Unknown',self.fx.inspect()['outcome']['contract_type'])
        with self.assertRaises(ValueError):self.fx.journal.start_local_zero(self.fx.p(),self.fx.warrant,self.fx.operation,self.fx.request)
        with self.assertRaises(ValueError):self.fx.start()
        gov=self.fx.gov.inspect(self.fx.p(Capability.READ))
        self.assertEqual('UNKNOWN',gov['reservations'][self.fx.request.request_id]['state'])
        self.assertEqual(0,gov['exposure']['global']['money_nano'])

    def test_existing_unknown_blocks_remote_start_and_is_not_rewritten(self):
        req=ReservationRequest('old-unknown','old-task',self.fx.request.provider_id,self.fx.request.model_id,'c'*64,1,1)
        p=self.fx.p();self.fx.gov.reserve(p,req,1);self.fx.gov.dispatch_commit(p,req.request_id,1)
        self.fx.gov.mark_unknown(p,req.request_id,1,canonical_sha256('lost-old-ack'))
        before=self.fx.gov.inspect(self.fx.p(Capability.READ))
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_INTENT'):self.start()
        self.assertEqual(before,self.fx.gov.inspect(self.fx.p(Capability.READ)))
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),self.fx.warrant))

    def test_independent_reconciliation_settles_same_risk_and_never_grants_replay(self):
        self.start();result=self.fx.journal.reconcile(self.fx.p(),self.fx.warrant,1)
        self.assertEqual('Applied',result['outcome']['contract_type'])
        self.assertEqual('COMMITTED',self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'][self.fx.request.request_id]['state'])
        self.assertFalse(self.start()['remote_step_now'])


if __name__=='__main__':unittest.main()
