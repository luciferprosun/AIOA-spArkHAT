"""Native safety and fail-closed matrix; no imports or reads from the oracle."""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import nonzero_cloudops
from nonzero_cloudops import ModuleConfig, NonZeroCloudOpsService, NonZeroError, module_descriptor
from nonzero_cloudops.contract import JUDGE_SHA

AVAILABLE = module_descriptor()['available']
EIP = {'resource_type': 'AWS::EC2::EIP', 'resource_id': 'eipalloc-0123456789abcdef0'}
GROUP = {'resource_type': 'AWS::EC2::SecurityGroup', 'resource_id': 'sg-0123456789abcdef0'}
if AVAILABLE:
    from nonzero_cloudops.adapters.advisory import ModelProviderTimeoutError
    from nonzero_cloudops.adapters.portable import PortableConflictError
    from nonzero_cloudops.execution import DecisionRequest
    from nonzero_cloudops.models import ResultStatus, WorkflowState
    from nonzero_cloudops.models.errors import StorageDependencyError
    from nonzero_cloudops.state.files import atomic_write_private_json
    from nonzero_cloudops.views import ResumeRequest, StartRunRequest


def decision_body(challenge, choice='APPROVED'):
    fields = ('request_id', 'run_id', 'proposal_id', 'request_hash', 'proposal_hash',
              'evidence_hash', 'proposal_version')
    return {**{field: challenge['request'][field] for field in fields},
            'decision': choice, 'decision_nonce': challenge['decision_nonce']}


class NativeDiscoveryTests(unittest.TestCase):
    def test_identity_and_capabilities(self):
        status = module_descriptor()
        self.assertEqual(status['module'], 'nonzero-cloudops')
        self.assertEqual(status['source_sha'], JUDGE_SHA)
        self.assertEqual(status['product_name'], 'AIOA spArkHAT')
        self.assertIn('execute-approved-portable', status['capabilities'])
        self.assertFalse(status['live_aws_enabled'])

    def test_disabled_and_malformed_config_have_typed_status(self):
        for config, code in [({'enabled': False}, 'NONZERO_DISABLED'),
                             ({'enabled': 'yes'}, 'NONZERO_CONFIG_INVALID'),
                             ({'backend': 'magic'}, 'NONZERO_CONFIG_INVALID'),
                             ({'max_runs': True}, 'NONZERO_CONFIG_INVALID'),
                             ({'unknown': 1}, 'NONZERO_CONFIG_INVALID'),
                             ({'aws_enabled': True}, 'NONZERO_CONFIG_INVALID'),
                             ({'request_ttl_seconds': 1}, 'NONZERO_CONFIG_INVALID'),
                             ({'expected_source_sha': '0'*40}, 'NONZERO_SOURCE_IDENTITY_MISMATCH')]:
            with self.subTest(config=config):
                self.assertEqual(module_descriptor(config)['availability_code'], code)
                with tempfile.TemporaryDirectory() as directory:
                    state = Path(directory)/'nz'
                    with self.assertRaises(NonZeroError):
                        NonZeroCloudOpsService(state, config=config)
                    self.assertFalse(state.exists())

    def test_optional_aws_is_explicit_and_never_a_fallback(self):
        for flag, code in [(False, 'NONZERO_AWS_EXPLICIT_ENABLEMENT_REQUIRED'),
                           (True, 'NONZERO_AWS_BACKEND_NOT_CERTIFIED')]:
            status = module_descriptor({'backend': 'aws', 'aws_enabled': flag})
            self.assertEqual(status['mode'], 'aws')
            self.assertEqual(status['availability_code'], code)
            self.assertFalse(status['available'])
            self.assertFalse(status['live_aws_enabled'])
        self.assertEqual(module_descriptor()['mode'], 'portable')

    def test_unsupported_interpreter_is_unavailable_without_state(self):
        with patch('nonzero_cloudops.contract.sys.version_info', (3, 10)):
            self.assertEqual(module_descriptor()['availability_code'],
                             'NONZERO_UNAVAILABLE_REQUIRES_PYTHON_3_11')
        with patch('nonzero_cloudops.contract.sys.version_info', (3, 11)):
            self.assertNotIn('python>=3.12', module_descriptor()['missing_requirements'])

    def test_production_static_independence(self):
        root = Path(nonzero_cloudops.__file__).parent
        files = [path for path in root.rglob('*.py') if 'baseline' not in path.relative_to(root).parts]
        self.assertGreater(len(files), 20)
        for path in files:
            source = path.read_text()
            with self.subTest(file=path.name):
                ast.parse(source, feature_version=(3, 11))
                self.assertNotIn('aioa_cloudops_agent', source)
                self.assertNotIn('baseline', source)
                self.assertNotIn('sys.path', source)
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        self.assertTrue(all(alias.name not in {'subprocess', 'strands', 'boto3', 'botocore'} for alias in node.names))
        self.assertFalse(any(name.startswith('aioa_cloudops_agent') for name in sys.modules))


