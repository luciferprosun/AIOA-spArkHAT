"""Registered remote adapter on the existing Core, journal and governor."""
from contextlib import nullcontext
from dataclasses import replace
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric import ec
from lab.archaioa.authority import Money
from q09_support import Fixture
import test_github_remote_execution as protocol
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.git_publish import DEMO_REPOSITORY
from runtime.mission.governor import ReservationRequest
from runtime.mission.warrant import approval_digest
from runtime.mobile_gateway.wire import Identity,verify


class CoreRemoteGitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fx=Fixture(Path(self.temp.name)/'core.json');self.addCleanup(self.fx.close)
        self.protocol=protocol.RemoteExecutionTests();self.protocol.setUp()
        self.protocol.marker_assertion=lambda:self.assertTrue(self.fx.journal._run(self.fx.p(Capability.READ),
            Capability.READ,lambda tx:any(r.payload.get('state')=='GITHUB_STEP_UNKNOWN'
                for r in tx.scan(RecordKind.OPERATION,limit=1024))))
        self.identity=Identity(ec.generate_private_key(ec.SECP256R1()));self.factories=0
        from runtime.mission.git_publish import CoreRemoteGitRoute
        self.route=CoreRemoteGitRoute(self.fx.journal,plan=self.protocol.plan,base=self.protocol.base,
            identity=self.identity,api_factory=self.factory,check=self.protocol.check,
            target_guard=nullcontext,mode='OFFLINE_FIXTURE')
        operation=self.route.operation(self.fx.p().actor_session_id,1)
        self.fx.operation=operation
        scope=replace(self.fx.warrant.authority_scope,operation_classes=(operation['operation_class'],),
            target_scope=operation['target_fingerprint'],monetary_ceiling=Money(Decimal(0),'USD'),
            expires_at=self.fx.warrant.issued_at+timedelta(seconds=240))
        w=replace(self.fx.warrant,operation_class=operation['operation_class'],authority_scope=scope,
            target_fingerprint=operation['target_fingerprint'],expected_target_revision=operation['expected_target_revision'],
            decision_dependency_root=self.route.dependency_root,money_reservation_id='NONE',
            operation_hash='sha256:'+canonical_sha256(operation),expires_at=scope.expires_at)
        self.fx.warrant=replace(w,approval_digest=approval_digest(w))
        self.fx.request=replace(self.fx.request,money_nano=0,request_digest=canonical_sha256(operation),risk_units=1)
        self.fx.init()

    def factory(self,check,cancel):
        check();self.factories+=1;return self.protocol.api()

    def dispatch(self):
        return self.route.dispatch(self.fx.p(),self.fx.warrant,self.fx.operation,self.fx.request,
                                   cancel=self.protocol.cancel)

    def test_signed_durable_receipt_and_existing_outbox_after_independent_get(self):
        result=self.dispatch()
        self.assertEqual('Applied',result['outcome']['contract_type'])
        stored=self.route.result(self.fx.p(Capability.READ))
        self.assertFalse(stored['receipt']['live_verified'])
        self.assertEqual('OFFLINE_FIXTURE',stored['receipt']['mode'])
        self.assertEqual(self.protocol.commit,stored['receipt']['commit_sha'])
        verify(self.identity.spki,stored['signature'],stored['receipt'])
        self.assertEqual('COMMITTED',self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'][self.fx.request.request_id]['state'])
        self.assertFalse(self.fx.journal.delivery(self.fx.p(Capability.READ),self.fx.warrant)['grants_replay'])
        before=len(self.protocol.calls)
        self.assertFalse(self.dispatch()['remote_step_now'])
        self.assertEqual(before,len(self.protocol.calls));self.assertEqual(1,self.factories)

    def test_existing_unknown_blocks_before_credential_factory_or_any_network(self):
        p=self.fx.p();old=ReservationRequest('prior-unknown','old-task','fixture',self.fx.request.model_id,'a'*64,1,1)
        self.fx.gov.reserve(p,old,1);self.fx.gov.dispatch_commit(p,old.request_id,1)
        self.fx.gov.mark_unknown(p,old.request_id,1,'b'*64)
        before=self.fx.gov.inspect(self.fx.p(Capability.READ))
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_INTENT'):self.dispatch()
        self.assertEqual(0,self.factories);self.assertEqual([],self.protocol.calls)
        self.assertEqual(before,self.fx.gov.inspect(self.fx.p(Capability.READ)))

    def test_lost_pr_ack_leaves_unknown_and_explicit_get_reconciliation_never_replays(self):
        self.protocol.fail='/repos/'+DEMO_REPOSITORY+'/pulls'
        with self.assertRaisesRegex(ValueError,'GITHUB_WRITE_UNKNOWN_NO_RETRY'):self.dispatch()
        self.assertEqual('Unknown',self.fx.inspect()['outcome']['contract_type'])
        before=sum(m=='POST' for m,_,_ in self.protocol.calls)
        api=self.protocol.api()
        result=self.route.reconcile(self.fx.p(),self.fx.warrant,api=api,cancel=self.protocol.cancel)
        self.assertEqual('Applied',result['outcome']['contract_type'])
        self.assertEqual(before,sum(m=='POST' for m,_,_ in self.protocol.calls))
        self.assertFalse(self.dispatch()['remote_step_now'])

    def test_revoked_owner_warrant_prevents_factory_and_all_io(self):
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL),self.fx.warrant)
        with self.assertRaisesRegex(ValueError,'WARRANT_REVOKED'):self.dispatch()
        self.assertEqual(0,self.factories);self.assertEqual([],self.protocol.calls)


if __name__=='__main__':unittest.main()
