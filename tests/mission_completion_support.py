"""Explicit local G2 fixtures; never a product backend or human authority."""
from datetime import datetime, timezone, timedelta
from importlib.util import find_spec
from types import SimpleNamespace
import unittest

from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.outcome import Applied, NotApplied
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
from runtime.providers.nvidia import ProviderRequest, ProviderResponse
import test_dual_governor as native

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class MissionCompletionFixture(unittest.TestCase):
    def setUp(self):
        self.fx = native.DualGovernorTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.gov, self.core, self.runner = self.fx.gov, self.fx.core, self.fx.runner
        self.p = self.fx.principal()
        self.host = self.fx.principal(Capability.MANAGE)
        self.read = self.fx.principal(Capability.READ)
        self.ledger = CoreLiabilityLedger(self.core, self.runner, native.SCOPE)

    @staticmethod
    def clean_graph(task_id):
        return DependencyGraph(task_id, (DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))

    @staticmethod
    def effect_graph(task_id, *, request_id=None):
        trace = FaultTrace(FaultKind.LOST_ACK, task_id, request_id or 'request-' + task_id,
                           'sha256:' + canonical_sha256(('required-fixture-effect', task_id)))
        identity = classify_fault(trace).liability_id
        graph = DependencyGraph(task_id, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(identity,)),
            DependencyNode('verification', NodeKind.CLAIM, ('effect',)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('verification',)),
        ))
        return graph, trace, identity

    def task(self, task_id='required-task', *, graph=None, dependencies=(), initialize=True,
             required=True, start=True):
        request = ProviderRequest('request-' + task_id, 'trace-' + task_id, 'nebius', native.MODEL,
                                  'Offline advisory fixture only', 'budget-' + task_id, 128, 20)
        envelope = JobEnvelope.from_request(native.SCOPE, task_id, request,
                                           deadline_at=160, money_nano=1, risk_units=0)
        graph = graph or self.clean_graph(task_id)
        binding = None
        if required:
            self.assertIsNotNone(find_spec('runtime.mission.completion'),
                                 'Required native completion binding is not implemented')
            from runtime.mission.completion import TaskCompletionBinding
            binding = TaskCompletionBinding.for_graph(native.SCOPE, graph, 'completion', dependencies=dependencies)
            if initialize:
                self.ledger.initialize(self.p, graph)
            self.gov.submit_job(self.host, envelope, completion=binding)
        else:
            self.gov.submit_job(self.host, envelope)
        claim = self.gov.claim_job(self.p, task_id, 'worker-' + task_id, self.fx.epoch, lease_seconds=60)
        if start:
            self.assertTrue(self.gov.begin_job(self.p, claim)['fixture_step_now'])
        response = ProviderResponse(request.request_id, 'synthetic-receipt-' + task_id,
                                    native.MODEL, 101, 'stop', 100,
                                    {'summary': 'Model says done; advisory has no completion authority',
                                     'needs_attention': False},
                                    {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2})
        return SimpleNamespace(task_id=task_id, graph=graph, binding=binding, request=request,
                               envelope=envelope, claim=claim, response=response)

    def open_unknown(self, task, trace=None):
        if trace is None:
            _, trace, _ = self.effect_graph(task.task_id)
        self.ledger.record_unknown(self.p, trace, task.graph, NOW)
        return classify_fault(trace).liability_id

    def resolution(self, trace, *, applied=True):
        receipt = EvidenceRef('receipt-' + trace.task_id,
                              'receipt' if applied else 'no-effect-certificate',
                              'sha256:' + 'b' * 64, 'v1')
        readback = EvidenceRef('readback-' + trace.task_id, 'independent-readback',
                               'sha256:' + 'c' * 64, 'v1')
        outcome = Applied(receipt.evidence_id) if applied else NotApplied()
        return Reconciliation(trace.operation_digest, outcome, receipt, readback)

    def close_unknown(self, task, trace, *, applied=True, verifier=None):
        resolution = self.resolution(trace, applied=applied)
        ledger = CoreLiabilityLedger(self.core, self.runner, native.SCOPE,
                                     verifier=verifier or (lambda *_: resolution))
        return ledger.reconcile(self.p, task.task_id, classify_fault(trace).liability_id,
                                NOW + timedelta(seconds=1))

    def finish(self, task):
        return self.gov.finish_job(self.p, task.claim, task.response)

    def inspect_task(self, task):
        return self.gov.inspect_job(self.read, task.task_id)

    def assert_not_done(self, task):
        self.assertEqual('STARTED', self.inspect_task(task)['state'])
        self.assertFalse(self.gov.begin_job(self.p, task.claim)['fixture_step_now'])

    @staticmethod
    def dependency(task):
        from runtime.mission.completion import TaskDependency
        return TaskDependency(native.SCOPE, task.task_id, task.binding.graph_digest,
                              task.binding.candidate_id)
