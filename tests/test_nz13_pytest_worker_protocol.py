"""Pure lock/child selectors and mocked pipes; no package/project execution."""
import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_nz13_locked_wheels import FILENAME, wheel_bytes


class PipeProcess:
    def __init__(self, raw):
        read, write = os.pipe2(os.O_CLOEXEC)
        try:
            # All protocol fixtures are small enough for one owned pipe write.
            assert len(raw) < 4096
            os.write(write, raw)
        finally:
            os.close(write)
        self.stdout = os.fdopen(read, 'rb')

    def wait(self, timeout):
        return 0

    def poll(self):
        return 0


class PytestWorkerProtocolTests(unittest.TestCase):
    def api(self):
        module = importlib.import_module('runtime.mission.python_function_worker')
        self.assertTrue(callable(getattr(module, 'decode_wheel_lock', None)),
                        'CLOSED_LOCK_PROFILE_DISPATCH_NOT_IMPLEMENTED')
        self.assertTrue(callable(getattr(module, 'child_call_config', None)),
                        'CLOSED_CHILD_SELECTOR_NOT_IMPLEMENTED')
        self.assertIn('framework_profile', inspect.signature(module.one_call).parameters)
        return module

    def fixture(self, raw=None):
        policy = importlib.import_module('runtime.mission.dependency_lock')
        raw = wheel_bytes() if raw is None else raw
        wheel = policy.LockedWheel('fixture-math', '1.0.0', FILENAME, hashlib.sha256(raw).hexdigest(), raw)
        return policy, policy.PythonWheelLock((wheel,)), raw

    def decode(self, module, raw=None, *, framework=False, content=None):
        policy, lock, wheel = self.fixture()
        requests = []

        def load(name):
            requests.append(name)
            return wheel if content is None else content

        result = module.decode_wheel_lock(policy, lock.manifest_bytes() if raw is None else raw,
                                          load, framework=framework)
        return result, requests, lock

    def test_legacy_lock_keeps_exact_manifest_and_only_declared_byte_reads(self):
        module = self.api()
        result, reads, expected = self.decode(module)
        self.assertEqual(expected, result)
        self.assertEqual([FILENAME], reads)
        self.assertEqual(expected.manifest_bytes(), result.manifest_bytes())

    def test_legacy_null_lock_is_inert_and_does_not_read_any_wheel(self):
        module = self.api()
        policy = self.fixture()[0]
        result = module.decode_wheel_lock(policy, b'null', lambda _name: self.fail('NO_READ'))
        self.assertIsNone(result)

    def test_framework_cannot_use_a_null_lock_or_legacy_closure(self):
        module = self.api()
        for raw in (b'null', self.fixture()[1].manifest_bytes()):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                self.decode(module, raw, framework=True)

    def test_unknown_schema_and_extra_authority_fields_do_not_register_a_lock(self):
        module = self.api()
        original = json.loads(self.fixture()[1].manifest_bytes())
        for key, value in (('schema', 'unknown'), ('authority', 'OWNER'), ('network', 'ON'),
                           ('postinstall', '/bin/sh')):
            row = {**original, key: value}
            raw = json.dumps(row, sort_keys=True, separators=(',', ':')).encode()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.decode(module, raw)

    def test_filename_paths_are_denied_before_the_wheel_loader(self):
        module = self.api()
        policy, lock, _wheel = self.fixture()
        for name in ('../' + FILENAME, '/tmp/' + FILENAME, 'folder\\' + FILENAME):
            row = json.loads(lock.manifest_bytes())
            row['wheels'][0]['filename'] = name
            raw = json.dumps(row, sort_keys=True, separators=(',', ':')).encode()
            with self.subTest(name=name), self.assertRaises(ValueError):
                module.decode_wheel_lock(policy, raw, lambda _name: self.fail('NO_READ'))

    def test_wrong_byte_count_or_hash_never_becomes_a_valid_install_lock(self):
        module = self.api()
        original = json.loads(self.fixture()[1].manifest_bytes())
        for key, value in (('bytes', True), ('bytes', 1), ('sha256', '0' * 64)):
            row = json.loads(json.dumps(original))
            row['wheels'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.decode(module, json.dumps(row, sort_keys=True, separators=(',', ':')).encode())

    def test_framework_manifest_does_not_bypass_the_legacy_profile(self):
        module = self.api()
        policy, lock, _wheel = self.fixture()
        row = json.loads(lock.manifest_bytes())
        row['schema'] = 'aioa.pytest-wheel-lock.v1'
        row['wheels'] *= 5
        with self.assertRaises(ValueError):
            module.decode_wheel_lock(policy, json.dumps(row).encode(), lambda _name: self.fail('NO_READ'))

    def test_profile_selector_is_an_exact_boolean_not_model_claimed_authority(self):
        module = self.api()
        for value in (None, 1, 'FRAMEWORK', {}, {'approved': True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.decode(module, framework=value)

    def test_duplicate_json_and_unknown_row_fields_are_refused(self):
        module = self.api()
        original = json.loads(self.fixture()[1].manifest_bytes())
        row = json.loads(json.dumps(original))
        row['wheels'][0]['argv'] = ['/bin/sh']
        for raw in (b'{"wheels":[],"wheels":[]}', json.dumps(row).encode()):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                self.decode(module, raw)

    def test_lock_decoding_does_not_import_or_execute_wheel_payloads(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'never-executed'
            source = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("bad")\n').encode()
            policy, lock, raw = self.fixture(wheel_bytes(package=source))
            module.decode_wheel_lock(policy, lock.manifest_bytes(), lambda _name: raw)
            self.assertFalse(marker.exists())
            self.assertNotIn('fixture_math', sys.modules)

    def test_default_child_selector_preserves_fixed_interpreter_environment_and_one_second(self):
        module = self.api()
        selected = module.child_call_config(15)
        self.assertEqual(['/usr/bin/python3.12', '-I', '-S', '-B', '/inputs/function_child.py', '15'],
                         selected['argv'])
        self.assertEqual({'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, selected['env'])
        self.assertEqual('/work/project', selected['cwd'])
        self.assertEqual(1, selected['seconds'])

    def test_framework_selector_uses_fixed_five_second_child_and_private_scratch(self):
        module = self.api()
        selected = module.child_call_config('pytest', framework_profile=True)
        self.assertEqual('pytest', selected['argv'][-1])
        self.assertEqual(5, selected['seconds'])
        self.assertEqual('/tmp/pytest-framework', selected['env']['TMPDIR'])
        self.assertEqual('1', selected['env']['PYTEST_DISABLE_PLUGIN_AUTOLOAD'])
        self.assertNotIn('PYTEST_ADDOPTS', selected['env'])
        self.assertNotIn('PYTEST_PLUGINS', selected['env'])

    def test_new_oracle_selector_uses_only_its_projected_cwd_and_own_scratch(self):
        module = self.api()
        for index in (0, 7):
            selected = module.child_call_config(index, framework_profile=True)
            self.assertEqual('/work/oracle-project', selected['cwd'])
            self.assertEqual('/tmp/oracle-' + str(index), selected['env']['TMPDIR'])
            self.assertEqual(1, selected['seconds'])

    def test_unknown_argv_indices_and_profile_claims_refuse_before_process_creation(self):
        module = self.api()
        pairs = [('pytest', False), (True, False), (-1, False), (16, False),
                 ('../child.py', True), (8, True), (0, 'yes'), (0, None)]
        with patch.object(module.subprocess, 'Popen', side_effect=AssertionError('NO_SPAWN')):
            for index, profile in pairs:
                with self.subTest(index=index, profile=profile), \
                        self.assertRaisesRegex(ValueError, '^FUNCTION_CHILD_SELECTOR$'):
                    module.child_call_config(index, framework_profile=profile)

    def pipe_call(self, module, index, reply, *, framework_profile=False):
        process = PipeProcess((json.dumps(reply, separators=(',', ':')) + '\n').encode())
        self.addCleanup(process.stdout.close)
        with patch.object(module, 'confined'), \
                patch.object(module.subprocess, 'Popen', return_value=process) as spawn:
            value = module.one_call(index, framework_profile=framework_profile)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(spawn.call_args.kwargs['close_fds'])
        self.assertEqual(module.subprocess.DEVNULL, spawn.call_args.kwargs['stdin'])
        self.assertEqual(module.subprocess.DEVNULL, spawn.call_args.kwargs['stderr'])
        return value, spawn.call_args

    def test_mocked_fresh_oracle_reply_is_bounded_and_inherits_no_host_environment(self):
        module = self.api()
        reply = {'schema': 'aioa.python-function-return.v1', 'kind': 'returned', 'value': 7}
        value, call = self.pipe_call(module, 0, reply, framework_profile=True)
        self.assertEqual({'kind': 'returned', 'value': 7}, value)
        self.assertEqual('/work/oracle-project', call.kwargs['cwd'])
        self.assertEqual(module.child_call_config(0, framework_profile=True)['env'], call.kwargs['env'])

    def test_mocked_framework_reply_is_only_advisory_data_for_later_context_validation(self):
        module = self.api()
        reply = {'schema': 'aioa.pytest-framework-observation.v1', 'suite_digest': 'a' * 64,
                 'stage': 'FAST_TESTS', 'collected': ['tests/test_one.py::test_one'],
                 'results': [{'node_id': 'tests/test_one.py::test_one', 'outcome': 'PASS'}], 'exit_code': 0}
        value, call = self.pipe_call(module, 'pytest', reply, framework_profile=True)
        self.assertEqual(reply, value)
        self.assertEqual('pytest', call.args[0][-1])

    def test_wrong_child_schema_cannot_masquerade_as_framework_data(self):
        module = self.api()
        reply = {'schema': 'aioa.python-function-return.v1', 'kind': 'returned', 'value': 'PASS'}
        with self.assertRaisesRegex(ValueError, '^PYTEST_CHILD_SCHEMA$'):
            self.pipe_call(module, 'pytest', reply, framework_profile=True)

    def test_real_host_one_call_is_denied_before_popen(self):
        module = self.api()
        with patch.object(module.subprocess, 'Popen', side_effect=AssertionError('NO_HOST_SPAWN')), \
                self.assertRaisesRegex(ValueError, '^SANDBOX_ONLY_RECIPE$'):
            module.one_call(0)
