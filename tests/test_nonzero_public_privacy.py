"""Native output projections/command handlers preserve private authority.

Historical deep privacy scenarios run through explicit trusted native fixtures.
Actual public HTTP/registry denial and privacy are tested independently in U05.
"""
import hashlib
import http.client
import json
import unittest
from unittest.mock import patch
from uuid import UUID

import test_nonzero_core_authority as authority_fixture

FORBIDDEN = frozenset({
    'actor_session_id', 'decision_nonce_hash', 'authorization', 'token',
    'credential', 'password', 'secret',
})


def assert_public_privacy(case, payload, *, challenge=False, private_values=()):
    """Recursively inspect the whole envelope; failures print paths, never values."""
    violations = []

    def walk(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                child = (*path, key)
                if key.lower() in FORBIDDEN or (
                    key.lower() == 'decision_nonce'
                    and not (challenge and child == ('result', 'decision_nonce'))
                ):
                    violations.append('.'.join(map(str, child)))
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, (*path, index))

    walk(payload, ())
    case.assertFalse(violations, 'Forbidden public field paths: '+', '.join(violations))
    serialized = json.dumps(payload)
    for value in private_values:
        case.assertTrue(bool(value) and value not in serialized, 'Private value in public output')
    if challenge:
        case.assertTrue(isinstance(payload['result']['decision_nonce'], str))
        case.assertGreaterEqual(len(payload['result']['decision_nonce']), 16)


class PrivacyAssertionTests(unittest.TestCase):
    def test_recursive_guard_rejects_every_forbidden_key_in_nested_lists(self):
        for key in sorted(FORBIDDEN | {'decision_nonce'}):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                assert_public_privacy(self, {'result': {'items': [None, {key: 'synthetic'}]}})

    def test_nonce_exception_is_exact_challenge_field_only(self):
        challenge = {'result': {'decision_nonce': 'synthetic-challenge-only'}}
        assert_public_privacy(self, challenge, challenge=True)
        with self.assertRaises(AssertionError):
            assert_public_privacy(self, challenge)
        with self.assertRaises(AssertionError):
            assert_public_privacy(self, {'result': {'decision_nonce': 'synthetic-challenge-only',
                'request': [{'decision_nonce': 'synthetic'}]}}, challenge=True)


