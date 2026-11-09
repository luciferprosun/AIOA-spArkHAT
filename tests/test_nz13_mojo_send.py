"""Private connected-socket output: no destination or new peer authority."""
import hashlib
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_nz13_render_filter import ALLOW, DENY, KILL, evaluate

from runtime.mission import render_recipe, render_runtime, sandbox_linux

MOJO = 'RENDER_UNIX_MOJO_V1'
LISTENER = 'RENDER_UNIX_LISTENER_V1'


class MojoSendFilterTests(unittest.TestCase):
    def renderer(self):
        try:
            return sandbox_linux.build_filter(final=True, ipc_profile=MOJO)
        except ValueError:
            self.fail('Missing separately pinned NULL-destination Mojo send policy')

    def test_all_four_legacy_filters_keep_exact_bytes(self):
        for final, profile, expected in (
                (False, None, 'fc3c485848c94f2943791fe5dc23712aa395553c5bd0dde1a2bf09ce40cc825b'),
                (True, None, '9a3611e0becc74bd45f3ccb7b8b35eb19bb61f56307128049db0ee0156dadb36'),
                (True, 'RENDER_UNIX_SOCKETPAIR_V1', '1ddddcd5869b9d0ab3eeb952bae2d61107a447d376f3751a2b99a6e344b1a200'),
                (True, LISTENER, 'ba1e3271143e2e0a3b851e738e140079b608efc22d6974db030aa1023d423e78')):
            with self.subTest(final=final, profile=profile):
                self.assertEqual(expected, hashlib.sha256(
                    sandbox_linux.build_filter(final=final, ipc_profile=profile)).hexdigest())

    def test_null_destination_send_allows_only_bounded_private_fd_capacity_and_known_flags(self):
        raw = self.renderer()
        for descriptor in (0, 3, 63, 64, 128, 255):
            for flags in (0, socket.MSG_NOSIGNAL, socket.MSG_DONTWAIT,
                          socket.MSG_NOSIGNAL | socket.MSG_DONTWAIT):
                with self.subTest(descriptor=descriptor, flags=flags):
                    self.assertEqual(ALLOW, evaluate(raw, 44, (descriptor, 0x1000, 3, flags, 0, 0)))
                    self.assertEqual(DENY, evaluate(sandbox_linux.build_filter(final=True, ipc_profile=LISTENER),
                                                    44, (descriptor, 0x1000, 3, flags, 0, 0)))

    def test_any_destination_pointer_length_or_integer_high_bits_are_denied(self):
        raw = self.renderer()
        for descriptor, address, size in ((256, 0, 0), (2**32 + 3, 0, 0),
                                          (3, 1, 0), (3, 2**40, 0), (3, 0, 1),
                                          (3, 0, 2**32), (3, 0x1000, 110)):
            with self.subTest(descriptor=descriptor, address=address, size=size):
                self.assertEqual(DENY, evaluate(raw, 44, (descriptor, 0x1000, 3, 0, address, size)))

    def test_fast_open_out_of_band_eor_unknown_flags_and_high_bits_stay_denied(self):
        raw = self.renderer()
        for flags in (0x20000000, socket.MSG_OOB, socket.MSG_EOR, 0x100,
                      2**32, 2**32 + socket.MSG_NOSIGNAL, 2**32 - 1):
            with self.subTest(flags=flags):
                self.assertEqual(DENY, evaluate(raw, 44, (3, 0x1000, 3, flags, 0, 0)))

    def test_every_other_syscall_decision_is_identical_to_the_legacy_listener(self):
        raw = self.renderer()
        old = sandbox_linux.build_filter(final=True, ipc_profile=LISTENER)
        for number in range(451):
            if number == 44:
                continue
            for args in ((), (1, 1, 0), (3, 1, 16, 0x1000, 4), (128, 1, 16, 0x1000, 4)):
                with self.subTest(number=number, args=args):
                    self.assertEqual(evaluate(old, number, args), evaluate(raw, number, args))
        self.assertEqual(KILL, evaluate(raw, 59, arch=0x40000003))
        self.assertEqual(KILL, evaluate(raw, 0x40000000 | 44))

    def test_connect_recvfrom_peer_identity_and_setup_opt_in_are_still_denied(self):
        raw = self.renderer()
        for number in (42, 43, 45, 51, 52, 101, 165, 272, 288, 438):
            with self.subTest(number=number):
                self.assertEqual(DENY, evaluate(raw, number, (3, 0x1000, 110)))
        self.assertEqual(DENY, evaluate(raw, 55, (3, 1, socket.SO_PEERCRED, 0x1000, 0x2000)))
        with self.assertRaises(ValueError):
            sandbox_linux.build_filter(final=False, ipc_profile=MOJO)


class MojoSendRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'inert-runtime'
        self.runtime.write_bytes(b'INERT_RUNTIME_NEVER_EXECUTED\n')
        self.runtime.chmod(0o400)
        self.entry = {'snapshot': str(self.runtime), 'bytes': self.runtime.stat().st_size,
                      'sha256': hashlib.sha256(self.runtime.read_bytes()).hexdigest()}
        self.calls = []

    def compiler(self, argv, **_kwargs):
        self.calls.append(tuple(argv))
        Path(argv[argv.index('-o') + 1]).write_bytes(b'INERT_NATIVE_NOT_EXECUTABLE\n')
        return SimpleNamespace(returncode=0)

    def prepare(self, profile='HEADLESS_RENDER_V3', ipc=MOJO):
        with patch.object(sandbox_linux.subprocess, 'run', side_effect=self.compiler):
            return sandbox_linux.prepare_linux_sandbox(
                self.root / 'config', {'/usr/bin/python3.12': self.entry, '/opt/google/chrome/chrome': self.entry},
                workspace='workspace', recipes={'fixed': {'files': {'recipe.py': b'# inert\n'},
                                                         'expected': {'done': b'done'}}},
                resource_profile=profile, renderer_ipc=ipc)

    def test_mojo_is_explicitly_pinned_to_v3_profile_and_existing_bootstrap_variant(self):
        try:
            config = self.prepare()
        except ValueError:
            self.fail('Missing operator-pinned Mojo profile')
        profile = config.profile()
        self.assertEqual(MOJO, profile['ipc_profile'])
        self.assertEqual('NULL_ADDRESS_ONLY', profile['private_connected_send'])
        self.assertEqual(256, profile['private_send_fd_limit'])
        self.assertEqual('DENIED', profile['host_connect'])
        self.assertEqual('OFF', profile['network'])
        self.assertEqual(0, profile['inherited_control_fds'])
        self.assertEqual(256, profile['descriptor_limit'])
        self.assertEqual(128, profile['resources']['pids_max'])
        self.assertEqual(sandbox_linux.build_filter(final=True, ipc_profile=MOJO),
                         (config.root / 'final_filter.bpf').read_bytes())
        self.assertEqual(1, sum('-DAIOA_RENDER_LISTENER=1' in call for call in self.calls))

    def test_mojo_selector_cannot_promote_default_or_legacy_resource_profiles(self):
        for profile in (None, 'HEADLESS_RENDER_V1', 'HEADLESS_RENDER_V2'):
            with self.subTest(profile=profile), self.assertRaisesRegex(
                    ValueError, 'UNAPPROVED_SANDBOX_IPC_PROFILE'):
                self.prepare(profile=profile)
            self.assertFalse((self.root / 'config').exists())

    def test_legacy_v3_selection_does_not_gain_the_connected_send_rule(self):
        config = self.prepare(ipc=LISTENER)
        self.assertEqual(LISTENER, config.profile()['ipc_profile'])
        self.assertNotIn('private_connected_send', config.profile())
        self.assertEqual(DENY, evaluate((config.root / 'final_filter.bpf').read_bytes(),
                                       44, (3, 0x1000, 3, socket.MSG_NOSIGNAL, 0, 0)))

    def test_fixed_html_preparation_chooses_mojo_without_a_model_command_option(self):
        recipe = render_recipe.HtmlRenderRecipe((('index.html', b'<title>T</title><h1>Text</h1>'),),
                                                (320, 200), 'T', 'Text')
        manifest = {'/usr/bin/python3.12': self.entry, '/opt/google/chrome/chrome': self.entry}
        with patch.object(render_runtime, 'snapshot_renderer_runtime', return_value=manifest), \
                patch.object(sandbox_linux.subprocess, 'run', side_effect=self.compiler):
            config = render_runtime.prepare_html_render_sandbox(self.root / 'html', workspace='workspace',
                                                                recipe=recipe)
        self.assertEqual(MOJO, config.profile()['ipc_profile'])
        self.assertEqual('HEADLESS_RENDER_V3', config.registry.recipes[0].resource_profile)
        self.assertEqual(20000, config.registry.recipes[0].timeout_ms)
        self.assertEqual(16384, config.registry.recipes[0].max_output_bytes)
