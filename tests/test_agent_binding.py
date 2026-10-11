"""Bounded advisory parsing cannot introduce execution authority."""
import unittest
from runtime.mission.agent import parse_advisory, OfflineAdvisorySequence
class AgentBindingTests(unittest.TestCase):
    def test_valid_proposal(self):
        self.assertEqual('recipe-a',parse_advisory({'type':'RunRecipeProposal','recipe_id':'recipe-a','step_id':'effect'})['recipe_id'])
    def test_authority_fields_denied(self):
        for field in ('argv','cwd','env','approved','grant','path'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                parse_advisory({'type':'RunRecipeProposal','recipe_id':'recipe-a','step_id':'effect',field:'forged'})
    def test_final_text_has_no_authority(self):
        self.assertEqual('DONE',parse_advisory({'type':'FinalText','text':'DONE'})['text'])
    def test_output_bounds(self):
        with self.assertRaises(ValueError):parse_advisory({'type':'FinalText','text':'x'*1025})
        with self.assertRaises(ValueError):parse_advisory({'type':'tool','argv':['sh']})
    def test_sequence_snapshot(self):
        value={'type':'FinalText','text':'original'}
        sequence=OfflineAdvisorySequence.from_results((value,))
        value['text']='forged'
        self.assertEqual('original',sequence.results()[0]['text'])
    def test_sequence_limit(self):
        with self.assertRaises(ValueError):OfflineAdvisorySequence.from_results(({'type':'FinalText','text':'x'},)*3)

    def test_unbound_runtime_refuses_agent(self):
        from runtime.main import create_runtime
        runtime=create_runtime(inspection_only=True)
        try:
            self.assertEqual('PROVIDER_UNAVAILABLE',runtime.agent_run()['status'])
            self.assertEqual('POLICY_BLOCKED',runtime.agent_step({'type':'FinalText','text':'DONE'})['status'])
        finally:runtime.close()
    def test_unbound_inspection_does_not_import_agent_authority(self):
        import builtins
        from unittest.mock import patch
        from runtime.main import create_runtime
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            self.assertNotEqual('runtime.mission.agent', name,
                'Unbound inspection must not acquire an agent authority dependency')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded_import):
            runtime = create_runtime(inspection_only=True)
            try:
                self.assertIsNone(runtime.provider_manager)
                self.assertIsNone(runtime.executor)
                self.assertEqual('PROVIDER_UNAVAILABLE', runtime.agent_run()['status'])
            finally:
                runtime.close()
    def test_untyped_binding_does_not_initialize_provider(self):
        from unittest.mock import patch
        from runtime.main import create_runtime
        with patch('runtime.main.ProviderManager') as manager:
            with self.assertRaises(ValueError):create_runtime(agent_bindings={})
            manager.assert_not_called()