class NativeResponseProjectionPrivacyTests(unittest.TestCase):
    def setUp(self):
        # Compose the established fixture without collecting its tests twice.
        self.core = authority_fixture.NativeOperatorAuthorityTests()
        self.core.setUp()
        self.addCleanup(self.core.tearDown)
        self.nonce = None
        self.binding_values = ()

    def check(self, body, *, challenge=False):
        private = (self.core.token, *self.binding_values)
        if self.nonce is not None and not challenge:
            private += (self.nonce,)
        assert_public_privacy(self, body, challenge=challenge, private_values=private)
        return body.get('result', body)

    def native_view(self, method, path, payload=None, *, expected=200, challenge=False):
        status,body=self.core.native_response(method,path,payload)
        self.assertEqual(expected,status,'Unexpected native projection status')
        return self.check(body,challenge=challenge)

    def native_command(self, command, *, challenge=False):
        runtime = self.core.app.runtime
        from commands.local_commands import cmd_nonzero
        result = cmd_nonzero(command, runtime)
        self.assertEqual(result.exit_code, 0, 'NonZero CLI command failed')
        return self.check(json.loads(result.message), challenge=challenge)

    def begin(self, *, cli=False, decision='APPROVED'):
        if cli:
            self.native_command('status')
            self.native_command('ready')
            started = self.native_command('start-json '+json.dumps(authority_fixture.TARGET))
        else:
            self.native_view('GET', '/api/nonzero/status')
            self.native_view('GET', '/api/nonzero/ready')
            started = self.native_view('POST', '/api/nonzero/runs', authority_fixture.TARGET, expected=201)
        self.assertEqual(started['final_state'], 'AWAITING_APPROVAL')
        run_id = started['run_id']
        self.path = '/api/nonzero/runs/'+run_id
        if cli:
            self.native_command('run '+run_id)
            challenge = self.native_command('approval '+run_id, challenge=True)
        else:
            self.native_view('GET', self.path)
            challenge = self.native_view('POST', self.path+'/approval-request', {}, challenge=True)
        self.nonce = challenge['decision_nonce']
        fields = ('request_id', 'run_id', 'proposal_id', 'request_hash', 'proposal_hash',
                  'evidence_hash', 'proposal_version')
        self.decision = {**{key: challenge['request'][key] for key in fields},
                         'decision': decision, 'decision_nonce': self.nonce}
        self.assert_binding(approved=False)
        return run_id

    def assert_binding(self, *, approved=True):
        service = self.core.app.runtime.nonzero_cloudops
        checkpoint = service.components.repository.get_checkpoint(UUID(self.path.rsplit('/', 1)[1]))
        request = checkpoint.local_approval_request
        self.assertIsNotNone(request)
        nonce_hash = hashlib.sha256(self.nonce.encode()).hexdigest()
        self.assertTrue(bool(request.actor_session_id), 'Internal session binding missing')
        self.assertTrue(request.decision_nonce_hash == nonce_hash, 'Internal nonce binding changed')
        self.binding_values = (request.actor_session_id, request.decision_nonce_hash)
        if approved:
            approval = checkpoint.local_approval
            self.assertIsNotNone(approval)
            self.assertTrue(approval.actor_session_id == request.actor_session_id,
                            'Internal decision session binding changed')
            self.assertTrue(approval.decision_nonce_hash == nonce_hash,
                            'Internal decision nonce binding changed')
            self.assertTrue(approval.request_hash == request.request_hash,
                            'Internal request binding changed')
        return checkpoint

    def approve(self):
        result = self.native_view('POST', self.path+'/decision', self.decision)
        self.assert_binding()
        return result

    def resume(self, *, expected=200):
        return self.native_view('POST', self.path+'/resume', {'confirm_execution': True}, expected=expected)

    def finish(self, done, *, mutations=1):
        checkpoint = self.assert_binding()
        # Compare booleans to keep internal values out of failure diagnostics.
        self.assertTrue(done['approval']['decision_hash'] == checkpoint.local_approval.decision_hash)
        self.assertTrue(done['approval']['request_hash'] == checkpoint.local_approval.request_hash)
        view = self.native_view('GET', self.path)
        self.assertEqual(view['run_sandbox_mutations'], mutations)
        self.assertEqual(view['evidence_integrity'], 'VERIFIED')
        trace = self.native_view('GET', '/api/nonzero/trace')
        self.assertTrue(trace['ok'])
        self.assertEqual(self.core.app.runtime._owned_cpl_fixture.requests, [])
        if mutations:
            self.assertTrue(done['verification']['observed_absent'])
            self.assertEqual(done['verification']['receipt_hash'], done['receipt']['receipt_hash'])

    def test_native_projection_approved_all_safe_projections_and_private_durable_binding(self):
        self.begin()
        self.approve()
        done = self.resume()
        self.assertEqual(done['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.finish(done)

    def test_native_projection_denied_terminal_and_restart_remain_private(self):
        self.begin(decision='DENIED')
        self.approve()
        self.core.restart_core()
        done = self.resume()
        self.assertEqual(done['final_state'], 'DENIED_BY_HUMAN')
        self.assertNotIn('receipt', done)
        self.assertNotIn('verification', done)
        self.finish(done, mutations=0)

    def test_native_projection_decision_and_completion_replay_preserve_safe_evidence(self):
        self.begin()
        self.approve()
        self.assertTrue(self.approve()['reconciled'])
        done = self.resume()
        binding = self.assert_binding().local_approval.model_dump()
        replay = self.resume()
        self.assertTrue(replay['reconciled'])
        self.assertEqual(replay['receipt'], done['receipt'])
        self.assertEqual(replay['verification'], done['verification'])
        self.assertTrue(self.assert_binding().local_approval.model_dump() == binding)
        self.assertEqual(self.core.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 1)
        self.finish(replay)

    def test_native_projection_approved_restart_recovers_private_binding_and_safe_completion(self):
        self.begin()
        self.approve()
        binding = self.assert_binding().local_approval.model_dump()
        self.core.restart_core()
        self.native_view('GET', self.path)
        self.assertEqual(self.core.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 0)
        done = self.resume()
        self.assertTrue(self.assert_binding().local_approval.model_dump() == binding)
        self.finish(done)

    def test_native_projection_post_mutation_reconciliation_preserves_proof_and_privacy(self):
        self.begin()
        self.approve()
        service = self.core.app.runtime.nonzero_cloudops
        append = service.provenance.append_event

        def fail_result(kind, payload):
            if kind == 'nonzero_operator_result':
                raise OSError('synthetic result write interruption')
            return append(kind, payload)

        with patch.object(service.provenance, 'append_event', side_effect=fail_result):
            self.resume(expected=503)
        checkpoint = self.assert_binding()
        receipt = checkpoint.local_execution_receipt.model_dump(mode='json', exclude_none=True)
        verification = checkpoint.local_verification.model_dump(mode='json', exclude_none=True)
        binding = checkpoint.local_approval.model_dump()
        self.assertEqual(service.components.executor.mutation_calls, 1)
        self.core.restart_core()
        done = self.resume()
        self.assertTrue(done['reconciled'])
        self.assertEqual(done['receipt'], receipt)
        self.assertEqual(done['verification'], verification)
        self.assertTrue(self.assert_binding().local_approval.model_dump() == binding)
        self.assertEqual(self.core.app.runtime.nonzero_cloudops.components.executor.execute_calls, 0)
        self.finish(done)

    def test_native_projection_challenge_nonce_required_and_absent_after_decision(self):
        self.begin()
        missing = {key: value for key, value in self.decision.items() if key != 'decision_nonce'}
        self.native_view('POST', self.path+'/decision', missing, expected=400)
        wrong = {**self.decision, 'decision_nonce': 'incorrect-synthetic-challenge'}
        self.native_view('POST', self.path+'/decision', wrong, expected=403)
        self.approve()
        self.finish(self.resume())

    def cli_flow(self, decision):
        run_id = self.begin(cli=True, decision=decision)
        self.native_command('decision-json '+json.dumps(self.decision))
        self.assert_binding()
        done = self.native_command('resume '+run_id+' CONFIRM')
        denied = decision == 'DENIED'
        self.assertEqual(done['final_state'], 'DENIED_BY_HUMAN' if denied else 'SUCCESS_WITH_EVIDENCE')
        replay = self.resume()
        self.assertTrue(replay['reconciled'])
        self.assertEqual({k: v for k, v in done.items() if k != 'reconciled'},
                         {k: v for k, v in replay.items() if k != 'reconciled'})
        self.native_command('run '+run_id)
        self.native_command('trace')
        self.finish(done, mutations=0 if denied else 1)

    def test_native_command_success_and_native_replay_share_safe_projection(self):
        self.cli_flow('APPROVED')

    def test_native_command_denial_and_native_replay_share_safe_projection(self):
        self.cli_flow('DENIED')

    def test_internal_completion_retains_authority_while_projection_omits_private_fields(self):
        from nonzero_cloudops.execution import ExecutionCompletion

        self.begin()
        self.approve()
        service = self.core.app.runtime.nonzero_cloudops
        resume = service.resume
        captured = []

        def capture_completion(*args, **kwargs):
            result = resume(*args, **kwargs)
            captured.append(result.value)
            return result

        with patch.object(service, 'resume', side_effect=capture_completion):
            public = self.resume()
        self.assertEqual(len(captured), 1)
        internal = captured[0]
        self.assertIsInstance(internal, ExecutionCompletion)
        approval = internal.approval.model_dump(mode='json')
        self.assertTrue({'actor_session_id', 'decision_nonce_hash'} <= approval.keys())
        self.assertTrue(bool(approval['actor_session_id']) and bool(approval['decision_nonce_hash']))
        self.assertFalse({'actor_session_id', 'decision_nonce_hash'} & public['approval'].keys())
        self.assertTrue(internal.approval == self.assert_binding().local_approval)
        self.assertEqual(public['receipt'], internal.receipt.model_dump(mode='json', exclude_none=True))
        self.assertEqual(public['verification'], internal.verification.model_dump(mode='json', exclude_none=True))
        self.finish(public)

    def cli_restart_and_replay(self, decision):
        run_id = self.begin(cli=True, decision=decision)
        self.native_command('decision-json '+json.dumps(self.decision))
        binding = self.assert_binding().local_approval.model_dump()
        self.core.restart_core()
        self.native_command('run '+run_id)
        self.assertEqual(self.core.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 0)
        done = self.native_command('resume '+run_id+' CONFIRM')
        replay = self.native_command('resume '+run_id+' CONFIRM')
        self.assertTrue(replay['reconciled'])
        self.assertEqual({k: v for k, v in done.items() if k != 'reconciled'},
                         {k: v for k, v in replay.items() if k != 'reconciled'})
        self.assertTrue(self.assert_binding().local_approval.model_dump() == binding)
        self.native_command('run '+run_id)
        self.native_command('trace')
        self.finish(replay, mutations=0 if decision == 'DENIED' else 1)

    def test_native_command_approved_restart_and_reconciled_replay_remain_private(self):
        self.cli_restart_and_replay('APPROVED')

    def test_native_command_denied_restart_and_reconciled_replay_remain_private(self):
        self.cli_restart_and_replay('DENIED')

    def test_native_command_post_mutation_recovery_preserves_private_binding_and_public_proof(self):
        run_id = self.begin(cli=True)
        self.native_command('decision-json '+json.dumps(self.decision))
        service = self.core.app.runtime.nonzero_cloudops
        append = service.provenance.append_event

        def fail_result(kind, payload):
            if kind == 'nonzero_operator_result':
                raise OSError('synthetic CLI result write interruption')
            return append(kind, payload)

        with patch.object(service.provenance, 'append_event', side_effect=fail_result):
            from commands.local_commands import cmd_nonzero
            failed = cmd_nonzero('resume '+run_id+' CONFIRM', self.core.app.runtime)
        self.assertEqual(failed.exit_code, 1)
        self.assertTrue(failed.message.startswith('NONZERO_') and failed.message.replace('_', '').isalpha(),
                        'Expected a redacted CLI failure code')
        assert_public_privacy(self, failed.message,
                              private_values=(self.core.token, self.nonce, *self.binding_values))
        checkpoint = self.assert_binding()
        binding = checkpoint.local_approval.model_dump()
        receipt = checkpoint.local_execution_receipt.model_dump(mode='json', exclude_none=True)
        verification = checkpoint.local_verification.model_dump(mode='json', exclude_none=True)
        self.assertEqual(service.components.executor.mutation_calls, 1)
        self.core.restart_core()
        done = self.native_command('resume '+run_id+' CONFIRM')
        self.assertTrue(done['reconciled'])
        self.assertEqual(done['receipt'], receipt)
        self.assertEqual(done['verification'], verification)
        self.assertTrue(self.assert_binding().local_approval.model_dump() == binding)
        self.assertEqual(self.core.app.runtime.nonzero_cloudops.components.executor.execute_calls, 0)
        self.native_command('run '+run_id)
        self.native_command('trace')
        self.finish(done)
