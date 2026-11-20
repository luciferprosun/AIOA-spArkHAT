"""Pure child selectors/origins/event recording; pytest is never imported."""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ONE = 'tests/test_math.py::test_double[one]'
TWO = 'tests/test_math.py::test_double[two]'
PROFILE = 'ISOLATED_PYTEST_FUNCTIONS_V1'


class PytestChildTests(unittest.TestCase):
    def api(self):
        module = importlib.import_module('runtime.mission.python_function_child')
        for name in ('_function_domain', '_framework_args', '_check_framework_origins',
                     '_check_pytest_environment', 'FrameworkRecorder', 'run_pytest'):
            self.assertTrue(callable(getattr(module, name, None)), name + '_NOT_IMPLEMENTED')
        return module

    def test_function_domain_keeps_legacy_root_and_uses_only_projected_v4_root(self):
        module = self.api()
        old = module._function_domain({'mode': 'observe', 'profile': 'ISOLATED_PYTHON_FUNCTIONS_V1'}, 15)
        self.assertEqual({'root': '/work/project', 'profile': 'FUNCTION_V1', 'index': None}, old)
        new = module._function_domain({'mode': 'observe', 'profile': PROFILE}, 0)
        self.assertEqual({'root': '/work/oracle-project', 'profile': 'PYTEST_ORACLE_V1', 'index': 0}, new)

    def test_domain_cannot_be_chosen_by_unknown_flags_indices_or_boolean_claims(self):
        module = self.api()
        pairs = [({'mode': 'observe', 'profile': PROFILE}, value) for value in (True, None, -1, 8, '0')]
        pairs += [({'mode': 'observe', 'profile': 'UNKNOWN'}, 0),
                  ({'mode': 'observe', 'profile': PROFILE, 'approved': True}, 0)]
        for mode, index in pairs:
            with self.subTest(mode=mode, index=index), self.assertRaises(ValueError):
                module._function_domain(mode, index)

    def test_framework_arguments_are_fixed_and_literal_signed_nodes_cannot_add_flags(self):
        module = self.api()
        argv = module._framework_args((ONE, TWO))
        self.assertIn('--rootdir=/work/tests', argv)
        self.assertIn('--confcutdir=/work/tests', argv)
        self.assertIn('--import-mode=importlib', argv)
        self.assertIn('no:cacheprovider', argv)
        self.assertIn('no:terminal', argv)
        self.assertEqual(['/work/tests/' + ONE, '/work/tests/' + TWO], argv[-2:])
        self.assertIn('/work/tests/pytest.ini', argv)
        for nodes in ((), ('--pyargs',), ('../outside.py::test_x',), (ONE, ONE), (True,)):
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                module._framework_args(nodes)

    def test_framework_environment_requires_autoload_off_and_no_ambient_flags(self):
        module = self.api()
        module._check_pytest_environment({'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
        for changes in ({}, {'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '0'},
                        {'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': '-p extra'},
                        {'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_PLUGINS': 'extra'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module._check_pytest_environment(changes)

    def origins(self):
        return {name: SimpleNamespace(__file__='/work/dependencies/' + path) for name, path in {
            'pytest': 'pytest/__init__.py', '_pytest': '_pytest/__init__.py', 'py': 'py.py',
            'pluggy': 'pluggy/__init__.py', 'iniconfig': 'iniconfig/__init__.py',
            'packaging': 'packaging/__init__.py', 'pygments': 'pygments/__init__.py'}.items()}

    def test_all_seven_framework_import_origins_are_exact_before_project_import(self):
        module = self.api()
        module._check_framework_origins(self.origins())
        for value in ('/work/project/pytest.py', '/work/dependencies/../project/pytest.py', None, True):
            origins = self.origins()
            origins['pytest'] = SimpleNamespace(__file__=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                module._check_framework_origins(origins)
        origins = self.origins()
        origins.pop('py')
        with self.assertRaises(ValueError):
            module._check_framework_origins(origins)

    def recorder(self, module, nodes=(ONE, TWO)):
        recorder = module.FrameworkRecorder(nodes)
        recorder.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=node) for node in nodes]))
        return recorder

    def event(self, recorder, node, when, outcome='passed', **values):
        recorder.pytest_runtest_logreport(SimpleNamespace(nodeid=node, when=when, outcome=outcome, **values))

    def test_recorder_emits_complete_exact_pass_facts_without_any_test_execution(self):
        module = self.api()
        recorder = self.recorder(module)
        for node in (ONE, TWO):
            for when in ('setup', 'call', 'teardown'):
                self.event(recorder, node, when)
        value = recorder.result('a' * 64, 'FAST_TESTS', 0)
        self.assertEqual([ONE, TWO], value['collected'])
        self.assertEqual([{'node_id': ONE, 'outcome': 'PASS'}, {'node_id': TWO, 'outcome': 'PASS'}],
                         value['results'])
        self.assertEqual('aioa.pytest-framework-observation.v1', value['schema'])

    def test_setup_or_teardown_failure_is_a_coherent_failed_case_not_a_fake_pass(self):
        module = self.api()
        for failed in ('setup', 'teardown'):
            recorder = self.recorder(module, (ONE,))
            self.event(recorder, ONE, 'setup', 'failed' if failed == 'setup' else 'passed')
            if failed != 'setup':
                self.event(recorder, ONE, 'call')
            self.event(recorder, ONE, 'teardown', 'failed' if failed == 'teardown' else 'passed')
            value = recorder.result('a' * 64, 'FAST_TESTS', 1)
            self.assertEqual([{'node_id': ONE, 'outcome': 'FAIL'}], value['results'])

    def test_dropped_duplicate_skip_xfail_or_incomplete_reports_never_become_pass(self):
        module = self.api()
        recorder = module.FrameworkRecorder((ONE, TWO))
        with self.assertRaises(ValueError):
            recorder.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=ONE)]))
        for kwargs in ({'outcome': 'skipped'}, {'wasxfail': 'unsupported'}):
            recorder = self.recorder(module, (ONE,))
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.event(recorder, ONE, 'setup', **kwargs)
        recorder = self.recorder(module, (ONE,))
        self.event(recorder, ONE, 'setup')
        with self.assertRaises(ValueError):
            self.event(recorder, ONE, 'setup')
        with self.assertRaises(ValueError):
            recorder.result('a' * 64, 'FAST_TESTS', 0)

    def test_host_framework_entrypoint_refuses_before_importing_pytest(self):
        module = self.api()
        self.assertNotIn('pytest', sys.modules)
        with patch.object(module.importlib, 'import_module', side_effect=AssertionError('NO_PACKAGE_IMPORT')), \
                self.assertRaisesRegex(ValueError, '^SANDBOX_ONLY_RECIPE$'):
            module.run_pytest()
        self.assertNotIn('pytest', sys.modules)


    def test_actual_function_producer_counts_v4_lf_and_keeps_legacy_boundary(self):
        import contextlib
        import io
        import json
        module = self.api()
        value = ['x' * 2028] + ['x' * 2027] * 3
        frame = json.dumps({'schema': 'aioa.python-function-return.v1', 'kind': 'returned', 'value': value},
                           sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        self.assertEqual(8192, len(frame.encode()))
        boundary_error = type('MockBoundaryError', (Exception,), {})
        for profile in ('ISOLATED_PYTHON_FUNCTIONS_V1', PROFILE):
            inputs = {
                '/inputs/mode.json': json.dumps({'mode': 'observe', 'profile': profile}).encode(),
                '/inputs/calls.json': json.dumps([{'case_id': 'case', 'module': 'module',
                    'function': 'run', 'arguments': []}]).encode(),
                '/inputs/imports.json': b'["src"]'}
            def data_path(*parts, inputs=inputs):
                path = '/'.join(str(part).rstrip('/') for part in parts)
                if path in ('/work/project/src', '/work/oracle-project/src'):
                    from pathlib import Path
                    return Path(path)
                self.assertIn(path, inputs)
                return SimpleNamespace(read_bytes=lambda: inputs[path])
            def trusted_policy(path):
                if path == '/inputs/failure_boundary.py':
                    return {'failure_boundary': lambda _label: contextlib.nullcontext(),
                            'RepairBoundaryError': boundary_error}
                self.assertEqual('/inputs/function_policy.py', path)
                return {'restrict_function_process': lambda **_kwargs: None}
            output = io.StringIO()
            with self.subTest(profile=profile), patch.object(module, '_require_sandbox'), \
                    patch.object(module, 'Path', side_effect=data_path), \
                    patch.object(module.runpy, 'run_path', side_effect=trusted_policy), \
                    patch.object(module.importlib, 'import_module', return_value=SimpleNamespace(run=lambda: value)), \
                    patch.object(module.sys, 'argv', ['child.py', '0']), \
                    patch.object(module.sys, 'path', list(module.sys.path)), contextlib.redirect_stdout(output):
                if profile == PROFILE:
                    with self.assertRaisesRegex(ValueError, '^FUNCTION_RESULT_BOUND$'):
                        module.run()
                    self.assertEqual('', output.getvalue())
                else:
                    module.run()
                    self.assertEqual(8193, len(output.getvalue().encode()))
                    self.assertEqual(value, json.loads(output.getvalue())['value'])
