"""Signed test data and strict advisory framework facts; no pytest execution."""
import dataclasses
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.mission.repair import TEST_STAGES

ONE = 'tests/test_main.py::test_double[one]'
TWO = 'tests/test_main.py::test_double[two]'


class PytestSuiteTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('runtime.mission.project_recipe')
        self.assertTrue(callable(getattr(self.module, 'PytestSuite', None)),
                        'PINNED_PYTEST_SUITE_NOT_IMPLEMENTED')

    def values(self):
        return {'files': (
            ('tests/conftest.py', 'import pytest\n@pytest.fixture\ndef amount():\n    return 2\n'),
            ('tests/data/cases.json', '[1,2]\n'),
            ('tests/test_main.py', ('import pytest\nfrom calc import double\n'
             '@pytest.mark.parametrize("value", [1,2], ids=["one","two"])\n'
             'def test_double(amount, value):\n    assert double(value) == amount * value\n'))),
            'stages': ((TEST_STAGES[0], (ONE,)),
                       (TEST_STAGES[1], (ONE, TWO)), (TEST_STAGES[2], (ONE, TWO)))}

    def suite(self, **updates):
        return self.module.PytestSuite(**{**self.values(), **updates})

    def observation(self, suite=None, **updates):
        suite = suite or self.suite()
        return {'schema': 'aioa.pytest-framework-observation.v1', 'suite_digest': suite.digest,
                'stage': TEST_STAGES[2], 'collected': [ONE, TWO],
                'results': [{'node_id': ONE, 'outcome': 'PASS'}, {'node_id': TWO, 'outcome': 'PASS'}],
                'exit_code': 0, **updates}

    def test_canonical_roundtrip_binds_files_selections_and_no_authority(self):
        suite = self.suite()
        raw = suite.manifest_bytes()
        self.assertEqual('aioa.pytest-suite.v1', json.loads(raw)['schema'])
        self.assertEqual('NONE', suite.authority)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), suite.digest)
        self.assertEqual(suite, type(suite).from_manifest(raw))
        self.assertEqual((ONE,), suite.node_ids(TEST_STAGES[0]))

    def test_source_and_exact_selection_each_change_the_suite_digest(self):
        suite = self.suite()
        files = self.values()['files']
        self.assertNotEqual(suite.digest, self.suite(files=files[:-1] + ((files[-1][0], files[-1][1] + '\n'),)).digest)
        stages = self.values()['stages']
        changed = ((TEST_STAGES[0], (TWO,)),) + stages[1:]
        self.assertNotEqual(suite.digest, self.suite(stages=changed).digest)

    def test_frozen_data_cannot_be_reassigned_to_another_test_plan(self):
        suite = self.suite()
        with self.assertRaises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            suite.files = ()

    def test_test_source_is_never_imported_executed_or_written_on_the_host(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'must-not-exist'
            files = self.values()['files']
            source = 'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("executed")\n'
            suite = self.suite(files=files[:-1] + ((files[-1][0], source),))
            suite.manifest_bytes()
            suite.workspace_archive_bytes()
            self.assertFalse(marker.exists())

    def test_traversal_absolute_backslash_and_non_test_roots_are_denied(self):
        for name in ('../escape.py', '/tmp/test_main.py', 'tests/../escape.py',
                     'tests\\test_main.py', 'src/test_main.py', 'tests//test_main.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.suite(files=((name, 'pass\n'),))

    def test_duplicate_casefold_and_file_directory_prefix_collisions_are_denied(self):
        for rows in (
            (('tests/test_main.py', ''), ('tests/test_main.py', '')),
            (('tests/TEST_MAIN.py', ''), ('tests/test_main.py', '')),
            (('tests/a.txt', ''), ('tests/a.txt/child.txt', ''), ('tests/test_main.py', '')),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.suite(files=rows)

    def test_file_order_and_tuple_shapes_are_closed_without_silent_sorting(self):
        files = self.values()['files']
        for rows in (list(files), files[::-1], (), (['tests/test_main.py', 'pass\n'],), (True,)):
            with self.subTest(kind=type(rows).__name__), self.assertRaises(ValueError):
                self.suite(files=rows)

    def test_binary_scripts_hooks_and_user_config_are_not_a_test_file_profile(self):
        for name in ('tests/native.so', 'tests/runner.sh', 'tests/start.pth', 'tests/setup.py',
                     'tests/sitecustomize.py', 'tests/usercustomize.py', 'tests/pytest.ini'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.suite(files=tuple(sorted((*self.values()['files'], (name, 'pass\n')))))

    def test_tests_cannot_shadow_framework_names_in_any_package_component(self):
        for name in ('tests/pytest.py', 'tests/_pytest/__init__.py', 'tests/py.py',
                     'tests/pkg/pluggy/__init__.py', 'tests/packaging.py',
                     'tests/iniconfig.py', 'tests/pygments.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.suite(files=tuple(sorted((*self.values()['files'], (name, 'pass\n')))))

    def test_test_count_file_and_total_text_bytes_have_finite_bounds(self):
        for files in (
            tuple(('tests/file_' + str(index).zfill(2) + '.txt', '') for index in range(33)),
            (('tests/test_main.py', 'x' * 65537),),
            tuple(sorted((('tests/test_main.py', 'x' * 65536),
                          *[('tests/data_' + str(index) + '.txt', 'x' * 65536) for index in range(4)]))),
        ):
            with self.subTest(count=len(files)), self.assertRaises(ValueError):
                self.suite(files=files)

    def test_text_is_primitive_utf8_without_nul_or_binary_coercion(self):
        for value in (b'pass\n', None, True, 'contains\0nul', '\ud800'):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                self.suite(files=(('tests/test_main.py', value),))

    def test_stage_order_and_exact_nonempty_selected_ids_are_required(self):
        stages = self.values()['stages']
        for value in (list(stages), stages[::-1], stages[:2],
                      ((TEST_STAGES[0], ()),) + stages[1:],
                      ((TEST_STAGES[0], (ONE, ONE)),) + stages[1:],
                      ((TEST_STAGES[0], (TWO, ONE)),) + stages[1:]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.suite(stages=value)

    def test_nodes_must_name_signed_test_files_and_bounded_literal_ids(self):
        for node in ('tests/missing.py::test_x', 'tests/conftest.py::test_x',
                     'tests/test_main.py', ONE + '\n--extra', '--collect-only',
                     'tests/../test_main.py::test_x', 'tests/test_main.py::test_' + 'x' * 257):
            stages = tuple((stage, (node,)) for stage in TEST_STAGES)
            with self.subTest(node=node), self.assertRaises(ValueError):
                self.suite(stages=stages)

    def test_final_selection_cannot_drop_previously_required_ids(self):
        stages = self.values()['stages']
        with self.assertRaises(ValueError):
            self.suite(stages=stages[:-1] + ((TEST_STAGES[2], (ONE,)),))

    def test_workspace_contains_exact_readonly_tests_and_fixed_configuration(self):
        suite = self.suite()
        archive = json.loads(suite.workspace_archive_bytes())
        self.assertEqual('aioa.validation-workspace.v1', archive['schema'])
        entries = {row['path']: row for row in archive['files']}
        self.assertEqual({'pytest.ini', *dict(suite.files)}, set(entries))
        self.assertTrue(all(row['mode'] == 0o600 for row in entries.values()))
        self.assertTrue(entries['pytest.ini']['text'].startswith('[pytest]\n'))
        self.assertTrue(all(entries[name]['text'] == text for name, text in suite.files))

    def test_valid_framework_facts_are_advisory_and_a_real_failed_case_returns_false(self):
        suite = self.suite()
        self.assertTrue(suite.check_observation(self.observation(suite), TEST_STAGES[2]))
        facts = self.observation(suite, exit_code=1)
        facts['results'][1]['outcome'] = 'FAIL'
        self.assertFalse(suite.check_observation(facts, TEST_STAGES[2]))

    def test_dropped_extra_duplicate_and_reordered_collection_never_pass(self):
        suite = self.suite()
        for ids in ([], [ONE], [ONE, ONE], [ONE, TWO, TWO], [TWO, ONE]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                suite.check_observation(self.observation(suite, collected=ids), TEST_STAGES[2])

    def test_skip_xfail_unknown_and_exit_only_pass_claims_are_denied(self):
        suite = self.suite()
        for outcome in ('SKIP', 'XFAIL', 'XPASS', 'UNKNOWN', True):
            facts = self.observation(suite)
            facts['results'][0]['outcome'] = outcome
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                suite.check_observation(facts, TEST_STAGES[2])
        for value in (True, False, 2, -1, '0'):
            with self.subTest(exit=value), self.assertRaises(ValueError):
                suite.check_observation(self.observation(suite, exit_code=value), TEST_STAGES[2])
        with self.assertRaises(ValueError):
            suite.check_observation(self.observation(suite, results=[]), TEST_STAGES[2])

    def test_wrong_source_stage_schema_and_authority_fields_are_denied(self):
        suite = self.suite()
        for changes in ({'suite_digest': '0' * 64}, {'stage': TEST_STAGES[0]},
                        {'schema': 'claimed-pass'}, {'authority': 'OWNER'}, {'passed': 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                suite.check_observation(self.observation(suite, **changes), TEST_STAGES[2])

    def test_manifest_parser_refuses_unknown_duplicate_and_noncanonical_data(self):
        suite = self.suite()
        row = json.loads(suite.manifest_bytes())
        malformed = [b'', b'{"schema":"first","schema":"second"}',
                     json.dumps(row, indent=2).encode(), b'x' * 524289]
        row['argv'] = ['/bin/sh']
        malformed.append(json.dumps(row, sort_keys=True, separators=(',', ':')).encode())
        for raw in malformed:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                type(suite).from_manifest(raw)
