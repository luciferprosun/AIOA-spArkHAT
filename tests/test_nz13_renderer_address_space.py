"""Virtual renderer reservations cannot raise the physical memory ceiling."""
import unittest

from runtime.mission import sandbox_linux as linux
from runtime.mission.sandbox_contracts import SandboxOperation, SandboxRecipe


class RendererAddressSpaceTests(unittest.TestCase):
    def operation(self, *, render):
        recipe = SandboxRecipe('recipe:address-space', 'trusted-fixture', 'a' * 64,
                               'b' * 64, 'c' * 64, pids_max=64 if render else 16,
                               resource_profile='HEADLESS_RENDER_V1' if render else None)
        return {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + 'd' * 64,
                'expected_target_revision': 'recipe-v1',
                'payload': recipe.payload('workspace', 'task', 'step')}

    def test_explicit_renderer_has_finite_four_tib_virtual_space_and_512_mib_physical(self):
        operation = self.operation(render=True)
        properties = linux._systemd_properties(operation)
        self.assertIn('LimitAS=4398046511104', properties)
        self.assertIn('MemoryMax=536870912', properties)
        self.assertIn('MemorySwapMax=0', properties)
        self.assertIn('TasksMax=64', properties)
        self.assertEqual(operation['payload']['network_profile'], 'OFF')

    def test_default_profile_keeps_its_exact_original_virtual_and_physical_bounds(self):
        properties = linux._systemd_properties(self.operation(render=False))
        self.assertIn('LimitAS=536870912', properties)
        self.assertNotIn('LimitAS=4398046511104', properties)
        self.assertIn('MemoryMax=536870912', properties)
        self.assertIn('TasksMax=16', properties)

    def test_virtual_space_is_not_a_model_chosen_payload_parameter(self):
        for render in (False, True):
            for field in ('address_space_bytes', 'virtual_memory_bytes', 'rlimit_as'):
                with self.subTest(render=render, field=field), self.assertRaises(ValueError):
                    operation = self.operation(render=render)
                    operation['payload'][field] = 4 * 1024**4
                    SandboxOperation.parse(operation)

    def test_renderer_cannot_raise_physical_memory_or_enable_swap_or_network(self):
        for field, replacement in (('memory_bytes', 536870913), ('network_profile', 'ON'),
                                   ('swap_bytes', 4096)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                operation = self.operation(render=True)
                operation['payload'][field] = replacement
                SandboxOperation.parse(operation)
