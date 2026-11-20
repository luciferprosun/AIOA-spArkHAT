"""The trusted factory borrows the one existing fixture Core and controller."""
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_nz11_controller as support

from runtime import main as api


class CodingFactoryGraphTests(unittest.TestCase):
    def setUp(self):
        self.case = support.ControllerTests('test_two_active_runs_cancel_independently_without_worker_or_core_replay')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.tasks = self.case.service()

    def require_seam(self):
        self.assertIn('coding_tasks', inspect.signature(api.create_runtime).parameters)

    def test_factory_preserves_the_real_fixture_core_journal_and_controller(self):
        self.require_seam()
        with patch.object(api, 'ProviderManager', side_effect=AssertionError('Provider startup forbidden')):
            runtime = api.create_runtime(inspection_only=True, coding_tasks=self.tasks)
        self.addCleanup(runtime.close)
        self.assertIs(runtime._coding_tasks, self.tasks)
        self.assertIs(runtime._memory_patch_admission, self.tasks.journal.ledger.core)
        self.assertIs(runtime._coding_tasks.journal, self.case.fx.journal)
        self.assertIsNone(runtime.provider_manager)
        self.assertIsNone(runtime.executor)
        self.assertIsNone(runtime.memory_store)

    def test_factory_cannot_replace_the_controller_with_a_lookalike(self):
        self.require_seam()
        with (
            patch.object(api, 'ProviderManager', side_effect=AssertionError('Provider startup forbidden')),
            self.assertRaisesRegex(ValueError, 'INVALID_CODING_BINDING'),
        ):
            api.create_runtime(inspection_only=True, coding_tasks=SimpleNamespace(journal=self.tasks.journal))

    def test_factory_never_constructs_a_second_admission_core(self):
        self.require_seam()
        with patch('runtime.core_admission.CoreAdmission', side_effect=AssertionError('Second Core forbidden')):
            runtime = api.create_runtime(inspection_only=True, coding_tasks=self.tasks)
        self.addCleanup(runtime.close)
        self.assertIs(runtime._memory_patch_admission, self.case.fx.core)
