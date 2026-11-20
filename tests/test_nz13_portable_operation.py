"""Closed Portable operation identity; no owner admission or physical permission."""
import copy
import importlib
import unittest

import test_nz13_portable_domain_input as facts

from runtime.memory_patch.contracts.serialization import canonical_json_bytes


class PortableOperationTests(unittest.TestCase):
    def setUp(self):
        target = importlib.import_module('runtime.mission.portable_target')
        self.api = getattr(target, 'PortableOperation', None)
        self.assertIsNotNone(self.api, 'CLOSED_PORTABLE_OPERATION_NOT_IMPLEMENTED')
        fixture = facts.PortableDomainInputTests('test_valid_exact_pack_is_facts_only_and_has_complete_storage_root')
        fixture.setUp()
        self.pack = fixture.parse()
        self.payload = {
            'operation_class': 'PORTABLE_RELEASE_ELASTIC_IP',
            'target_fingerprint': 'sha256:' + self.pack.state_root,
            'expected_target_revision': 'core-target-fixture-00000000',
            'payload': {
                'schema': 'aioa.portable-operation.v1', 'tool': 'release_elastic_ip',
                'workspace': 'workspace-1', 'task_id': 'portable-task', 'session_id': 'owner-task-grant',
                'principal_session_id': 'a' * 64, 'policy_epoch': 1,
                'target_binding_digest': 'c' * 64, 'domain_input': self.pack.to_dict(),
            },
        }

    def refused(self, value, reason):
        with self.assertRaisesRegex(ValueError, '^' + reason + '$'):
            self.api.parse(value)

    def test_exact_operation_roundtrip_has_no_authority(self):
        parsed = self.api.parse(self.payload)
        self.assertEqual(self.payload, parsed.to_dict())
        self.assertEqual('NONE', parsed.authority)
        self.assertEqual(self.pack.canonical_input, parsed.domain_input.canonical_input)

    def test_capture_is_immutable_and_detached_from_nested_caller_values(self):
        parsed = self.api.parse(self.payload)
        original = copy.deepcopy(self.payload)
        self.payload['payload']['domain_input']['inventory']['resources'].clear()
        parsed.to_dict()['payload'].clear()
        self.assertEqual(original, parsed.to_dict())
        with self.assertRaises(AttributeError):
            parsed.canonical_operation = b'changed'

    def test_host_builder_is_the_same_closed_codec(self):
        parsed = self.api.create(workspace='workspace-1', task_id='portable-task',
            session_id='owner-task-grant', principal_session_id='a' * 64, policy_epoch=1,
            target_binding_digest='c' * 64, target_revision='core-target-fixture-00000000',
            domain_input=self.pack)
        self.assertEqual(self.payload, parsed.to_dict())

    def test_only_one_distinct_operation_class_is_accepted(self):
        for kind in ['PROJECT_WRITE', 'WORKSPACE_WRITE', 'SANDBOX_EXEC', 'REVOKE_PUBLIC_INGRESS']:
            with self.subTest(kind=kind):
                self.refused({**self.payload, 'operation_class': kind}, 'PORTABLE_OPERATION_SHAPE')

    def test_model_authority_argv_paths_and_other_payload_fields_are_not_registration(self):
        for name, data in [('approved', True), ('argv', ['true']), ('path', 'inventory.json'),
                           ('provider', 'meta'), ('release', True)]:
            value = copy.deepcopy(self.payload)
            value['payload'][name] = data
            with self.subTest(name=name):
                self.refused(value, 'PORTABLE_OPERATION_SHAPE')

    def test_tool_or_schema_cannot_impersonate_existing_tool_variants(self):
        for key, item in [('schema', 'aioa.local-operation.v2'), ('tool', 'write_file'),
                          ('tool', 'run_recipe')]:
            value = copy.deepcopy(self.payload)
            value['payload'][key] = item
            with self.subTest(key=key, item=item):
                self.refused(value, 'PORTABLE_OPERATION_SHAPE')

    def test_complete_before_root_must_equal_the_operation_fingerprint(self):
        self.refused({**self.payload, 'target_fingerprint': 'sha256:' + 'd' * 64},
                     'PORTABLE_OPERATION_TARGET_BINDING')

    def test_actor_session_must_equal_the_exact_domain_approval_request(self):
        value = copy.deepcopy(self.payload)
        value['payload']['principal_session_id'] = 'b' * 64
        self.refused(value, 'PORTABLE_OPERATION_OWNER_BINDING')

    def test_boolean_negative_and_unbounded_epochs_are_not_valid_policy_revisions(self):
        for epoch in [True, 0, -1, 2**63, '1']:
            value = copy.deepcopy(self.payload)
            value['payload']['policy_epoch'] = epoch
            with self.subTest(epoch=epoch):
                self.refused(value, 'PORTABLE_OPERATION_POLICY_BINDING')

    def test_binding_and_actor_hashes_are_exact_lowercase_digests(self):
        for key in ['target_binding_digest', 'principal_session_id']:
            for digest in ['A' * 64, 'a' * 63, '', True]:
                value = copy.deepcopy(self.payload)
                value['payload'][key] = digest
                with self.subTest(key=key, digest_type=type(digest).__name__):
                    self.refused(value, 'PORTABLE_OPERATION_IDENTITY')

    def test_owner_task_workspace_and_revision_identifiers_are_closed(self):
        for key in ['workspace', 'task_id', 'session_id']:
            value = copy.deepcopy(self.payload)
            value['payload'][key] = '/outside/host/path'
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.api.parse(value)

    def test_noncanonical_duplicate_and_large_raw_operations_fail_closed(self):
        raw = canonical_json_bytes(self.payload)
        for data in [raw + b' ', b'{"operation_class":"forged",' + raw[1:], b' ' * 65537]:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                self.api(data)

    def test_changed_untouched_resource_cannot_hide_behind_old_fingerprint(self):
        value = copy.deepcopy(self.payload)
        resource = next(item for item in value['payload']['domain_input']['inventory']['resources']
                        if item['resource_id'] != self.pack.to_dict()['proposal']['target_resource_id'])
        resource['tags']['drift'] = 'changed'
        self.refused(value, 'PORTABLE_OPERATION_TARGET_BINDING')

    def test_boolean_model_flags_and_callables_are_not_operation_inputs(self):
        for value in [None, True, lambda: True, {'approved': True}]:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                self.api.parse(value)
