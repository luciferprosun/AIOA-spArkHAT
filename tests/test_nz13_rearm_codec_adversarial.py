"""Closed REARM parser and current-owner binding adversaries on the real Core."""
import json
import unittest
from dataclasses import replace

import test_nz13_portable_rearm as support
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.mission.tools import SessionGrant


class PortableRearmCodecAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.f = support.PortableRearmTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_unhashable_operation_discriminators_use_closed_schema_denial(self):
        f = self.f
        with f.f.adapter.target_guard():
            snapshot = f.f.adapter.probe()
        for discriminator in [[], {}, ['PORTABLE_REARM_DEMO_V1']]:
            operation = json.loads(canonical_json_bytes(f.task.operation))
            operation['operation_class'] = discriminator
            try:
                f.task.route.operation(operation, snapshot)
            except ValueError:
                pass
            except TypeError:
                self.fail('CLOSED_OPERATION_UNION_LEAKED_TYPE_ERROR')
            else:
                self.fail('UNRECOGNIZED_OPERATION_DISCRIMINATOR_ACCEPTED')
        self.assertEqual((1, 1, 0), f.f.executor.counters())

    def test_wrong_owner_assignment_session_task_scope_epoch_and_target_bindings_deny_before_start(self):
        f = self.f
        mutations = [
            lambda p: p.update(principal_session_id='d' * 64),
            lambda p: p['request'].update(assignment_revision=p['request']['assignment_revision'] + 1),
            lambda p: p.update(session_id='another-tool-grant'),
            lambda p: p.update(task_id='another-task'),
            lambda p: p.update(workspace='another-workspace'),
            lambda p: p.update(policy_epoch=2),
            lambda p: p.update(target_binding_digest='f' * 64),
        ]
        for index, mutate in enumerate(mutations):
            def operation(task_id, session_id, nonce, mutate=mutate):
                value = json.loads(canonical_json_bytes(f.task.operation))
                payload = value['payload']
                payload.update(task_id=task_id, session_id=session_id)
                payload['request']['decision_nonce_hash'] = canonical_sha256(nonce)
                mutate(payload)
                return value
            task = f.new_task(policy=5, operation_builder=operation, label='wrong-binding-' + str(index))
            with self.subTest(index=index), self.assertRaises(ValueError):
                f.approve(task)
        self.assertEqual(f.before_bytes, f.f.path.read_bytes())
        self.assertEqual((1, 1, 0), f.f.executor.counters())

    def test_policy5_refuses_positive_money_session_grant_before_session_registration(self):
        f = self.f
        value = {**f.task.grant.to_dict(), 'money_nano': 1}
        grant = replace(SessionGrant.parse(value), session_id='wrong-positive-money-grant')
        before = f.f.base.records()
        with self.assertRaises(ValueError):
            f.task.route.create_session(f.f.p(Capability.OWNER_APPROVAL), grant)
        self.assertEqual(before, f.f.base.records())
        self.assertEqual((1, 1, 0), f.f.executor.counters())

    def test_rearm_operation_cannot_reuse_a_consuming_release_run_id(self):
        f = self.f
        operation = json.loads(canonical_json_bytes(f.task.operation))
        operation['payload']['request']['run_id'] = f.domain.to_dict()['inventory']['receipts'][0]['run_id']
        with self.assertRaises(ValueError):
            f.f.target.PortableRearmOperation.parse(operation)
        self.assertEqual(f.before_bytes, f.f.path.read_bytes())