class AgentCoreBindingTests(unittest.TestCase):
    """Native durable Core with synthetic broker I/O; kernel gates run separately."""

    def setUp(self):
        from test_sandbox_core import SandboxCoreTests
        from runtime.mission.agent import CoreAgentBindings
        from runtime.mission.sandbox_linux import LinuxSandboxBroker, TrustedSandboxConfig
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
        from runtime.main import create_runtime

        self.fixture = SandboxCoreTests(
            'test_live_ack_builds_exact_stored_request_and_keeps_unknown_until_readback')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fx = self.fixture.fx
        self.route = self.fixture.route
        config = TrustedSandboxConfig(self.fixture.base.path.parent,
            canonical_json_bytes({}), canonical_sha256({}), self.fixture.registry, b'{}', b'{}')
        self.broker = LinuxSandboxBroker(config)

        def dispatch(request, release_check):
            release_check()
            self.fixture.execute(request)

        self.broker.dispatch = dispatch
        self.broker.verify = self.fixture.base.verify
        self.route.executor = self.broker
        self.route.verifier = self.broker.verify
        self.binding = CoreAgentBindings(self.route, self.fx.p(), self.fixture.grant.session_id,
            canonical_json_bytes(self.fixture.operation), self.fixture.warrant,
            self.fixture.reservation, self.fixture.binding, self.fixture.claim,
            self.fixture.response())
        self.runtime = create_runtime(agent_bindings=self.binding)
        self.addCleanup(self.runtime.close)
        self.proposal = {'type': 'RunRecipeProposal', 'recipe_id': 'tiny-python-v1',
                         'step_id': 'effect'}

    def step(self):
        return self.runtime.agent_step(self.proposal)

    def job(self):
        from runtime.core_admission import Capability
        return self.fx.gov.inspect_job(self.fx.p(Capability.READ), 'sandbox-task')

    def test_verified_core_completion_and_replay_have_one_attempt(self):
        self.assertEqual('COMPLETED', self.step()['status'])
        self.assertEqual('COMPLETED', self.step()['status'])
        self.assertEqual(1, len(self.fixture.requests))
        self.assertEqual('DONE', self.job()['state'])

    def test_model_final_text_cannot_finish_required_job(self):
        self.assertEqual('ADVISORY_ONLY', self.runtime.agent_step(
            {'type': 'FinalText', 'text': 'DONE'})['status'])
        self.assertEqual([], self.fixture.requests)
        self.assertEqual('STARTED', self.job()['state'])

    def test_wrong_step_denied_without_attempt(self):
        self.proposal['step_id'] = 'optional'
        self.assertEqual('POLICY_BLOCKED', self.step()['status'])
        self.assertEqual([], self.fixture.requests)

    def test_wrong_session_and_forged_approval_bindings_denied(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            replace(self.binding, session_id='foreign-session')
        with self.assertRaises(ValueError):
            replace(self.binding, warrant=replace(self.fixture.warrant,
                approval_digest='sha256:' + 'f' * 64))
        with self.assertRaises(ValueError):
            replace(self.binding, claim=replace(self.fixture.claim, task_id='foreign-task'))
        self.assertEqual([], self.fixture.requests)

    def test_profile_and_revision_changes_denied_without_attempt(self):
        from dataclasses import replace
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        import copy
        for field, value in (('sandbox_profile_digest', 'f' * 64), ('task_id', 'foreign-task')):
            operation = copy.deepcopy(self.fixture.operation)
            operation['payload'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(self.binding, operation_bytes=canonical_json_bytes(operation))
        operation = copy.deepcopy(self.fixture.operation)
        operation['expected_target_revision'] = 'revision-foreign'
        with self.assertRaises(ValueError):
            replace(self.binding, operation_bytes=canonical_json_bytes(operation))
        self.assertEqual([], self.fixture.requests)

    def test_expired_session_denied_without_attempt(self):
        self.fixture.base.now = self.fixture.grant.expires_at
        self.assertEqual('POLICY_BLOCKED', self.step()['status'])
        self.assertEqual([], self.fixture.requests)

    def test_expired_job_lease_denied_without_attempt(self):
        self.fx.gov.clock = lambda: self.fixture.claim.lease_until
        self.assertEqual('POLICY_BLOCKED', self.step()['status'])
        self.assertEqual([], self.fixture.requests)

    def test_stop_denied_without_attempt(self):
        from runtime.core_admission import Capability
        self.fx.gov.set_kill(self.fx.p(Capability.MANAGE), True)
        self.assertEqual('POLICY_BLOCKED', self.step()['status'])
        self.assertEqual([], self.fixture.requests)

    def test_stale_epoch_denied_without_attempt(self):
        from runtime.core_admission import Capability
        self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        self.assertEqual('POLICY_BLOCKED', self.step()['status'])
        self.assertEqual([], self.fixture.requests)

    def test_plain_chat_and_public_tools_denied_without_legacy_effect(self):
        from runtime.mission.contracts import MissionError
        for operation in (lambda: self.runtime.assistant_request('execute', mode='plain'),
                          lambda: self.runtime.run_text_request('write_file')):
            with self.assertRaises(MissionError):
                operation()
        self.assertIsNone(self.runtime.provider_manager)
        self.assertIsNone(self.runtime.executor)
        self.assertEqual([], self.fixture.requests)

    def test_lost_start_ack_remains_unknown_without_execution_or_retry(self):
        from unittest.mock import patch
        from q09_support import DurableTransaction
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        original = DurableTransaction.commit
        lost = []

        def commit(tx):
            changed = tx.snapshot != tx.factory.state
            original(tx)
            if changed and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()

        with patch.object(DurableTransaction, 'commit', commit):
            self.assertEqual('UNKNOWN', self.step()['status'])
        self.assertEqual('UNKNOWN', self.step()['status'])
        self.assertEqual([], self.fixture.requests)
        self.assertEqual('STARTED', self.job()['state'])

    def test_lost_reconciliation_ack_preserves_applied_effect_without_retry(self):
        from unittest.mock import patch
        from q09_support import DurableTransaction
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        original = DurableTransaction.commit
        lost = []

        def commit(tx):
            changed = tx.snapshot != tx.factory.state
            resolved = any(row.payload.get('schema') == 'aioa-effect-intent-v1'
                and row.payload.get('resolution') is not None for row in tx.snapshot.values())
            original(tx)
            if changed and resolved and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()

        with patch.object(DurableTransaction, 'commit', commit):
            result = self.step()
        self.assertEqual([True], lost)
        self.assertEqual('BLOCKED_COMPLETION', result['status'])
        self.assertEqual('Applied', result['effect']['outcome']['contract_type'])
        self.assertEqual('STARTED', self.job()['state'])
        self.assertEqual('COMPLETED', self.step()['status'])
        self.assertEqual(1, len(self.fixture.requests))

    def test_known_not_applied_retains_failure_and_cannot_finish(self):
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import NotApplied
        from runtime.mission.liability import Reconciliation
        self.route.dispatch(self.fx.p(), session_id=self.binding.session_id,
            warrant=self.binding.warrant, operation=self.fixture.operation,
            reservation=self.binding.reservation, completion=self.binding.completion)
        evidence = EvidenceRef('no-effect', 'no-effect-certificate', 'sha256:' + 'a' * 64, 'v1')
        self.route.verifier = lambda op, warrant: Reconciliation(warrant.operation_hash,
            NotApplied((evidence,)), evidence,
            EvidenceRef('readback', 'independent-readback', 'sha256:' + 'b' * 64, 'v1'))
        self.route.reconcile(self.fx.p(), self.binding.warrant, self.fixture.claim.governor_epoch)
        result = self.step()
        self.assertEqual('FAIL', result['status'])
        self.assertEqual('NotApplied', result['effect']['outcome']['contract_type'])
        self.assertEqual('STARTED', self.job()['state'])
        self.assertEqual(1, len(self.fixture.requests))
