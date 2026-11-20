"""Closed opt-in normal-Python profile; no candidate execution on the host."""
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import unittest

import test_nz11_general_recipe as general
from test_nz13_locked_wheels import FILENAME, wheel_bytes


class PythonFunctionProfileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = general.GeneralRecipeTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def profile(self, *, lock=None):
        original = self.fixture.profile()
        fields = {field.name for field in dataclasses.fields(original)}
        self.assertIn('execution_profile', fields, 'No explicit opt-in normal Python profile')
        self.assertIn('wheel_lock', fields, 'No operator-bound package lock')
        return dataclasses.replace(original, execution_profile='ISOLATED_PYTHON_FUNCTIONS_V1', wheel_lock=lock)

    def lock(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.dependency_lock'))
        module = importlib.import_module('runtime.mission.dependency_lock')
        raw = wheel_bytes()
        wheel = module.LockedWheel(distribution='fixture-math', version='1.0.0', filename=FILENAME,
                                   sha256=hashlib.sha256(raw).hexdigest(), content=raw)
        return module.PythonWheelLock((wheel,))

    def test_default_profile_remains_the_closed_v2_contract(self):
        original = self.fixture.profile()
        self.assertIn('execution_profile', {field.name for field in dataclasses.fields(original)})
        self.assertEqual('RESTRICTED_AST_JSON_V2', original.execution_profile)
        self.assertIsNone(original.wheel_lock)
        self.assertEqual('aioa.python-repository-recipe.v2', json.loads(original.manifest_bytes())['schema'])
        self.assertEqual(original, type(original).from_manifest(original.manifest_bytes()))

    def test_normal_profile_requires_an_explicit_version_and_pins_distinct_worker(self):
        normal = self.profile()
        original = self.fixture.profile()
        self.assertNotEqual(normal.digest, original.digest)
        manifest = json.loads(normal.manifest_bytes())
        self.assertEqual('aioa.python-repository-recipe.v3', manifest['schema'])
        self.assertEqual('ISOLATED_PYTHON_FUNCTIONS_V1', manifest['execution_profile'])
        self.assertIsNone(manifest['wheel_lock'])
        self.assertEqual(normal, type(normal).from_manifest(normal.manifest_bytes()))
        for bad in ('GENERAL_PYTHON', '', None, 3):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dataclasses.replace(normal, execution_profile=bad)

    def test_package_lock_is_inert_exact_operator_input_and_affects_profile_digest(self):
        unlocked = self.profile()
        lock = self.lock()
        locked = self.profile(lock=lock)
        self.assertNotEqual(locked.digest, unlocked.digest)
        manifest = json.loads(locked.manifest_bytes())
        self.assertEqual(json.loads(lock.manifest_bytes()), manifest['wheel_lock'])
        self.assertEqual(locked, type(locked).from_manifest(locked.manifest_bytes(), wheel_lock=lock))
        with self.assertRaises(ValueError):
            type(locked).from_manifest(locked.manifest_bytes())
        with self.assertRaises(ValueError):
            dataclasses.replace(self.fixture.profile(), wheel_lock=lock)

    def test_restoration_refuses_unrelated_or_tampered_package_lock(self):
        locked = self.profile()
        lock = self.lock()
        locked = dataclasses.replace(locked, wheel_lock=lock)
        value = json.loads(locked.manifest_bytes())
        value['wheel_lock']['wheels'][0]['sha256'] = 'a' * 64
        with self.assertRaises(ValueError):
            type(locked).from_manifest(json.dumps(value).encode(), wheel_lock=lock)
        value = json.loads(locked.manifest_bytes())
        value['wheel_lock']['authority'] = 'OWNER'
        with self.assertRaises(ValueError):
            type(locked).from_manifest(json.dumps(value).encode(), wheel_lock=lock)

    def test_normal_observation_inputs_pin_helpers_and_never_contain_expected_answers(self):
        profile = self.profile(lock=self.lock())
        *_, patch, archive = self.fixture.proposal()
        spec = profile.observation_spec('TARGETED_TESTS', archive, patch)
        self.assertLessEqual(len(spec['files']), 16)
        self.assertIn('function_child.py', spec['files'])
        self.assertIn('repository_support.py', spec['files'])
        self.assertIn('wheel_policy.py', spec['files'])
        self.assertEqual(profile.wheel_lock.inputs()['python-wheel-lock.json'], spec['files']['python-wheel-lock.json'])
        self.assertEqual(profile.wheel_lock.wheels[0].content, spec['files'][FILENAME])
        self.assertNotIn('one-two', spec['files']['calls.json'].decode())
        self.assertNotIn('expected', spec['files']['calls.json'].decode())
        self.assertNotIn('/home/', spec['files']['context.json'].decode())

    def test_fixed_interpreter_and_network_policy_cannot_be_chosen_by_manifest(self):
        profile = self.profile()
        value = json.loads(profile.manifest_bytes())
        value['command'] = ['/bin/sh', '-c', 'echo rejected']
        with self.assertRaises(ValueError):
            type(profile).from_manifest(json.dumps(value).encode())
        value = json.loads(profile.manifest_bytes())
        value['network'] = 'ON'
        with self.assertRaises(ValueError):
            type(profile).from_manifest(json.dumps(value).encode())

    def test_worker_pass_claims_and_wrong_value_cannot_replace_host_oracle(self):
        profile = self.profile()
        *_, patch, _archive = self.fixture.proposal()
        stage, cases = profile.stages[0]
        row = {'schema': 'aioa.python-observation.v2', 'profile_digest': profile.digest,
               'patchset_sha256': patch.patchset_sha256, 'stage': stage,
               'results': [{'case_id': case.case_id, 'kind': 'returned', 'value': 'PASS'} for case in cases]}
        self.assertEqual(('FAIL', 1), profile.decode_observation(json.dumps(row) + '\n', stage, patch))
        row['results'] = [{'case_id': cases[0].case_id, 'kind': 'PASS'}]
        with self.assertRaises(ValueError):
            profile.decode_observation(json.dumps(row) + '\n', stage, patch)

    def test_profile_digest_rejects_a_manifest_with_unknown_execution_fields(self):
        profile = self.profile()
        value = json.loads(profile.manifest_bytes())
        value['postinstall'] = 'ignored command must be refused'
        with self.assertRaises(ValueError):
            type(profile).from_manifest(json.dumps(value).encode())

    def test_normal_manifest_cannot_omit_or_downgrade_required_child_isolation(self):
        profile = self.profile()
        row = json.loads(profile.manifest_bytes())
        self.assertEqual('LANDLOCK_ABI6_MANDATORY_V1', row.get('isolation_policy'))
        for replacement in (None, 'BEST_EFFORT', 'OFF'):
            value = dict(row)
            if replacement is None:
                value.pop('isolation_policy')
            else:
                value['isolation_policy'] = replacement
            with self.subTest(policy=replacement), self.assertRaises(ValueError):
                type(profile).from_manifest(json.dumps(value).encode())

    def test_normal_recipe_pins_child_policy_and_shared_failure_boundary_as_readonly_inputs(self):
        profile = self.profile()
        *_, patch, archive = self.fixture.proposal()
        files = profile.observation_spec('FAST_TESTS', archive, patch)['files']
        self.assertIn('function_policy.py', files)
        self.assertIn('failure_boundary.py', files)
        self.assertIn(b'def restrict_function_process', files['function_policy.py'])
        self.assertIn(b'def failure_boundary', files['failure_boundary.py'])