@unittest.skipUnless(AVAILABLE, 'native nonzero extra is not installed')
class _NativeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)/'nz'
        self.now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
        self.service = NonZeroCloudOpsService(self.root, clock=lambda: self.now)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, code=200):
        status, response = self.service.request(method, path, body, operator=True)
        self.assertEqual(status, code, response)
        return response.get('result', response)

    def start(self, target=None):
        result = self.call('POST', '/api/runs', target or EIP, code=201)
        return '/api/runs/'+result['run_id']

    def approve(self, path, choice='APPROVED'):
        challenge = self.call('POST', path+'/approval-request', {})
        body = decision_body(challenge, choice)
        self.call('POST', path+'/decision', body)
        return body

    def restart(self, **options):
        self.service.close()
        self.service = NonZeroCloudOpsService(self.root, clock=lambda: self.now, **options)


class NativeFlowTests(_NativeCase):
    def test_typed_start_approve_execute_verify(self):
        first = self.service.start(StartRunRequest(**EIP), operator=True)
        self.assertIs(first.status, ResultStatus.SUCCESS)
        run = first.value.run_id
        challenge = self.service.request_approval(run, operator=True).value
        body = decision_body(challenge.model_dump(mode='json'))
        self.service.decide(DecisionRequest.model_validate(body), operator=True)
        completed = self.service.resume(run, ResumeRequest(confirm_execution=True), operator=True).value
        self.assertIs(completed.final_state, WorkflowState.SUCCESS_WITH_EVIDENCE)
        self.assertEqual(completed.verification.run_id, run)
        self.assertEqual(completed.verification.proposal_id, completed.proposal_id)
        self.assertEqual(completed.verification.receipt_hash, completed.receipt.receipt_hash)
        self.assertEqual(self.service.components.executor.mutation_calls, 1)

    def test_security_group_exact_bounded_mutation(self):
        path = self.start(GROUP)
        self.approve(path)
        result = self.call('POST', path+'/resume', {'confirm_execution': True})
        self.assertEqual(result['receipt']['operation_type'], 'REVOKE_PUBLIC_INGRESS')
        self.assertEqual(result['receipt']['after_resource']['inbound_rules'], [])
        self.assertTrue(result['receipt']['after_resource']['outbound_rules'])
        self.assertEqual(result['verification']['observed_resource'], result['receipt']['after_resource'])

    def test_clean_resource_requires_no_action(self):
        result = self.call('POST', '/api/runs', {'resource_type': 'AWS::EC2::Instance',
                          'resource_id': 'i-0123456789abcdef0'}, code=201)
        self.assertEqual(result['final_state'], 'NO_ACTION_REQUIRED')
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_tagging_stays_non_executable_recommendation(self):
        result = self.call('POST', '/api/runs', {'resource_type': 'AWS::EC2::Instance',
                          'resource_id': 'i-0fedcba9876543210'}, code=201)
        self.assertEqual(result['final_state'], 'RECOMMENDATION_ONLY')
        self.assertFalse(result['plan']['proposal']['authorizes_execution'])
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_approval_survives_restart_but_restart_does_not_execute(self):
        path = self.start()
        self.approve(path)
        self.restart()
        self.assertEqual(self.service.components.executor.mutation_calls, 0)
        self.assertEqual(self.call('GET', path)['run']['state'], 'APPROVED')
        completed = self.call('POST', path+'/resume', {'confirm_execution': True})
        self.assertEqual(completed['final_state'], 'SUCCESS_WITH_EVIDENCE')

    def test_duplicate_approval_and_concurrent_resume_do_not_repeat_mutation(self):
        path = self.start()
        body = self.approve(path)
        self.assertTrue(self.call('POST', path+'/decision', body)['reconciled'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.service.request('POST', path+'/resume',
                {'confirm_execution': True}, operator=True), range(4)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(self.service.components.executor.mutation_calls, 1)
        self.assertEqual(len({result['result']['receipt']['receipt_hash'] for _, result in results}), 1)

    def test_denial_persists_through_restart(self):
        path = self.start()
        self.approve(path, 'DENIED')
        self.restart()
        result = self.call('POST', path+'/resume', {'confirm_execution': True})
        self.assertEqual(result['final_state'], 'DENIED_BY_HUMAN')
        self.assertNotIn('receipt', result)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_old_challenge_is_invalid_after_new_challenge(self):
        path = self.start()
        old = self.call('POST', path+'/approval-request', {})
        fresh = self.call('POST', path+'/approval-request', {})
        result = self.call('POST', path+'/decision', decision_body(old), code=403)
        self.assertEqual(result['failure_code'], 'LOCAL_APPROVAL_BINDING_MISMATCH')
        self.call('POST', path+'/decision', decision_body(fresh))

    def test_every_critical_approval_binding_is_enforced(self):
        path = self.start()
        challenge = self.call('POST', path+'/approval-request', {})
        body = decision_body(challenge)
        replacements = {'request_hash': '0'*64, 'proposal_hash': '0'*64, 'evidence_hash': '0'*64,
            'proposal_version': 999, 'decision_nonce': 'wrong-'+'x'*32,
            'proposal_id': '00000000-0000-7000-8000-000000000001',
            'request_id': '00000000-0000-7000-8000-000000000002'}
        for field, value in replacements.items():
            with self.subTest(field=field):
                self.call('POST', path+'/decision', {**body, field: value}, code=403)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_proposal_a_cannot_authorize_proposal_b(self):
        first, second = self.start(), self.start(GROUP)
        a = self.call('POST', first+'/approval-request', {})
        b = self.call('POST', second+'/approval-request', {})
        forged = {**decision_body(a), 'run_id': b['request']['run_id']}
        self.call('POST', second+'/decision', forged, code=403)
        self.call('POST', second+'/resume', {'confirm_execution': True}, code=403)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_challenge_expiry_is_fail_closed(self):
        path = self.start()
        challenge = self.call('POST', path+'/approval-request', {})
        self.now += timedelta(seconds=601)
        result = self.call('POST', path+'/decision', decision_body(challenge), code=403)
        self.assertEqual(result['failure_code'], 'LOCAL_APPROVAL_EXPIRED')
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_approved_but_expired_proposal_needs_recovery(self):
        path = self.start()
        self.approve(path)
        self.now += timedelta(days=2)
        result = self.call('POST', path+'/resume', {'confirm_execution': True}, code=409)
        self.assertEqual(result['failure_code'], 'LOCAL_APPROVAL_EXPIRED_BEFORE_EXECUTION')
        self.assertEqual(self.call('GET', path)['run']['state'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_deciding_core_operator_binding_survives_restart(self):
        path = self.start()
        self.approve(path)
        self.restart(operator_id='different-core-operator')
        result = self.call('POST', path+'/resume', {'confirm_execution': True}, code=403)
        self.assertEqual(result['failure_code'], 'LOCAL_OPERATOR_SESSION_MISMATCH')

    def test_false_and_coerced_confirmation_cannot_execute(self):
        path = self.start()
        self.approve(path)
        for value in [False, 'true', 1, None]:
            with self.subTest(value=value):
                self.call('POST', path+'/resume', {'confirm_execution': value}, code=400)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)


class NativeFailureTests(_NativeCase):
    def test_tampered_source_identity_blocks_every_operation(self):
        atomic_write_private_json(self.root/'native-identity.json', {'source_sha': '0'*40})
        with self.assertRaisesRegex(NonZeroError, 'SOURCE_IDENTITY_MISMATCH'):
            self.service.ready(operator=True)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_valid_hash_chain_with_wrong_source_is_rejected(self):
        self.service.provenance.append_event('wrong_source', {'source_sha': '0'*40})
        with self.assertRaisesRegex(NonZeroError, 'SOURCE_IDENTITY_MISMATCH'):
            self.service.ready(operator=True)

    def test_state_corruption_never_falls_back_to_empty_inventory(self):
        path = self.start()
        self.approve(path)
        self.call('POST', path+'/resume', {'confirm_execution': True})
        original = self.service.components.executor.mutation_calls
        atomic_write_private_json(self.root/'inventory.json', {'invalid': 'not-an-inventory'})
        with self.assertRaisesRegex(NonZeroError, 'STATE_OR_OPERATION_UNAVAILABLE'):
            self.service.ready(operator=True)
        self.assertEqual(self.service.components.executor.mutation_calls, original)

    def test_receipt_persistence_failure_reconciles_without_second_mutation(self):
        path = self.start()
        self.approve(path)
        repository = self.service.components.repository
        original = repository.save_checkpoint

        def lose_checkpoint(checkpoint, **kwargs):
            if checkpoint.local_execution_receipt is not None:
                raise StorageDependencyError('synthetic checkpoint interruption')
            return original(checkpoint, **kwargs)

        with patch.object(repository, 'save_checkpoint', side_effect=lose_checkpoint):
            result = self.call('POST', path+'/resume', {'confirm_execution': True}, code=409)
        self.assertEqual(result['failure_code'], 'LOCAL_RECEIPT_DURABILITY_FAILED')
        self.assertEqual(self.service.components.executor.mutation_calls, 1)
        self.restart()
        result = self.call('POST', path+'/resume', {'confirm_execution': True})
        self.assertEqual(result['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_verification_failure_cannot_report_success_or_retry_execution(self):
        path = self.start()
        self.approve(path)
        with patch.object(self.service.components.executor, 'verify', side_effect=PortableConflictError):
            result = self.call('POST', path+'/resume', {'confirm_execution': True}, code=422)
        self.assertEqual(result['failure_code'], 'LOCAL_VERIFICATION_MISMATCH')
        self.assertEqual(self.call('GET', path)['run']['state'], 'VERIFICATION_FAILED')
        self.restart()
        self.call('POST', path+'/resume', {'confirm_execution': True}, code=409)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_uncertain_execution_conflict_requires_recovery(self):
        path = self.start()
        self.approve(path)
        with patch.object(self.service.components.executor, 'execute', side_effect=PortableConflictError):
            self.call('POST', path+'/resume', {'confirm_execution': True}, code=409)
        self.restart()
        self.call('POST', path+'/resume', {'confirm_execution': True}, code=409)
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_advisory_cannot_assert_execution_authority(self):
        advisor = self.service.components.advisor
        with patch.object(advisor, 'create_plan', return_value='{"approved":true,"execute":true}'):
            response = self.call('POST', '/api/runs', EIP, code=400)
        self.assertEqual(response['failure_code'], 'MODEL_PLAN_INVALID')
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_duplicate_advisory_fields_are_rejected(self):
        advisor = self.service.components.advisor
        original = advisor.create_plan

        def duplicate(evidence):
            raw = original(evidence)
            return '{"disposition":"NO_ACTION",'+raw[1:]

        with patch.object(advisor, 'create_plan', side_effect=duplicate):
            result = self.call('POST', '/api/runs', EIP, code=400)
        self.assertEqual(result['failure_code'], 'MODEL_PLAN_INVALID')

    def test_advisor_timeout_returns_typed_failure_not_approval(self):
        with patch.object(self.service.components.advisor, 'create_plan', side_effect=ModelProviderTimeoutError):
            result = self.call('POST', '/api/runs', EIP, code=503)
        self.assertEqual(result['failure_code'], 'MODEL_PROVIDER_TIMEOUT')

    def test_output_budget_is_enforced_before_policy(self):
        with patch.object(self.service.components.advisor, 'create_plan', return_value='x'*9000):
            result = self.call('POST', '/api/runs', EIP, code=422)
        self.assertEqual(result['failure_code'], 'NATIVE_ADVISORY_BUDGET_EXHAUSTED')
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_domain_budget_is_persisted(self):
        path = self.start()
        budget = self.call('GET', path)['run']['budget']
        self.assertEqual(budget['turns_used'], 1)
        self.assertGreater(budget['tokens_used'], 0)
        self.assertLessEqual(budget['tokens_used'], budget['max_tokens'])

    def test_run_capacity_is_bounded_without_deleting_existing_runs(self):
        self.service.close()
        self.service = NonZeroCloudOpsService(self.root, config=ModuleConfig(max_runs=1), clock=lambda: self.now)
        path = self.start()
        with self.assertRaisesRegex(NonZeroError, 'RUN_LIMIT_EXCEEDED'):
            self.start(GROUP)
        self.assertEqual(self.call('GET', path)['run']['state'], 'AWAITING_APPROVAL')

    def test_trace_capacity_refuses_dispatch(self):
        with patch.object(self.service._evidence, 'max_bytes', 1):
            with self.assertRaisesRegex(NonZeroError, 'EVIDENCE_QUOTA_EXCEEDED'):
                self.start()
        self.assertEqual(self.service.components.repository.run_count(), 0)

    def test_result_log_failure_never_claims_unlogged_success(self):
        append = self.service._evidence.append

        def fail_result(kind, payload):
            if kind == 'nonzero_operator_result':
                raise NonZeroError('NONZERO_PROVENANCE_WRITE_FAILED')
            return append(kind, payload)

        with patch.object(self.service._evidence, 'append', side_effect=fail_result):
            with self.assertRaisesRegex(NonZeroError, 'PROVENANCE_WRITE_FAILED'):
                self.start()
        self.assertEqual(self.service.components.executor.mutation_calls, 0)

    def test_evidence_trace_contains_binding_chain_and_no_nonce(self):
        path = self.start()
        body = self.approve(path)
        done = self.call('POST', path+'/resume', {'confirm_execution': True})
        trace = json.dumps(self.service.trace(operator=True))
        for value in [body['proposal_hash'], body['evidence_hash'], body['request_hash'],
                      done['receipt']['receipt_hash'], done['verification']['verification_hash'], JUDGE_SHA]:
            self.assertIn(value, trace)
        self.assertNotIn(body['decision_nonce'], trace)
        self.assertNotIn('decision_nonce_hash', trace)
        self.assertIn('Integrity/linkage only', trace)

    def test_direct_typed_methods_require_operator_admission(self):
        with self.assertRaisesRegex(NonZeroError, 'OPERATOR_REQUIRED'):
            self.service.start(StartRunRequest(**EIP))
        with self.assertRaisesRegex(NonZeroError, 'OPERATOR_REQUIRED'):
            self.service.ready()
        self.assertEqual(self.service.components.repository.run_count(), 0)

    def test_no_second_operator_credential_or_provider_manager(self):
        self.start()
        self.assertFalse((self.root/'operator.credential').exists())
        self.assertFalse(hasattr(self.service, '_application'))
        self.assertFalse(hasattr(self.service.components, 'provider_manager'))
        self.assertFalse(any(name.startswith(('aioa_cloudops_agent', 'strands', 'boto3')) for name in sys.modules))

    def test_existing_phase2_state_is_not_silently_authorized(self):
        legacy = Path(self.tmp.name)/'legacy'
        legacy.mkdir(mode=0o700)
        atomic_write_private_json(legacy/'durable-truth.json', {'legacy': True})
        with self.assertRaisesRegex(NonZeroError, 'LEGACY_STATE_REQUIRES_MIGRATION'):
            NonZeroCloudOpsService(legacy)
        self.assertEqual(json.loads((legacy/'durable-truth.json').read_text()), {'legacy': True})
        self.assertFalse((legacy/'native-identity.json').exists())

    def test_wrong_independent_verification_identity_never_closes_success(self):
        path = self.start()
        self.approve(path)
        original = self.service.components.executor.verify

        def wrong_proposal(receipt):
            return original(receipt).model_copy(update={'proposal_id': UUID('00000000-0000-7000-8000-000000000099')})

        with patch.object(self.service.components.executor, 'verify', side_effect=wrong_proposal):
            result = self.call('POST', path+'/resume', {'confirm_execution': True}, code=503)
        self.assertNotIn('receipt', result)
        self.assertNotEqual(self.call('GET', path)['run']['state'], 'SUCCESS_WITH_EVIDENCE')


if __name__ == '__main__':
    unittest.main()
