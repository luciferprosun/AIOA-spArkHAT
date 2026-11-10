"""Distinct preapproved task cannot bypass retained owner/target facts by head rewind."""
import unittest
from datetime import timedelta

import test_nz13_portable_no_release as support
from nonzero_cloudops.models import LocalApprovalRequestRecord, generate_proposal_id
from test_dual_governor import MODEL

from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.adapters.cockroach.repositories import canonical_record
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import StoredRecord
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import ReservationRequest
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.tools import LocalSessionGrant
from runtime.providers.nvidia import ProviderRequest


class PortableDifferentTaskTests(unittest.TestCase):
    def setUp(self):
        self.reference = support.PortableNoReleaseTests('runTest')
        self.reference.setUp()
        self.addCleanup(self.reference.doCleanups)
        self.f = self.reference.f
        self.original_row, self.original_head = self.f.head()
        task, session = 'portable-other-task', 'portable-other-task-grant'
        request = LocalApprovalRequestRecord.create(request_id=generate_proposal_id(), proposal=self.f.proposal,
            actor_session_id=self.f.p().actor_session_id, decision_nonce_hash='c' * 64,
            requested_at=self.f.base.now, expires_at=self.f.base.now + timedelta(minutes=1))
        pack = {**self.f.domain.to_dict(), 'request': request.model_dump(mode='json')}
        domain = self.f.target.PortableDomainInput(canonical_json_bytes(pack))
        self.operation = self.f.target.PortableOperation.create(workspace=self.f.workspace, task_id=task,
            session_id=session, principal_session_id=self.f.p().actor_session_id, policy_epoch=1,
            target_binding_digest=self.f.port.binding.digest(), target_revision=self.original_head['target_revision'],
            domain_input=domain).to_dict()
        trace = FaultTrace(FaultKind.LOST_ACK, task, 'other-portable-request',
                           'sha256:' + canonical_sha256(self.operation))
        identity = classify_fault(trace).liability_id
        graph = DependencyGraph(task, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(identity,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        self.completion = TaskCompletionBinding.for_graph(self.f.base.ledger.scope, graph, 'completion')
        self.f.base.liability.initialize(self.f.p(), graph)
        advisory = ProviderRequest('other-portable-advisory', 'other-portable-trace', 'nebius', MODEL,
                                   'inert fixture metadata only', 'other-portable-budget', 128, 20)
        envelope = JobEnvelope.from_request(self.f.base.ledger.scope, task, advisory,
            deadline_at=160, money_nano=1, risk_units=0)
        self.f.base.gov.submit_job(self.f.p(Capability.MANAGE), envelope, completion=self.completion)
        claim = self.f.base.gov.claim_job(self.f.p(), task, 'other-fixture-worker', 1, lease_seconds=30)
        self.f.base.gov.begin_job(self.f.p(), claim)
        now = int(self.f.base.now.timestamp())
        grant = LocalSessionGrant(session, self.f.base.ledger.scope, self.f.workspace, 4,
            ('PORTABLE_RELEASE_ELASTIC_IP',), self.completion.digest, now, now + 120, 1, 0, 10, 20, 4096)
        self.f.route.create_session(self.f.p(Capability.OWNER_APPROVAL), grant)
        self.warrant = self.f.route.authorize_exact(self.f.p(Capability.OWNER_APPROVAL), session,
            self.operation, self.completion, graph, trace, nonce='other-task-preapproved',
            model_id=MODEL, money_nano=0, risk_units=5)
        self.session = session
        self.reservation = ReservationRequest(self.warrant.risk_reservation_id, task, 'portable-local',
            MODEL, canonical_sha256(self.operation), 0, 5)
        self.assertNotEqual(self.f.warrant.task_id, self.warrant.task_id)
        self.assertNotEqual(self.f.warrant.operation_hash, self.warrant.operation_hash)

    def other_dispatch(self):
        return self.f.route.dispatch(self.f.p(), session_id=self.session, warrant=self.warrant,
            operation=self.operation, reservation=self.reservation, completion=self.completion)

    def test_distinct_preapproved_task_is_denied_while_first_started_is_unknown(self):
        self.reference.start_lost()
        before = self.f.base.records()
        with self.assertRaisesRegex(ValueError, '^UNRESOLVED_INTENT$'):
            self.other_dispatch()
        self.assertEqual(before, self.f.base.records())
        self.f.unknown()
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())

    def test_distinct_stale_approval_is_denied_after_no_release_and_partial_head_rewind(self):
        self.reference.start_lost()
        self.reference.settle()
        current, _head = self.f.head()
        replacement = StoredRecord(current.kind, current.record_id, current.scope,
                                   self.original_row.revision, self.original_head)
        cursor = self.f.base.factory.db.execute('UPDATE core_records_v1 SET record_json=?,record_digest=?,revision=? '
            'WHERE scope_key=? AND kind=? AND record_id=? AND revision=?',
            (canonical_record(replacement), replacement.payload_digest, replacement.revision,
             canonical_json_bytes(current.scope.binding()).decode(), current.kind.value,
             current.record_id, current.revision))
        self.assertEqual(1, cursor.rowcount)
        before = self.f.base.records()
        with self.assertRaisesRegex(ValueError, '^TARGET_HISTORY_INTEGRITY$'):
            self.other_dispatch()
        self.assertEqual(before, self.f.base.records())
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
