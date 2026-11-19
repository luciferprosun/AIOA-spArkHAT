"""Finite offline host jobs share the native job/ledger path without a provider."""
import json
import os
import subprocess
import sys
import threading
import unittest
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.outcome import Applied
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import (
    LocalCoreRecordFactory,
    LocalCoreTransaction,
    TransactionRunner,
)
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import (
    CoreDualGovernor,
    GovernorPolicy,
    Limits,
    ReservationRequest,
)
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
from runtime.mission.tools import CoreToolRoute, SessionGrant, TargetSnapshot
from runtime.mission.warrant import CoreWarrantLedger
from runtime.providers.nvidia import ProviderRequest, ProviderResponse

LOCAL_MODEL = 'aioa/offline-host-worker-v1'
LOCAL_SCHEMA = 'aioa.offline-host-job.v1'
LOCAL_OUTPUT = 'aioa.local-required-effects.v1'


class NativeOfflineJobTests(unittest.TestCase):
    def setUp(self):
        self.scope = OwnerScope('owned-fixture', 'local-owner', 'one-native', 'same-slot')
        self.now = 100
        self.core = CoreAdmission(LocalOwnerAssignment(
            self.scope, frozenset(Capability), frozenset({'owned-offline-workspace'}),
            frozenset({LOCAL_MODEL}), operator_approved=True),
            clock=lambda: datetime(2030, 1, 1, tzinfo=UTC))
        self.addCleanup(self.core.close)
        directory = os.environ.get('NZ13_NATIVE_TASK_FIXTURES')
        self.root = Path(mkdtemp(prefix='offline-job-', dir=directory))
        self.factory = LocalCoreRecordFactory(self.root / 'core.sqlite3', self.core)
        self.runner = TransactionRunner(self.core, self.factory)
        self.addCleanup(self.runner.close)
        limits = Limits(100, 20)
        self.governor = CoreDualGovernor(self.core, self.runner,
            GovernorPolicy(self.scope, 'unchanged-native-policy', limits, limits, limits),
            clock=lambda: self.now)
        self.epoch = self.governor.start_epoch(self.p(Capability.MANAGE))
        self.liability = CoreLiabilityLedger(self.core, self.runner, self.scope)
        self.warrants = CoreWarrantLedger(self.core, self.runner, self.scope,
            clock=lambda: datetime.fromtimestamp(self.now, UTC))
        self.journal = CoreIntentJournal(self.warrants, self.governor)

    def p(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def envelope(self, task='local-required-effect'):
        factory = getattr(JobEnvelope, 'for_offline_host', None)
        self.assertTrue(callable(factory), 'Honest offline host work has no admitted job profile')
        return factory(self.scope, task, request_id='local-request-' + task,
                       request_digest=canonical_sha256(('inert-local-request', task)), deadline_at=160)

    def prepare(self, task='local-required-effect', *, effect=False):
        if effect:
            trace = FaultTrace(FaultKind.LOST_ACK, task, 'local-effect', 'sha256:' + 'b' * 64)
            graph = DependencyGraph(task, (
                DependencyNode('effect', NodeKind.OPERATION, liability_ids=(classify_fault(trace).liability_id,)),
                DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        else:
            trace = None
            graph = DependencyGraph(task, (DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
        binding = TaskCompletionBinding.for_graph(self.scope, graph, 'completion')
        self.liability.initialize(self.p(), graph)
        envelope = self.envelope(task)
        self.governor.submit_job(self.p(Capability.MANAGE), envelope, completion=binding)
        claim = self.governor.claim_job(self.p(), task, 'owned-local-worker', self.epoch, lease_seconds=30)
        return envelope, claim, binding, graph, trace

    def test_local_claim_is_honest_zero_cost_and_cannot_be_restarted(self):
        envelope, claim, _binding, _graph, _trace = self.prepare()
        public = self.governor.inspect_job(self.p(Capability.READ), claim.task_id)
        self.assertEqual((LOCAL_SCHEMA, 'offline-host', LOCAL_MODEL, LOCAL_OUTPUT),
                         tuple(public['envelope'][key] for key in ('schema', 'provider_id', 'model_id', 'output_schema')))
        self.assertEqual('NOT_CERTIFIED', public['worker_certification'])
        self.assertEqual((0, 0), (public['envelope']['money_nano'], public['envelope']['risk_units']))
        reservation = self.governor.inspect(self.p(Capability.READ))['reservations'][public['reservation_id']]
        self.assertEqual(('offline-host', LOCAL_MODEL, 0, 0),
                         tuple(reservation[key] for key in ('provider_id', 'model_id', 'money_nano', 'risk_units')))
        self.assertTrue(self.governor.begin_job(self.p(), claim)['local_step_now'])
        self.assertFalse(self.governor.begin_job(self.p(), claim)['local_step_now'])
        self.assertEqual(envelope, JobEnvelope.parse(public['envelope']))

    def test_local_envelope_cannot_cross_provider_or_authority_fields(self):
        value = self.envelope().as_dict()
        for key, wrong in (('provider_id', 'nebius'), ('schema', 'aioa.offline-advisory-job.v1'),
                           ('model_id', 'nvidia/Nemotron-3_5-Lightning'), ('output_schema', 'aioa-readonly-advice-v1'),
                           ('money_nano', 1), ('risk_units', 1), ('authority', 'APPROVED'),
                           ('transport_scope', 'LIVE'), ('worker_certification', 'CERTIFIED')):
            with self.subTest(field=key), self.assertRaises(ValueError):
                JobEnvelope.parse({**value, key: wrong})
        for change in ({'money_nano': 1}, {'risk_units': 1}, {'model_id': 'other-local-model'},
                       {'max_output_tokens': 2}, {'request_timeout': 21}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.envelope(), **change)
        request = ProviderRequest('cross', 'trace', 'offline-host', LOCAL_MODEL, 'inert', 'budget', 1, 20)
        with self.assertRaises(ValueError):
            JobEnvelope.from_request(self.scope, 'cross', request, deadline_at=160, money_nano=0, risk_units=0)

    def test_local_submit_requires_admitted_model_and_completion_binding(self):
        with self.assertRaises(ValueError):
            self.governor.submit_job(self.p(Capability.MANAGE), self.envelope())
        foreign = CoreAdmission(LocalOwnerAssignment(
            self.scope, frozenset(Capability), frozenset({'owned-offline-workspace'}),
            frozenset({'nvidia/Nemotron-3_5-Lightning'}), operator_approved=True),
            clock=lambda: datetime(2030, 1, 1, tzinfo=UTC))
        self.addCleanup(foreign.close)
        with self.assertRaises(ValueError):
            self.governor.submit_job(foreign.local_operator(Capability.MANAGE), self.envelope())
        legacy = JobEnvelope(self.scope, 'legacy-job', 'request', 'a' * 64,
                             'nvidia/Nemotron-3_5-Lightning', 'aioa-readonly-advice-v1', 128, 20, 160, 1, 0)
        with self.assertRaisesRegex(ValueError, 'MODEL_BINDING_DENIED'):
            self.governor.submit_job(self.p(Capability.MANAGE), legacy)

    def test_local_completion_reads_canonical_liability_and_cannot_use_provider_advice(self):
        envelope, claim, binding, graph, trace = self.prepare(effect=True)
        self.governor.begin_job(self.p(), claim)
        self.liability.record_unknown(self.p(), trace, graph, datetime(2030, 1, 1, tzinfo=UTC))
        response = ProviderResponse(envelope.request_id, 'synthetic-advice', LOCAL_MODEL, 100, 'stop', 1,
                                    {'summary': 'done', 'needs_attention': False}, {})
        with self.assertRaises(ValueError):
            self.governor.finish_job(self.p(), claim, response)
        finish = getattr(self.governor, 'finish_offline_host_job', None)
        self.assertTrue(callable(finish), 'Offline required job cannot settle without provider impersonation')
        with self.assertRaisesRegex(ValueError, 'REQUIRED_LIABILITY_OPEN'):
            finish(self.p(), claim)
        receipt = EvidenceRef('owned-receipt', 'receipt', 'sha256:' + 'c' * 64, 'local-fixture-v1')
        readback = EvidenceRef('owned-readback', 'independent-readback', 'sha256:' + 'd' * 64, 'local-fixture-v1')
        resolution = Reconciliation(trace.operation_digest, Applied(receipt.evidence_id), receipt, readback)
        def settle(tx):
            _, state = self.liability._load(tx, trace.task_id)
            identity = classify_fault(trace).liability_id
            self.liability.apply_resolution_in_transaction(tx, trace.task_id, identity,
                datetime(2030, 1, 1, 0, 0, 1, tzinfo=UTC), resolution, state['entries'][identity])
        self.journal._run(self.p(), Capability.COMMIT, settle)
        result = finish(self.p(), claim)
        self.assertEqual(('DONE', 'COMPLETED', 'NONE', 'NOT_CERTIFIED'),
                         tuple(result[key] for key in ('state', 'task_completion', 'authority', 'worker_certification')))
        self.assertEqual(binding.digest, result['completion_proof']['binding_digest'])
        self.assertEqual(result, self.governor.inspect_job(self.p(Capability.READ), claim.task_id))
        self.assertEqual(result, finish(self.p(), claim))
        self.assertFalse(self.governor.begin_job(self.p(), claim)['local_step_now'])

    def test_source_model_expiry_and_kill_denials_preserve_local_start(self):
        """Retain the historical ID; this case proves only local lease/kill denials."""
        _envelope, claim, _binding, _graph, _trace = self.prepare()
        self.governor.begin_job(self.p(), claim)
        finish = getattr(self.governor, 'finish_offline_host_job', None)
        self.assertTrue(callable(finish), 'A local settlement path is required')
        self.governor.set_kill(self.p(Capability.MANAGE), True)
        with self.assertRaises(ValueError):
            finish(self.p(), claim)
        self.governor.set_kill(self.p(Capability.MANAGE), False)
        self.now = claim.lease_until
        with self.assertRaises(ValueError):
            finish(self.p(), claim)
        self.assertEqual('STARTED', self.governor.inspect_job(self.p(Capability.READ), claim.task_id)['state'])


    def test_provider_request_cannot_construct_the_offline_host_profile(self):
        request = ProviderRequest('cross', 'trace', 'nebius', LOCAL_MODEL,
                                  'inert', 'budget', 1, 20, LOCAL_OUTPUT)
        with self.assertRaises(ValueError):
            JobEnvelope.from_request(self.scope, 'cross', request, deadline_at=160,
                                     money_nano=0, risk_units=0)

    def test_missing_envelope_is_a_closed_denial(self):
        try:
            self.governor.submit_job(self.p(Capability.MANAGE), None)
        except (ValueError, AttributeError) as error:
            self.assertIsInstance(error, ValueError)
        else:
            self.fail('Missing envelope was admitted')

    def test_lost_local_start_ack_restarts_with_no_second_step(self):
        _envelope, claim, _binding, _graph, _trace = self.prepare()
        original = LocalCoreTransaction.commit
        def lost(tx):
            original(tx)
            raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', lost), self.assertRaises(CommitOutcomeUnknown):
            self.governor.begin_job(self.p(), claim)
        code = """import json,sys
from pathlib import Path
from datetime import datetime, timezone
source = Path(sys.argv[1])
sys.path.insert(0, str(source))
import runtime
assert Path(runtime.__file__).is_relative_to(source)
from runtime.core_admission import Capability,CoreAdmission,LocalOwnerAssignment,OwnerScope
from runtime.memory_patch.persistence.ports import TransactionRunner,LocalCoreRecordFactory
from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,Limits
from runtime.mission.job_contracts import JobClaim
value=json.loads(sys.stdin.read())
scope=OwnerScope('owned-fixture','local-owner','one-native','same-slot')
core=CoreAdmission(LocalOwnerAssignment(scope,frozenset(Capability),frozenset({'owned-offline-workspace'}),
    frozenset({'aioa/offline-host-worker-v1'}),operator_approved=True),
    clock=lambda:datetime(2030,1,1,tzinfo=timezone.utc))
runner=TransactionRunner(core,LocalCoreRecordFactory(Path(value['path']),core))
limits=Limits(100,20)
gov=CoreDualGovernor(core,runner,GovernorPolicy(scope,'unchanged-native-policy',limits,limits,limits),clock=lambda:100)
result=gov.begin_job(core.local_operator(Capability.COMMIT),JobClaim(**value['claim']))
print(json.dumps({'state':result['state'],'step':result['local_step_now'],
                  'certification':result['worker_certification']}))
runner.close();core.close()
"""
        source = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(source)], input=json.dumps({
            'path': str(self.root / 'core.sqlite3'), 'claim': asdict(claim)}), text=True,
            capture_output=True, timeout=10, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({'state': 'STARTED', 'step': False, 'certification': 'NOT_CERTIFIED'},
                         json.loads(result.stdout))

    def test_lost_local_finish_ack_is_readable_and_never_grants_another_start(self):
        _envelope, claim, _binding, _graph, _trace = self.prepare()
        self.governor.begin_job(self.p(), claim)
        original = LocalCoreTransaction.commit
        def lost(tx):
            original(tx)
            raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', lost), self.assertRaises(CommitOutcomeUnknown):
            self.governor.finish_offline_host_job(self.p(), claim)
        result = self.governor.inspect_job(self.p(Capability.READ), claim.task_id)
        self.assertEqual('DONE', result['state'])
        self.assertEqual(result, self.governor.finish_offline_host_job(self.p(), claim))
        self.assertFalse(self.governor.begin_job(self.p(), claim)['local_step_now'])


    def test_same_sqlite_job_journal_and_tool_route_require_actual_fixture_readback(self):
        """The target is an explicit inert fixture; the Core path is real SQLite."""
        snapshot = TargetSnapshot('sha256:' + 'a' * 64, 'fixture-target-1', DecisionDependencyRoot())
        target, receipts = {}, {}
        def execute(operation, warrant, _limits):
            target[operation['payload']['path']] = operation['payload']['content']
            receipts[warrant.digest()] = canonical_sha256({
                'schema': 'explicit-fixture-receipt.v1', 'operation': operation, 'target': target})
        def verify(operation, warrant):
            self.assertEqual({'src/offline.txt': 'owned inert fixture\n'}, target)
            readback = canonical_sha256({'schema': 'explicit-fixture-readback.v1',
                                         'target': target, 'warrant_digest': warrant.digest()})
            return Reconciliation(warrant.operation_hash, Applied('fixture-receipt'),
                EvidenceRef('fixture-receipt', 'receipt', 'sha256:' + receipts[warrant.digest()], 'explicit-inert-fixture-v1'),
                EvidenceRef('fixture-readback', 'independent-readback', 'sha256:' + readback, 'explicit-inert-fixture-v1'))
        guard = threading.RLock()
        route = CoreToolRoute(self.journal, self.liability, workspace='owned-offline-workspace',
            policy_revision=1, probe=lambda: snapshot, executor=execute,
            target_guard=lambda: guard, verifier=verify, clock=lambda: self.now)
        operation = route.operation({'action': 'write_file', 'path': 'src/offline.txt',
                                     'content': 'owned inert fixture\n'}, snapshot)
        task_id = 'joined-local-effect'
        trace = FaultTrace(FaultKind.LOST_ACK, task_id, 'joined-request',
                           'sha256:' + canonical_sha256(operation))
        graph = DependencyGraph(task_id, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(classify_fault(trace).liability_id,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        completion = TaskCompletionBinding.for_graph(self.scope, graph, 'completion')
        self.liability.initialize(self.p(), graph)
        self.governor.submit_job(self.p(Capability.MANAGE), self.envelope(task_id), completion=completion)
        claim = self.governor.claim_job(self.p(), task_id, 'owned-worker', self.epoch, lease_seconds=30)
        self.assertTrue(self.governor.begin_job(self.p(), claim)['local_step_now'])
        grant = SessionGrant('owned-session', self.scope, 'owned-offline-workspace', 1,
            ('PROJECT_WRITE',), completion.digest, self.now, self.now + 120, self.epoch, 1, 5, 20, 4096)
        route.create_session(self.p(Capability.OWNER_APPROVAL), grant)
        warrant = route.authorize(self.p(), grant.session_id, operation, completion, graph, trace,
            nonce='owned-local-effect-once', model_id=LOCAL_MODEL, money_nano=1, risk_units=5)
        reservation = ReservationRequest(warrant.money_reservation_id, task_id, 'synthetic',
                                         LOCAL_MODEL, canonical_sha256(operation), 1, 5)
        result = route.dispatch(self.p(), session_id=grant.session_id, warrant=warrant,
                               operation=operation, reservation=reservation, completion=completion)
        self.assertEqual(('SYNTHETIC_ONLY', 'Unknown'),
                         (result['mode'], result['outcome']['contract_type']))
        self.assertEqual({'src/offline.txt': 'owned inert fixture\n'}, target)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_LIABILITY_OPEN'):
            self.governor.finish_offline_host_job(self.p(), claim)
        self.assertEqual('Applied', route.reconcile(self.p(), warrant, self.epoch)['outcome']['contract_type'])
        result = self.governor.finish_offline_host_job(self.p(), claim)
        self.assertEqual(('DONE', 'NOT_CERTIFIED'), (result['state'], result['worker_certification']))
        intent = self.journal._run(self.p(Capability.READ), Capability.READ,
                                  lambda tx: self.journal._load(tx, warrant)[1])
        self.assertEqual('Applied', intent['outcome']['contract_type'])
        self.assertIs(route.journal, self.journal)
        self.assertIs(route.liability, self.liability)
        self.assertIs(route.runner, self.runner)
        self.assertIs(route.journal.governor, self.governor)
