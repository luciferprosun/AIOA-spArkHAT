"""Builder/registry contracts only; fake binary bytes are never executed."""
import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mission import sandbox_linux as linux


class RendererRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'inert-runtime-bytes'
        self.runtime.write_bytes(b'FIXTURE_BINARY_BYTES_NEVER_EXECUTED\n')
        self.runtime.chmod(0o400)
        self.entry = {'snapshot': str(self.runtime), 'bytes': self.runtime.stat().st_size,
                      'sha256': hashlib.sha256(self.runtime.read_bytes()).hexdigest()}

    def compiler(self, argv, **kwargs):
        self.assertEqual('/usr/bin/cc', argv[0])
        destination = Path(argv[argv.index('-o') + 1])
        self.assertTrue(destination.is_relative_to(self.root))
        destination.write_bytes(b'INERT_COMPILE_FIXTURE_NOT_AN_EXECUTABLE\n')
        return SimpleNamespace(returncode=0)

    def prepare(self, *, renderer=False, chrome=True, resource_profile=None):
        self.assertIn('resource_profile', inspect.signature(linux.prepare_linux_sandbox).parameters,
                      'Broker builder has no explicit renderer profile')
        manifest = {'/usr/bin/python3.12': self.entry}
        if renderer and chrome:
            manifest['/opt/google/chrome/chrome'] = self.entry
        recipes = {'recipe:render-v1': {'files': {'recipe.py': b'# pinned fixture; never executed\n'},
                                       'expected': {'finished.txt': b'finished\n'}}}
        selected = 'HEADLESS_RENDER_V1' if renderer else resource_profile
        with patch.object(linux.subprocess, 'run', side_effect=self.compiler), \
                patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('No process execution in data tests')):
            return linux.prepare_linux_sandbox(self.root / 'config', manifest, workspace='workspace',
                                                recipes=recipes, resource_profile=selected)

    def test_default_builder_keeps_original_filter_resources_and_payload(self):
        config = self.prepare()
        profile = config.profile()
        self.assertNotIn('resource_profile', profile)
        self.assertEqual(16, profile['resources']['pids_max'])
        self.assertEqual('9a3611e0becc74bd45f3ccb7b8b35eb19bb61f56307128049db0ee0156dadb36',
                         hashlib.sha256((config.root / 'final_filter.bpf').read_bytes()).hexdigest())
        self.assertNotIn('resource_profile', config.registry.recipes[0].payload('workspace', 'task', 'step'))

    def test_renderer_profile_binds_runtime_filter_registry_and_limits_together(self):
        config = self.prepare(renderer=True)
        profile = config.profile()
        self.assertEqual('HEADLESS_RENDER_V1', profile['resource_profile'])
        self.assertEqual('RENDER_UNIX_SOCKETPAIR_V1', profile['ipc_profile'])
        self.assertEqual('DENIED', profile['host_socket_creation'])
        self.assertEqual(0, profile['inherited_control_fds'])
        self.assertEqual('OFF', profile['network'])
        self.assertEqual(64, profile['resources']['pids_max'])
        self.assertEqual(536870912, profile['resources']['memory_bytes'])
        payload = config.registry.recipes[0].payload('workspace', 'task', 'step')
        self.assertEqual(config.profile_digest, payload['sandbox_profile_digest'])
        self.assertEqual('HEADLESS_RENDER_V1', payload['resource_profile'])
        self.assertEqual(64, payload['pids_max'])
        self.assertEqual(536870912, payload['memory_bytes'])
        self.assertEqual(linux.build_filter(final=True, ipc_profile='RENDER_UNIX_SOCKETPAIR_V1'),
                         (config.root / 'final_filter.bpf').read_bytes())

    def test_renderer_without_pinned_chrome_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'PINNED_RENDERER_REQUIRED'):
            self.prepare(renderer=True, chrome=False)

    def test_unknown_profile_refuses_before_any_configuration_directory(self):
        for profile in ('', 'BROWSER_ANY', False):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'INVALID_SANDBOX_RESOURCE_PROFILE'):
                self.prepare(resource_profile=profile)
            self.assertFalse((self.root / 'config').exists())

    def test_renderer_config_roundtrip_cannot_drop_the_explicit_profile(self):
        config = self.prepare(renderer=True)
        linux.save_host_config(config)
        restored = linux.load_host_config(config.root, trusted_root=self.root)
        self.assertEqual(config, restored)
        self.assertEqual('HEADLESS_RENDER_V1', restored.registry.recipes[0].resource_profile)
