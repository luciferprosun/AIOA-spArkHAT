"""Owned offline authority/capacity regressions; no model or external target."""
import unittest

from main import create_runtime

from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.mission.governor import (
    CoreDualGovernor,
    GovernorPolicy,
    Limits,
    ReservationRequest,
)


class CapacityEquationTests(unittest.TestCase):
    def setUp(self):
        self.scope = OwnerScope('fixture', 'owner', 'project', 'mobile-status')
        self.core = CoreAdmission(LocalOwnerAssignment(
            self.scope, frozenset({Capability.READ, Capability.COMMIT, Capability.MANAGE}),
            frozenset({'project'}), frozenset({'aioa/offline-host-worker-v1'}), operator_approved=True))
        self.addCleanup(self.core.close)
        from runtime.memory_patch.persistence.ports import TransactionRunner
        self.gov = CoreDualGovernor(self.core, TransactionRunner(self.core), GovernorPolicy(
            self.scope, 'native-mobile-chat-v1', Limits(50000000, 20),
            Limits(50000000, 20), Limits(50000000, 20), max_clock_step_seconds=3600))

    def state(self, risk=40, threshold=10):
        state = self.gov._initial()
        state.update(version=1, epoch=1, last_now=100)
        state['execution_capacity'] = {
            'schema': 'aioa.governor.execution-capacity.v1',
            'capacity': {'risk_limits': {'task_limit': risk, 'owner_provider_limit': risk,
                                        'global_limit': risk}, 'sandbox_exec_failure_threshold': threshold},
            'request_id': '1' * 32, 'review_digest': '2' * 64,
            'warrant_digest': 'sha256:' + '3' * 64, 'consumption_digest': '4' * 64}
        return state

    def test_each_snapshot_uses_its_retained_risk_capacity(self):
        state = self.state()
        request = ReservationRequest('work', 'task', 'sandbox-exec', 'aioa/offline-host-worker-v1',
                                     'a' * 64, 0, 30)
        self.gov._reserve_state(state, request, 1, 100)
        self.assertEqual(30, state['reservations']['work']['risk_units'])
        # The same exposure must still fail under the immutable legacy ceiling.
        state.pop('execution_capacity')
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.gov._budgets(state)

    def test_sandbox_override_preserves_other_provider_failure_threshold(self):
        for provider, expected in (('sandbox-exec', 'CLOSED'), ('offline-host', 'OPEN')):
            state = self.state()
            for i in range(3):
                request = ReservationRequest(f'work-{i}', f'task-{i}', provider,
                                             'aioa/offline-host-worker-v1', 'a' * 64, 0, 1)
                self.gov._reserve_state(state, request, 1, 100)
                self.gov._dispatch_state(state, request.request_id, 1, 100)
                self.gov._unknown_state(state, request.request_id, 1, 'b' * 64, 100)
            self.assertEqual(expected, state['circuits'][provider]['state'], provider)

    def test_borrowed_runtime_closes_children_without_closing_native_core(self):
        runtime = create_runtime(inspection_only=True)
        runtime._owns_memory_patch_admission = False
        runtime._memory_patch_admission = self.core
        runtime.close()
        self.assertTrue(self.core.configured, 'Native still owns its admitted Core until runner drain')
        self.core.require(self.core.local_operator(Capability.READ), Capability.READ, scope=self.scope)
