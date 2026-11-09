"""Explicit resource profile cannot widen the legacy sandbox payload."""
import dataclasses
import unittest

from runtime.mission.sandbox_contracts import (
    SandboxOperation,
    SandboxRecipe,
    SandboxRegistry,
)

PROFILE = 'HEADLESS_RENDER_V1'


class RendererResourceProfileTests(unittest.TestCase):
    def recipe(self, profile=None, *, pids=16):
        self.assertIn('resource_profile', {field.name for field in dataclasses.fields(SandboxRecipe)},
                      'Renderer resource selection is not explicit in the registry')
        return SandboxRecipe('recipe:render-v1', 'trusted-fixture', 'a' * 64,
                             'b' * 64, 'c' * 64, pids_max=pids, resource_profile=profile)

    def operation(self, recipe):
        return {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + 'd' * 64,
                'expected_target_revision': 'recipe-v1',
                'payload': recipe.payload('workspace', 'task', 'step')}

    def test_default_payload_has_no_new_field_and_preserves_sixteen_pid_ceiling(self):
        recipe = self.recipe()
        payload = recipe.payload('workspace', 'task', 'step')
        self.assertNotIn('resource_profile', payload)
        self.assertEqual(16, payload['pids_max'])
        SandboxOperation.parse(self.operation(recipe))
        with self.assertRaises(ValueError):
            self.recipe(pids=17)

    def test_opt_in_renderer_profile_is_explicit_bounded_and_stays_network_off(self):
        recipe = self.recipe(PROFILE, pids=64)
        payload = recipe.payload('workspace', 'task', 'step')
        self.assertEqual(PROFILE, payload['resource_profile'])
        self.assertEqual('OFF', payload['network_profile'])
        self.assertEqual(536870912, payload['memory_bytes'])
        self.assertEqual(64, payload['pids_max'])
        SandboxOperation.parse(self.operation(recipe))
        with self.assertRaises(ValueError):
            self.recipe(PROFILE, pids=65)

    def test_renderer_cannot_raise_other_resource_or_network_ceilings(self):
        recipe = self.recipe(PROFILE, pids=64)
        for key, value in (('memory_bytes', 536870913), ('timeout_ms', 20001),
                           ('network_profile', 'ON'), ('cpu_quota_us', 100001)):
            with self.subTest(field=key), self.assertRaises(ValueError):
                operation = self.operation(recipe)
                operation['payload'][key] = value
                SandboxOperation.parse(operation)

    def test_unknown_profiles_false_and_explicit_null_payload_are_refused(self):
        for profile in ('', 'BROWSER_ANY', False, {}, 1):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.recipe(profile)
        operation = self.operation(self.recipe())
        operation['payload']['resource_profile'] = None
        with self.assertRaises(ValueError):
            SandboxOperation.parse(operation)

    def test_model_proposal_cannot_supply_the_resource_profile_or_pid_limit(self):
        registry = SandboxRegistry('workspace', (self.recipe(),))
        proposal = {'action': 'run_recipe', 'recipe_id': 'recipe:render-v1',
                    'task_id': 'task', 'step_id': 'step'}
        for key, value in (('resource_profile', PROFILE), ('pids_max', 64)):
            with self.subTest(field=key), self.assertRaises(ValueError):
                registry.payload({**proposal, key: value})

    def test_default_registry_refuses_a_forged_render_payload_before_dispatch(self):
        default = self.recipe()
        registry = SandboxRegistry('workspace', (default,))
        operation = self.operation(self.recipe(PROFILE, pids=64))
        SandboxOperation.parse(operation)  # Shape is inert; registry grants no default promotion.
        with self.assertRaises(ValueError):
            registry.validate(operation)
        operation = self.operation(default)
        self.assertEqual(SandboxOperation.parse(operation), registry.validate(operation))

    def test_exact_renderer_registry_binds_its_profile_and_fixed_interpreter(self):
        recipe = self.recipe(PROFILE, pids=64)
        registry = SandboxRegistry('workspace', (recipe,))
        operation = self.operation(recipe)
        self.assertEqual(SandboxOperation.parse(operation), registry.validate(operation))
        self.assertEqual('/usr/bin/python3.12', operation['payload']['argv'][0])
        operation['payload']['argv'] = ['/bin/sh', '-c', 'rejected']
        with self.assertRaises(ValueError):
            registry.validate(operation)
