"""Closed child views; fake Landlock boundary never restricts the host."""
import importlib
import inspect
import unittest
from unittest.mock import patch

from test_nz13_function_isolation import FakeLandlock


class PytestIsolationTests(unittest.TestCase):
    def module(self):
        module = importlib.import_module('runtime.mission.function_isolation')
        fields = inspect.signature(module.restrict_function_process).parameters
        self.assertIn('profile', fields, 'SEPARATE_FRAMEWORK_ORACLE_VIEWS_NOT_IMPLEMENTED')
        self.assertIn('index', fields, 'PRIVATE_ORACLE_SCRATCH_NOT_IMPLEMENTED')
        return module

    def enforce(self, profile, index=None, kernel=None):
        module = self.module()
        kernel = kernel or FakeLandlock()
        opened = []

        def open_path(path, flags):
            opened.append((path, flags))
            return len(opened) + 20

        with patch.object(module, '_require_confined_single_thread'), \
                patch.object(module, '_kernel', return_value=kernel), \
                patch.object(module.os, 'open', side_effect=open_path), \
                patch.object(module.os, 'close'):
            result = module.restrict_function_process(profile=profile, index=index)
        by_fd = {number + 21: path for number, (path, _) in enumerate(opened)}
        granted = {by_fd[row[2]]: row[3] for row in kernel.calls if row[0] == 'add'}
        return module, result, opened, granted

    def test_oracle_sees_only_production_projection_packages_and_private_scratch(self):
        _module, result, opened, granted = self.enforce('PYTEST_ORACLE_V1', 0)
        self.assertIn('/work/oracle-project', granted)
        self.assertIn('/work/dependencies', granted)
        self.assertIn('/tmp/oracle-0', granted)
        self.assertEqual('DENIED', result['source_test_access'])
        self.assertEqual('/tmp/oracle-0', result['scratch_root'])
        self.assertFalse(any(path.startswith(('/work/project', '/work/tests', '/proc', '/inputs', '/artifacts'))
                             for path, _flags in opened))
        self.assertNotIn('/tmp', granted)
        self.assertNotIn('/', granted)

    def test_framework_sees_readonly_signed_source_and_tests_but_no_oracle_view(self):
        module, result, _opened, granted = self.enforce('PYTEST_FRAMEWORK_V1')
        self.assertIn('/work/project', granted)
        self.assertIn('/work/tests', granted)
        self.assertIn('/tmp/pytest-framework', granted)
        self.assertNotIn('/work/oracle-project', granted)
        self.assertNotIn('/tmp', granted)
        self.assertEqual('READ_ONLY', result['source_test_access'])
        for path in ('/work/project', '/work/tests', '/work/dependencies'):
            self.assertFalse(granted[path] & (module.WRITE_FILE | module.TRUNCATE | module.MAKE_REG))

    def test_each_oracle_index_selects_a_distinct_fixed_scratch_without_cross_access(self):
        for index in (0, 1, 7):
            with self.subTest(index=index):
                _module, result, opened, _granted = self.enforce('PYTEST_ORACLE_V1', index)
                scratch = [path for path, _flags in opened if path.startswith('/tmp')]
                self.assertEqual(['/tmp/oracle-' + str(index)], scratch)
                self.assertEqual(scratch[0], result['scratch_root'])

    def test_private_scratch_never_grants_exec_socket_or_symlink_creation(self):
        for profile, index in (('PYTEST_ORACLE_V1', 2), ('PYTEST_FRAMEWORK_V1', None)):
            with self.subTest(profile=profile):
                module, _result, opened, granted = self.enforce(profile, index)
                scratch = next(path for path in granted if path.startswith('/tmp'))
                self.assertTrue(granted[scratch] & module.WRITE_FILE)
                self.assertTrue(granted[scratch] & module.TRUNCATE)
                self.assertFalse(granted[scratch] & (module.EXECUTE | module.MAKE_SYM | module.MAKE_SOCK))
                self.assertTrue(all(flags & module.os.O_NOFOLLOW for _path, flags in opened))

    def test_unknown_profiles_and_model_dictionaries_cannot_make_a_domain(self):
        module = self.module()
        for value in ('', 'UNRESTRICTED', True, None, {'profile': 'PYTEST_ORACLE_V1'}):
            with self.subTest(profile=value), patch.object(module, '_require_confined_single_thread'), \
                    patch.object(module, '_kernel', side_effect=AssertionError('NO_KERNEL_MUTATION')), \
                    self.assertRaisesRegex(ValueError, '^FUNCTION_CHILD_DOMAIN_REQUIRED$'):
                module.restrict_function_process(profile=value)

    def test_bad_indices_and_borrowed_legacy_or_framework_indices_refuse_before_kernel(self):
        module = self.module()
        pairs = [('PYTEST_ORACLE_V1', value) for value in (None, True, False, -1, 8, 0.0, '0')]
        pairs += [('PYTEST_FRAMEWORK_V1', 0), ('FUNCTION_V1', 0)]
        for profile, index in pairs:
            with self.subTest(profile=profile, index=index), \
                    patch.object(module, '_require_confined_single_thread'), \
                    patch.object(module, '_kernel', side_effect=AssertionError('NO_KERNEL_MUTATION')), \
                    self.assertRaisesRegex(ValueError, '^FUNCTION_CHILD_DOMAIN_REQUIRED$'):
                module.restrict_function_process(profile=profile, index=index)

    def test_missing_abi_or_failed_enforcement_does_not_fall_back_for_either_new_view(self):
        for profile, index in (('PYTEST_ORACLE_V1', 0), ('PYTEST_FRAMEWORK_V1', None)):
            for abi in (-1, 0, 5):
                kernel = FakeLandlock(abi=abi)
                with self.subTest(profile=profile, abi=abi), \
                        self.assertRaisesRegex(ValueError, '^FUNCTION_LANDLOCK_ABI_REQUIRED$'):
                    self.enforce(profile, index, kernel)
                self.assertEqual([], kernel.calls)
            for failure in ('create', 'add', 'restrict'):
                with self.subTest(profile=profile, failure=failure), \
                        self.assertRaisesRegex(ValueError, '^FUNCTION_LANDLOCK_'):
                    self.enforce(profile, index, FakeLandlock(failure=failure))

    def test_host_call_refuses_before_loading_or_mutating_the_kernel_boundary(self):
        module = self.module()
        with patch.object(module, '_require_confined_single_thread',
                          side_effect=ValueError('FUNCTION_CONFINEMENT_REQUIRED')), \
                patch.object(module, '_kernel', side_effect=AssertionError('NO_KERNEL_MUTATION')), \
                self.assertRaisesRegex(ValueError, '^FUNCTION_CONFINEMENT_REQUIRED$'):
            module.restrict_function_process(profile='PYTEST_ORACLE_V1', index=0)
