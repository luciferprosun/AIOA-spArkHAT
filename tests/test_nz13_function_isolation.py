"""Mandatory child policy contracts; fake syscall boundary never changes the host."""
import importlib
import unittest
from unittest.mock import patch


class FakeLandlock:
    def __init__(self, abi=8, failure=None):
        self.abi, self.failure, self.calls = abi, failure, []

    def create(self, rights, scoped):
        self.calls.append(('create', rights, scoped))
        return -1 if self.failure == 'create' else 99

    def add(self, ruleset, parent, rights):
        self.calls.append(('add', ruleset, parent, rights))
        return -1 if self.failure == 'add' else 0

    def restrict(self, ruleset):
        self.calls.append(('restrict', ruleset))
        return -1 if self.failure == 'restrict' else 0


class FunctionIsolationTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('runtime.mission.function_isolation')
        except ModuleNotFoundError as exc:
            self.fail('Missing mandatory normal-Python child isolation: ' + exc.name)

    def enforce(self, kernel):
        module = self.module()
        opened = []

        def open_path(path, flags):
            opened.append((path, flags))
            return len(opened) + 20

        with patch.object(module, '_require_confined_single_thread'), \
                patch.object(module, '_kernel', return_value=kernel), \
                patch.object(module.os, 'open', side_effect=open_path), \
                patch.object(module.os, 'close') as close:
            result = module.restrict_function_process()
        return module, result, opened, close.call_args_list

    def test_process_inputs_and_parent_proc_descriptors_are_outside_the_read_policy(self):
        module, result, opened, _ = self.enforce(FakeLandlock())
        paths = {path for path, _ in opened}
        self.assertFalse(any(path.startswith(('/proc', '/inputs', '/artifacts')) for path in paths))
        self.assertEqual('DENIED', result['parent_proc_access'])
        self.assertEqual('READ_ONLY', result['workspace_access'])
        self.assertEqual('DESCENDANTS_ONLY', result['signal_scope'])
        self.assertTrue(all(flags & module.os.O_NOFOLLOW for _, flags in opened))

    def test_workspace_packages_and_runtime_are_read_only_but_tmp_has_bounded_write_scope(self):
        kernel = FakeLandlock()
        module, _, opened, _ = self.enforce(kernel)
        paths = {index + 21: path for index, (path, _) in enumerate(opened)}
        granted = {paths[entry[2]]: entry[3] for entry in kernel.calls if entry[0] == 'add'}
        for path in ('/work/project', '/work/dependencies', '/usr/lib/python3.12', '/lib', '/lib64'):
            self.assertFalse(granted[path] & (module.WRITE_FILE | module.TRUNCATE | module.MAKE_REG))
            self.assertTrue(granted[path] & module.READ_FILE)
        self.assertTrue(granted['/tmp'] & module.WRITE_FILE)
        self.assertTrue(granted['/tmp'] & module.TRUNCATE)
        self.assertFalse(granted['/tmp'] & (module.EXECUTE | module.MAKE_SYM | module.MAKE_SOCK))

    def test_old_or_missing_abi_refuses_before_creating_any_ruleset(self):
        self.module()
        for abi in (-1, 0, 3, 5):
            kernel = FakeLandlock(abi=abi)
            with self.subTest(abi=abi), self.assertRaisesRegex(ValueError, 'FUNCTION_LANDLOCK_ABI_REQUIRED'):
                self.enforce(kernel)
            self.assertEqual([], kernel.calls)

    def test_ruleset_or_rule_failure_never_falls_back_to_an_unconfined_child(self):
        self.module()
        for failure in ('create', 'add'):
            kernel = FakeLandlock(failure=failure)
            with self.subTest(failure=failure), self.assertRaisesRegex(ValueError, 'FUNCTION_LANDLOCK_'):
                self.enforce(kernel)
            self.assertFalse(any(call[0] == 'restrict' for call in kernel.calls))

    def test_restrict_self_failure_propagates_and_closes_owned_policy_descriptors(self):
        module = self.module()
        kernel = FakeLandlock(failure='restrict')
        with patch.object(module, '_require_confined_single_thread'), \
                patch.object(module, '_kernel', return_value=kernel), \
                patch.object(module.os, 'open', return_value=21), patch.object(module.os, 'close') as close, \
                self.assertRaisesRegex(ValueError, 'FUNCTION_LANDLOCK_ENFORCEMENT_REQUIRED'):
            module.restrict_function_process()
        self.assertIn(((99,), {}), close.call_args_list)
        self.assertEqual(1, sum(call[0] == 'restrict' for call in kernel.calls))

    def test_host_or_multithreaded_invocation_refuses_before_loading_the_kernel_boundary(self):
        module = self.module()
        with patch.object(module, '_require_confined_single_thread',
                          side_effect=ValueError('FUNCTION_CONFINEMENT_REQUIRED')), \
                patch.object(module, '_kernel', side_effect=AssertionError('No kernel mutation')), \
                self.assertRaisesRegex(ValueError, 'FUNCTION_CONFINEMENT_REQUIRED'):
            module.restrict_function_process()
