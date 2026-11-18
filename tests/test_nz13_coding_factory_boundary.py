"""Trusted factory seam stays inspection-only and starts no provider/executor."""
import inspect
import unittest
from unittest.mock import patch, sentinel

from runtime import main as api


class CodingFactoryBoundaryTests(unittest.TestCase):
    def require_seam(self):
        self.assertIn('coding_tasks', inspect.signature(api.create_runtime).parameters,
                      'Missing trusted factory coding keyword')

    def test_factory_forwards_the_same_controller_without_provider_startup(self):
        self.require_seam()
        with patch.object(api, 'AgentRuntime', return_value=sentinel.runtime) as runtime, \
                patch.object(api, 'ProviderManager', side_effect=AssertionError('Provider startup forbidden')):
            result = api.create_runtime(inspection_only=True, coding_tasks=sentinel.tasks)
        self.assertIs(result, sentinel.runtime)
        runtime.assert_called_once_with(None, '', api.PROJECT_DIR, inspection_only=True,
                                        coding_tasks=sentinel.tasks, borrowed_admission=None)

    def test_non_inspection_mode_refuses_before_runtime_or_provider_creation(self):
        self.require_seam()
        with patch.object(api, 'AgentRuntime') as runtime, patch.object(api, 'ProviderManager') as provider:
            with self.assertRaisesRegex(ValueError, 'INVALID_CODING_BINDING'):
                api.create_runtime(coding_tasks=sentinel.tasks)
            runtime.assert_not_called()
            provider.assert_not_called()

    def test_all_other_binding_paths_refuse_before_any_constructor(self):
        self.require_seam()
        variants = ({'cpl_fixture': True}, {'cpl_cost_policy': sentinel.cost}, {'nonzero_config': {}},
                    {'memory_patch_config': {}}, {'memory_patch_dependencies': sentinel.dependencies},
                    {'mission_context': sentinel.context}, {'mission_bindings': sentinel.mission},
                    {'lite_profile': sentinel.profile}, {'lite_bindings': sentinel.lite},
                    {'agent_bindings': sentinel.agent})
        for extra in variants:
            with self.subTest(option=next(iter(extra))), patch.object(api, 'AgentRuntime') as runtime, \
                    patch.object(api, 'ProviderManager') as provider:
                with self.assertRaisesRegex(ValueError, 'INVALID_CODING_BINDING'):
                    api.create_runtime(inspection_only=True, coding_tasks=sentinel.tasks, **extra)
                runtime.assert_not_called()
                provider.assert_not_called()

    def test_non_boolean_inspection_mode_retains_its_original_refusal(self):
        self.require_seam()
        for value in (0, 1, None, 'true'):
            with self.subTest(type=type(value).__name__), patch.object(api, 'AgentRuntime') as runtime:
                with self.assertRaisesRegex(ValueError, 'INVALID_INSPECTION_MODE'):
                    api.create_runtime(inspection_only=value, coding_tasks=sentinel.tasks)
                runtime.assert_not_called()

    def test_default_none_preserves_the_existing_inspection_constructor(self):
        self.require_seam()
        with patch.object(api, 'AgentRuntime', return_value=sentinel.runtime) as runtime, \
                patch.object(api, 'ProviderManager') as provider:
            self.assertIs(api.create_runtime(inspection_only=True), sentinel.runtime)
            runtime.assert_called_once_with(None, '', api.PROJECT_DIR, inspection_only=True,
                                            nonzero_config=None, memory_patch_config=None,
                                            memory_patch_dependencies=None, mission_context=None,
                                            mission_bindings=None, borrowed_admission=None)
            provider.assert_not_called()

    def test_runtime_close_preserves_borrowed_core_until_owner_closes(self):
        from runtime.core_admission import (
            AdmissionError, Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope,
        )

        core = CoreAdmission(LocalOwnerAssignment(
            OwnerScope('fixture', 'owner', 'space', 'slot'),
            frozenset({Capability.READ}), frozenset({'fixture-hat'}),
            frozenset({'fixture-model'}), operator_approved=True))
        self.addCleanup(core.close)
        with patch.object(api, 'ProviderManager',
                          side_effect=AssertionError('Provider startup forbidden')):
            runtime = api.create_runtime(inspection_only=True, borrowed_admission=core)
            self.addCleanup(runtime.close)
            runtime.close()
            core.local_operator(Capability.READ)
            core.close()
            with self.assertRaises(AdmissionError):
                core.local_operator(Capability.READ)

    def test_invalid_borrowed_core_refuses_before_provider_startup(self):
        with patch.object(api, 'ProviderManager',
                          side_effect=AssertionError('Provider startup forbidden')):
            with self.assertRaisesRegex(ValueError, 'INVALID_BORROWED_ADMISSION'):
                api.create_runtime(inspection_only=True, borrowed_admission=sentinel.invalid_core)
