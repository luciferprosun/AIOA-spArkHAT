"""Closed renderer descriptor capacity and kernel evidence before Core ACK."""
import errno
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mission import render_recipe, sandbox_linux
from runtime.mission.sandbox_contracts import (
    SandboxOperation,
    SandboxRecipe,
    SandboxRegistry,
)

V1 = 'HEADLESS_RENDER_V1'
V2 = 'HEADLESS_RENDER_V2'


class RendererDescriptorTests(unittest.TestCase):
    def recipe(self, profile=V2):
        try:
            return SandboxRecipe('recipe:descriptor-v2', 'fixture', 'a' * 64, 'b' * 64, 'c' * 64,
                                 pids_max=64, resource_profile=profile)
        except ValueError:
            self.fail('Missing explicitly versioned renderer resource profile')

    def operation(self, recipe):
        return {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + 'd' * 64,
                'expected_target_revision': 'recipe-v1', 'payload': recipe.payload('workspace', 'task', 'step')}

    def parser(self):
        method = getattr(sandbox_linux, '_parse_descriptor_limits', None)
        self.assertTrue(callable(method), 'Missing bounded kernel descriptor limit parser')
        return method

    def observer(self):
        method = getattr(sandbox_linux, '_observe_descriptor_limits', None)
        self.assertTrue(callable(method), 'Missing pinned bootstrap limit observation before ACK')
        return method

    def test_v2_changes_only_the_versioned_nofile_property_from_v1(self):
        old = sandbox_linux._systemd_properties(self.operation(self.recipe(V1)))
        new = sandbox_linux._systemd_properties(self.operation(self.recipe()))
        self.assertIn('LimitNOFILE=64', old)
        self.assertIn('LimitNOFILE=256', new)
        self.assertEqual(tuple('LimitNOFILE=64' if item == 'LimitNOFILE=256' else item for item in new), old)
        for required in ('LimitAS=4398046511104', 'MemoryMax=536870912', 'MemorySwapMax=0',
                         'TasksMax=64', 'CPUQuota=100%', 'RuntimeMaxSec=32s'):
            self.assertIn(required, new)

    def test_v2_payload_contains_only_the_closed_marker_and_forbids_arbitrary_nofile(self):
        operation = self.operation(self.recipe())
        self.assertEqual(V2, operation['payload']['resource_profile'])
        SandboxOperation.parse(operation)
        for name in ('nofile', 'descriptor_limit', 'LimitNOFILE'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                SandboxOperation.parse({**operation, 'payload': {**operation['payload'], name: 4096}})

    def test_v1_registry_cannot_be_promoted_by_a_well_shaped_v2_payload(self):
        old = SandboxRegistry('workspace', (self.recipe(V1),))
        operation = self.operation(self.recipe())
        SandboxOperation.parse(operation)
        with self.assertRaises(ValueError):
            old.validate(operation)

    def test_fixed_html_recipe_declares_v2_without_model_chosen_limit(self):
        recipe = render_recipe.HtmlRenderRecipe((('index.html', b'<title>T</title><h1>Text</h1>'),),
                                                (320, 200), 'T', 'Text')
        manifest = json.loads(recipe.manifest_bytes())
        # Keep this original test ID while the fixed current recipe advances.
        self.assertEqual('HEADLESS_RENDER_V3', manifest['resource_profile'])
        self.assertNotIn('nofile', manifest)
        self.assertNotIn('descriptor_limit', manifest)

    def test_v2_configuration_pins_descriptor_limit_and_keeps_exact_ipc_policy(self):
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
                        resource_profile=V2, renderer_ipc='RENDER_UNIX_LISTENER_V1')
                except ValueError:
                    self.fail('Missing operator-pinned V2 configuration')
            self.assertEqual(256, config.profile()['descriptor_limit'])
            self.assertEqual(0, config.profile()['inherited_control_fds'])
            self.assertEqual('OFF', config.profile()['network'])
            self.assertEqual(sandbox_linux.build_filter(final=True, ipc_profile='RENDER_UNIX_LISTENER_V1'),
                             (config.root / 'final_filter.bpf').read_bytes())

    def test_parser_requires_one_exact_finite_soft_and_hard_kernel_value(self):
        parse = self.parser()
        for limit in (64, 256):
            raw = ('Limit                     Soft Limit           Hard Limit           Units\n'
                   'Max cpu time              15                   15                   seconds\n'
                   f'Max open files            {limit}                  {limit}                  files\n').encode()
            self.assertEqual((limit, limit), parse(raw, expected=limit))

    def test_parser_rejects_missing_duplicate_unlimited_mismatched_and_unbounded_data(self):
        parse = self.parser()
        row = b'Max open files            256                  256                  files\n'
        for raw in (b'', b'header only\n', row + row, row.replace(b'256', b'unlimited'),
                    row.replace(b'256', b'257', 1), row.replace(b'files\n', b'bytes\n'),
                    b'X' * 8193, row + b'\xff', row.decode()):
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ValueError):
                parse(raw, expected=256)
        for expected in (True, None, 4096, 256.0, '256'):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                parse(row, expected=expected)

    def test_observer_reads_only_pinned_proc_limits_and_closes_fd_before_return(self):
        observer = self.observer()
        with patch.object(sandbox_linux.select, 'select', return_value=([], [], [])) as alive, \
                patch.object(sandbox_linux.os, 'open', return_value=33) as opened, \
                patch.object(sandbox_linux.os, 'read', return_value=b'Max open files 256 256 files\n') as read, \
                patch.object(sandbox_linux.os, 'close') as close:
            result = observer(17, 19, expected=256)
        self.assertEqual({'soft': 256, 'hard': 256, 'source': 'PINNED_BOOTSTRAP_PROC_LIMITS'}, result)
        opened.assert_called_once_with('limits', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=17)
        read.assert_called_once_with(33, 8193)
        close.assert_called_once_with(33)
        self.assertEqual(2, alive.call_count)

    def test_dead_bootstrap_before_or_after_read_never_produces_evidence(self):
        observer = self.observer()
        with patch.object(sandbox_linux.select, 'select', return_value=([19], [], [])), \
                patch.object(sandbox_linux.os, 'open') as opened, self.assertRaises(ValueError):
            observer(17, 19, expected=256)
        opened.assert_not_called()
        with patch.object(sandbox_linux.select, 'select', side_effect=[([], [], []), ([19], [], [])]), \
                patch.object(sandbox_linux.os, 'open', return_value=33), \
                patch.object(sandbox_linux.os, 'read', return_value=b'Max open files 256 256 files\n'), \
                patch.object(sandbox_linux.os, 'close') as close, self.assertRaises(ValueError):
            observer(17, 19, expected=256)
        close.assert_called_once_with(33)

    def test_bad_or_failed_kernel_read_closes_fd_without_retry(self):
        observer = self.observer()
        with patch.object(sandbox_linux.select, 'select', return_value=([], [], [])), \
                patch.object(sandbox_linux.os, 'open', return_value=33), \
                patch.object(sandbox_linux.os, 'read', side_effect=OSError(errno.EIO, 'fixed fixture')) as read, \
                patch.object(sandbox_linux.os, 'close') as close, self.assertRaises(OSError):
            observer(17, 19, expected=256)
        read.assert_called_once()
        close.assert_called_once_with(33)
        with patch.object(sandbox_linux.select, 'select', return_value=([], [], [])), \
                patch.object(sandbox_linux.os, 'open', return_value=33), \
                patch.object(sandbox_linux.os, 'read', return_value=b'Max open files 256 unlimited files\n'), \
                patch.object(sandbox_linux.os, 'close') as close, self.assertRaises(ValueError):
            observer(17, 19, expected=256)
        close.assert_called_once_with(33)
