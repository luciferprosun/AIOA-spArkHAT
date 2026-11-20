"""A separately versioned finite PID budget, with unchanged sandbox rights."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mission import render_recipe, sandbox_contracts, sandbox_linux
from runtime.mission.sandbox_contracts import (
    SandboxOperation,
    SandboxRecipe,
    SandboxRegistry,
)

V3 = 'HEADLESS_RENDER_V3'


class RendererPidProfileTests(unittest.TestCase):
    def recipe(self, profile=V3, pids=128):
        try:
            return SandboxRecipe('recipe:pid-v3', 'fixture', 'a' * 64, 'b' * 64, 'c' * 64,
                                 pids_max=pids, resource_profile=profile)
        except ValueError:
            self.fail('Missing separately versioned finite PID resource profile')

    def operation(self, recipe):
        return {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + 'd' * 64,
                'expected_target_revision': 'recipe-v1', 'payload': recipe.payload('workspace', 'task', 'step')}

    def test_closed_shared_ceilings_preserve_old_profiles_and_are_immutable(self):
        profiles = getattr(sandbox_contracts, 'RENDER_PROFILE_CEILINGS', None)
        self.assertIsNotNone(profiles, 'Missing closed shared resource ceiling map')
        self.assertEqual({'HEADLESS_RENDER_V1', 'HEADLESS_RENDER_V2', V3}, set(profiles))
        for name, ceiling in (('HEADLESS_RENDER_V1', 64), ('HEADLESS_RENDER_V2', 64), (V3, 128)):
            self.assertEqual(ceiling, profiles[name]['pids_max'])
            self.assertEqual(536870912, profiles[name]['memory_bytes'])
        with self.assertRaises(TypeError):
            profiles[V3]['pids_max'] = 4096
        with self.assertRaises(TypeError):
            profiles['ANY'] = profiles[V3]
        self.assertEqual(16, sandbox_contracts.RESOURCE_CEILINGS['pids_max'])
        self.assertEqual(64, sandbox_contracts.RENDER_RESOURCE_CEILINGS['pids_max'])

    def test_v3_service_uses_signed_pid_value_and_retains_v2_other_properties(self):
        previous = sandbox_linux._systemd_properties(self.operation(self.recipe('HEADLESS_RENDER_V2', 64)))
        for pids in (96, 128):
            current = sandbox_linux._systemd_properties(self.operation(self.recipe(pids=pids)))
            self.assertIn('TasksMax=' + str(pids), current)
            self.assertEqual(tuple('TasksMax=64' if item == 'TasksMax=' + str(pids) else item
                                   for item in current), previous)
            for required in ('LimitNOFILE=256', 'LimitAS=4398046511104', 'MemoryMax=536870912',
                             'MemorySwapMax=0', 'CPUQuota=100%', 'RuntimeMaxSec=32s'):
                self.assertIn(required, current)

    def test_v3_pid_bounds_reject_high_boolean_string_and_invalid_integer_values(self):
        self.recipe()
        for pids in (129, True, '128', 128.0, 0, -1):
            with self.subTest(pids=pids), self.assertRaises(ValueError):
                SandboxRecipe('recipe:invalid', 'fixture', 'a' * 64, 'b' * 64, 'c' * 64,
                              pids_max=pids, resource_profile=V3)

    def test_legacy_profile_ceilings_do_not_inherit_the_v3_capacity(self):
        self.recipe()
        for profile, pids in ((None, 17), ('HEADLESS_RENDER_V1', 65), ('HEADLESS_RENDER_V2', 65)):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                SandboxRecipe('recipe:legacy', 'fixture', 'a' * 64, 'b' * 64, 'c' * 64,
                              pids_max=pids, resource_profile=profile)

    def test_v2_registry_refuses_well_shaped_v3_before_dispatch(self):
        registry = SandboxRegistry('workspace', (self.recipe('HEADLESS_RENDER_V2', 64),))
        operation = self.operation(self.recipe())
        SandboxOperation.parse(operation)
        with self.assertRaises(ValueError):
            registry.validate(operation)

    def test_v3_does_not_raise_other_ceilings_or_enable_model_resource_options(self):
        recipe = self.recipe()
        operation = self.operation(recipe)
        for name, value in (('memory_bytes', 536870913), ('timeout_ms', 20001),
                            ('cpu_quota_us', 100001), ('network_profile', 'ON'),
                            ('nofile', 4096), ('descriptor_limit', 4096)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                SandboxOperation.parse({**operation, 'payload': {**operation['payload'], name: value}})
        registry = SandboxRegistry('workspace', (recipe,))
        for name, value in (('pids_max', 128), ('resource_profile', V3)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                registry.payload({'action': 'run_recipe', 'recipe_id': recipe.recipe_id,
                                  'task_id': 'task', 'step_id': 'step', name: value})

    def test_v3_builder_pins_pid128_descriptor256_and_the_existing_listener_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'inert-runtime'
            path.write_bytes(b'INERT_RUNTIME_NEVER_EXECUTED\n')
            path.chmod(0o400)
            entry = {'snapshot': str(path), 'bytes': path.stat().st_size,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

            def compile_fixture(argv, **_kwargs):
                Path(argv[argv.index('-o') + 1]).write_bytes(b'INERT_NATIVE_NOT_EXECUTABLE\n')
                return SimpleNamespace(returncode=0)

            with patch.object(sandbox_linux.subprocess, 'run', side_effect=compile_fixture):
                try:
                    config = sandbox_linux.prepare_linux_sandbox(
                        root / 'config', {'/usr/bin/python3.12': entry, '/opt/google/chrome/chrome': entry},
                        workspace='workspace', recipes={'fixed': {'files': {'recipe.py': b'# inert\n'},
                                                                 'expected': {'done': b'done'}}},
                        resource_profile=V3, renderer_ipc='RENDER_UNIX_LISTENER_V1')
                except ValueError:
                    self.fail('Missing operator-pinned V3 preparation')
            profile = config.profile()
            self.assertEqual(128, profile['resources']['pids_max'])
            self.assertEqual(256, profile['descriptor_limit'])
            self.assertEqual('OFF', profile['network'])
            self.assertEqual(0, profile['inherited_control_fds'])
            payload = config.registry.recipes[0].payload('workspace', 'task', 'step')
            self.assertEqual(128, payload['pids_max'])
            self.assertEqual(config.profile_digest, payload['sandbox_profile_digest'])
            self.assertEqual(sandbox_linux.build_filter(final=True, ipc_profile='RENDER_UNIX_LISTENER_V1'),
                             (config.root / 'final_filter.bpf').read_bytes())

    def test_fixed_html_declares_the_current_v3_profile_without_arbitrary_resource_fields(self):
        recipe = render_recipe.HtmlRenderRecipe((('index.html', b'<title>T</title><h1>Text</h1>'),),
                                                (320, 200), 'T', 'Text')
        manifest = json.loads(recipe.manifest_bytes())
        self.assertEqual(V3, manifest['resource_profile'])
        self.assertNotIn('pids_max', manifest)
        self.assertNotIn('nofile', manifest)
