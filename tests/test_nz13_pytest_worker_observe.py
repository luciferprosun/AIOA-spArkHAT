"""Trusted orchestration with inert trees/mocked children; no pytest execution."""
import contextlib
import importlib
import inspect
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mission.python_test_contracts import PytestSuite
from runtime.mission.repair import TEST_STAGES

PROFILE = 'ISOLATED_PYTEST_FUNCTIONS_V1'
LEGACY = 'ISOLATED_PYTHON_FUNCTIONS_V1'


class WorkerObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def api(self):
        module = importlib.import_module('runtime.mission.python_function_worker')
        self.assertTrue(callable(getattr(module, '_observation_profile', None)),
                        'V4_PARENT_OBSERVATION_NOT_IMPLEMENTED')
        self.assertIn('target', inspect.signature(module.stage_workspace).parameters)
        self.assertTrue(callable(getattr(module, 'verify_workspace', None)))
        return module

    def calls(self, count):
        return [{'case_id': 'case' + str(index), 'module': 'module', 'function': 'run', 'arguments': []}
                for index in range(count)]

    def test_closed_modes_keep_sixteen_legacy_and_eight_new_calls(self):
        module = self.api()
        self.assertFalse(module._observation_profile({'mode': 'observe', 'profile': LEGACY}, self.calls(16)))
        self.assertTrue(module._observation_profile({'mode': 'observe', 'profile': PROFILE}, self.calls(8)))
        for mode, calls in [({'mode': 'observe', 'profile': PROFILE}, self.calls(9)),
                            ({'mode': 'observe', 'profile': LEGACY}, self.calls(17)),
                            ({'mode': 'observe', 'profile': PROFILE, 'approved': True}, self.calls(1)),
                            ({'mode': 'observe', 'profile': 'ANY'}, self.calls(1)),
                            ({'mode': 'observe', 'profile': PROFILE}, [])]:
            with self.subTest(mode=mode, count=len(calls)), self.assertRaises(ValueError):
                module._observation_profile(mode, calls)

    def map_work(self, *parts):
        path = Path(*parts)
        self.assertTrue(path.is_relative_to('/work'))
        return self.root / 'work' / path.relative_to('/work')

    def archive(self):
        return {'schema': 'aioa.validation-workspace.v1',
                'files': [{'path': 'src/module.py', 'mode': 0o600, 'text': '# inert source\n'}]}

    def test_one_existing_workspace_stager_handles_three_closed_roots_and_exact_readback(self):
        module = self.api()
        support = vars(importlib.import_module('runtime.mission.repository_worker'))
        (self.root / 'work').mkdir(mode=0o700)
        with patch.object(module, 'Path', side_effect=self.map_work):
            for target in ('project', 'tests', 'oracle-project'):
                module.stage_workspace(self.archive(), support, target=target)
                module.verify_workspace(self.archive(), support, target=target)
                self.assertEqual('# inert source\n',
                                 (self.root / 'work' / target / 'src/module.py').read_text())

    def test_unknown_workspace_root_is_denied_before_filesystem_access(self):
        module = self.api()
        for target in ('../outside', '/home', '', True, None):
            with self.subTest(target=target), patch.object(module, 'Path', side_effect=AssertionError('NO_FS')), \
                    self.assertRaisesRegex(ValueError, '^FUNCTION_WORKSPACE_TARGET$'):
                module.stage_workspace(self.archive(), {}, target=target)

    def test_projected_source_drift_is_not_accepted_as_a_readback(self):
        module = self.api()
        support = vars(importlib.import_module('runtime.mission.repository_worker'))
        (self.root / 'work').mkdir(mode=0o700)
        with patch.object(module, 'Path', side_effect=self.map_work):
            module.stage_workspace(self.archive(), support, target='oracle-project')
            path = self.root / 'work/oracle-project/src/module.py'
            path.write_text('# changed\n')
            with self.assertRaisesRegex(ValueError, '^FUNCTION_SOURCE_CHANGED$'):
                module.verify_workspace(self.archive(), support, target='oracle-project')

    def exercise_observe(self, *, framework=True, malformed=False, failed=False):
        module = self.api()
        for folder in ('inputs', 'artifacts', 'tmp'):
            (self.root / folder).mkdir(mode=0o700)
        node = 'tests/test_one.py::test_one'
        suite = PytestSuite((('tests/test_one.py', '# pinned test\n'),),
                            tuple((stage, (node,)) for stage in TEST_STAGES))
        observed = {'schema': 'aioa.pytest-framework-observation.v1', 'suite_digest': suite.digest,
                    'stage': TEST_STAGES[0], 'collected': [node],
                    'results': [{'node_id': node, 'outcome': 'PASS'}], 'exit_code': 0}
        if failed:
            observed['results'][0]['outcome'] = 'FAIL'
            observed['exit_code'] = 1
        values = {'mode.json': {'mode': 'observe', 'profile': PROFILE if framework else LEGACY},
                  'workspace.json': self.archive(), 'oracle-workspace.json': self.archive(),
                  'context.json': {'stage': TEST_STAGES[0], 'profile_digest': 'a' * 64,
                                   'patchset_sha256': 'b' * 64, 'test_count': 1},
                  'calls.json': self.calls(1), 'pytest-suite.json': json.loads(suite.manifest_bytes())}
        for name, value in values.items():
            raw = (suite.manifest_bytes() if name == 'pytest-suite.json'
                   else json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
            (self.root / 'inputs' / name).write_bytes(raw)

        def mapped_path(*parts):
            path = Path(*parts)
            for prefix in ('/inputs', '/artifacts', '/tmp'):
                if path.is_relative_to(prefix):
                    return self.root / prefix.lstrip('/') / path.relative_to(prefix)
            self.fail('UNDECLARED_TEST_PATH:' + str(path))

        replies = ([{'schema': 'fake-PASS'} if malformed else observed] if framework else [])
        replies += [{'kind': 'returned', 'value': 7}]
        output = io.StringIO()
        with patch.object(module, 'confined'), patch.object(module, 'Path', side_effect=mapped_path), \
                patch.object(module.runpy, 'run_path', return_value={}), \
                patch.object(module, '_input_policy', return_value=SimpleNamespace(PytestSuite=PytestSuite)), \
                patch.object(module, 'wheel_lock', return_value=object()), \
                patch.object(module, 'install', return_value=[('fixture.py', 'c' * 64, 1)]), \
                patch.object(module, 'verify_installed'), patch.object(module, 'verify_workspace') as verify, \
                patch.object(module, 'stage_workspace') as stage, \
                patch.object(module, 'one_call', side_effect=replies) as child, contextlib.redirect_stdout(output):
            if malformed:
                with self.assertRaises(ValueError):
                    module.observe()
            else:
                module.observe()
        return output.getvalue(), child.call_args_list, stage.call_args_list, verify.call_args_list, observed

    def test_mocked_v4_parent_uses_three_views_and_framework_then_fresh_oracle(self):
        raw, children, stages, verifications, observed = self.exercise_observe()
        row = json.loads(raw)
        self.assertEqual('aioa.python-observation.v3', row['schema'])
        self.assertEqual(observed, row['framework'])
        self.assertEqual([{'case_id': 'case0', 'kind': 'returned', 'value': 7}], row['results'])
        self.assertEqual(['pytest', 0], [call.args[0] for call in children])
        self.assertTrue(all(call.kwargs['framework_profile'] is True for call in children))
        self.assertEqual({'project', 'tests', 'oracle-project'},
                         {call.kwargs.get('target', 'project') for call in stages})
        self.assertTrue({'project', 'tests', 'oracle-project'} <=
                        {call.kwargs.get('target', 'project') for call in verifications})
        self.assertTrue((self.root / 'artifacts/dependencies.json').is_file())
        self.assertEqual(b'PYTHON_CALLS_FINISHED\n',
                         (self.root / 'artifacts/calls-complete.txt').read_bytes())
        self.assertTrue((self.root / 'tmp/pytest-framework').is_dir())
        self.assertTrue((self.root / 'tmp/oracle-0').is_dir())

    def test_malformed_framework_stops_before_any_oracle_or_complete_marker(self):
        raw, children, _stages, _verify, _observed = self.exercise_observe(malformed=True)
        self.assertEqual('', raw)
        self.assertEqual(['pytest'], [call.args[0] for call in children])
        self.assertFalse((self.root / 'artifacts/calls-complete.txt').exists())

    def test_legacy_parent_has_original_schema_and_no_framework_or_projected_view(self):
        raw, children, stages, _verify, _observed = self.exercise_observe(framework=False)
        row = json.loads(raw)
        self.assertEqual('aioa.python-observation.v2', row['schema'])
        self.assertNotIn('framework', row)
        self.assertEqual([0], [call.args[0] for call in children])
        self.assertEqual({'project'}, {call.kwargs.get('target', 'project') for call in stages})
        self.assertFalse((self.root / 'artifacts/dependencies.json').exists())


    def test_well_formed_framework_failure_remains_advisory_and_oracles_still_run(self):
        raw, children, _stages, _verify, observed = self.exercise_observe(failed=True)
        row = json.loads(raw)
        self.assertEqual(observed, row['framework'])
        self.assertEqual('FAIL', row['framework']['results'][0]['outcome'])
        self.assertEqual(['pytest', 0], [call.args[0] for call in children])
        self.assertEqual(7, row['results'][0]['value'])
        self.assertTrue((self.root / 'artifacts/calls-complete.txt').is_file())
