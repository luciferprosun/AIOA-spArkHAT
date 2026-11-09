"""Explicit private renderer listeners; no real socket or process execution.

The real kernel/renderer acceptance remains a separate required gate.
"""
import hashlib
import inspect
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_nz13_render_filter import ALLOW, DENY, KILL, evaluate

from runtime.mission import render_recipe, render_runtime, sandbox_linux

LISTENER = 'RENDER_UNIX_LISTENER_V1'
PAIR = 'RENDER_UNIX_SOCKETPAIR_V1'


class RenderListenerFilterTests(unittest.TestCase):
    def renderer(self):
        try:
            return sandbox_linux.build_filter(final=True, ipc_profile=LISTENER)
        except ValueError:
            self.fail('Missing separately pinned private listener policy')

    def test_existing_default_setup_and_pair_filters_keep_exact_bytes(self):
        for final, profile, expected in (
                (True, None, '9a3611e0becc74bd45f3ccb7b8b35eb19bb61f56307128049db0ee0156dadb36'),
                (False, None, 'fc3c485848c94f2943791fe5dc23712aa395553c5bd0dde1a2bf09ce40cc825b'),
                (True, PAIR, '1ddddcd5869b9d0ab3eeb952bae2d61107a447d376f3751a2b99a6e344b1a200')):
            with self.subTest(final=final, profile=profile):
                raw = sandbox_linux.build_filter(final=final, ipc_profile=profile)
                self.assertEqual(expected, hashlib.sha256(raw).hexdigest())

    def test_only_unix_stream_creation_with_closed_flags_and_protocol_is_allowed(self):
        raw = self.renderer()
        for flags in (0, socket.SOCK_CLOEXEC, socket.SOCK_NONBLOCK,
                      socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK):
            with self.subTest(flags=flags):
                self.assertEqual(ALLOW, evaluate(raw, 41, (socket.AF_UNIX, socket.SOCK_STREAM | flags, 0)))
                self.assertEqual(DENY, evaluate(sandbox_linux.build_filter(final=True, ipc_profile=PAIR),
                                                41, (socket.AF_UNIX, socket.SOCK_STREAM | flags, 0)))

    def test_inet_datagram_raw_unknown_flags_protocols_and_high_bits_stay_denied(self):
        raw = self.renderer()
        for family, kind, protocol in (
                (socket.AF_INET, 1, 0), (socket.AF_INET6, 1, 0), (socket.AF_NETLINK, 1, 0),
                (socket.AF_PACKET, 1, 0), (1, socket.SOCK_DGRAM, 0), (1, socket.SOCK_RAW, 0),
                (1, socket.SOCK_SEQPACKET, 0), (1, 1 | 0x40000000, 0), (1, 1, 1),
                (1 | 2**32, 1, 0), (1, 1 | 2**32, 0), (1, 1, 2**32)):
            with self.subTest(family=family, kind=kind, protocol=protocol):
                self.assertEqual(DENY, evaluate(raw, 41, (family, kind, protocol)))

    def test_bind_accepts_only_bounded_descriptors_and_sockaddr_un_sizes(self):
        raw = self.renderer()
        for descriptor in (0, 3, 63):
            for size in (2, 48, 110):
                for pointer in (0x1000, 2**40):
                    with self.subTest(descriptor=descriptor, size=size, pointer=pointer):
                        self.assertEqual(ALLOW, evaluate(raw, 49, (descriptor, pointer, size)))
        for descriptor, size in ((64, 110), (2**32 + 3, 110), (3, 0), (3, 1),
                                  (3, 111), (3, 2**32 + 110)):
            with self.subTest(descriptor=descriptor, size=size):
                self.assertEqual(DENY, evaluate(raw, 49, (descriptor, 0x1000, size)))

    def test_listen_accepts_only_observed_backlog_five_and_bounded_descriptors(self):
        raw = self.renderer()
        for descriptor in (0, 3, 63):
            self.assertEqual(ALLOW, evaluate(raw, 50, (descriptor, 5)))
        for descriptor, backlog in ((64, 5), (2**32 + 3, 5), (3, 0), (3, 4),
                                     (3, 6), (3, 2**32 + 5), (3, 2**32 - 1)):
            with self.subTest(descriptor=descriptor, backlog=backlog):
                self.assertEqual(DENY, evaluate(raw, 50, (descriptor, backlog)))

    def test_connect_accept_datagram_peer_queries_and_host_import_routes_stay_denied(self):
        raw = self.renderer()
        for number in (42, 43, 44, 45, 51, 52, 101, 165, 166, 272, 288, 299,
                       307, 310, 311, 317, 321, 438):
            for args in ((), (3, 0x1000, 110), (63, 0, 0)):
                with self.subTest(number=number, args=args):
                    self.assertEqual(DENY, evaluate(raw, number, args))

    def test_all_other_syscall_decisions_keep_the_existing_pair_policy(self):
        raw = self.renderer()
        pair = sandbox_linux.build_filter(final=True, ipc_profile=PAIR)
        for number in range(451):
            if number in (41, 49, 50):
                continue
            for args in ((), (1, 1, 0), (3, 1, 16, 0x1000, 4), (3, 1, 16, 0x1000, 2**40)):
                with self.subTest(number=number, args=args):
                    self.assertEqual(evaluate(pair, number, args), evaluate(raw, number, args))
        self.assertEqual(KILL, evaluate(raw, 59, arch=0x40000003))
        self.assertEqual(KILL, evaluate(raw, 0x40000000 | 41))

    def test_listener_profile_never_applies_during_namespace_setup(self):
        self.renderer()
        for final in (False, 1, None):
            with self.subTest(final=final), self.assertRaises(ValueError):
                sandbox_linux.build_filter(final=final, ipc_profile=LISTENER)


class RenderListenerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'inert-runtime'
        self.runtime.write_bytes(b'INERT_FIXED_RUNTIME_NEVER_EXECUTED\n')
        self.runtime.chmod(0o400)
        self.entry = {'snapshot': str(self.runtime), 'bytes': self.runtime.stat().st_size,
                      'sha256': hashlib.sha256(self.runtime.read_bytes()).hexdigest()}
        self.calls = []

    def compiler(self, argv, **_kwargs):
        self.calls.append(tuple(argv))
        Path(argv[argv.index('-o') + 1]).write_bytes(b'INERT_NATIVE_NEVER_EXECUTED\n')
        return SimpleNamespace(returncode=0)

    def prepare(self, *, listener=LISTENER, renderer=True):
        self.assertIn('renderer_ipc', inspect.signature(sandbox_linux.prepare_linux_sandbox).parameters,
                      'Missing trusted renderer-only IPC selection')
        manifest = {'/usr/bin/python3.12': self.entry}
        if renderer:
            manifest['/opt/google/chrome/chrome'] = self.entry
        with patch.object(sandbox_linux.subprocess, 'run', side_effect=self.compiler):
            return sandbox_linux.prepare_linux_sandbox(
                self.root / 'config', manifest, workspace='workspace',
                recipes={'fixed': {'files': {'recipe.py': b'# inert\n'}, 'expected': {'done': b'done'}}},
                resource_profile='HEADLESS_RENDER_V1' if renderer else None, renderer_ipc=listener)

    def test_new_profile_is_pinned_to_filter_and_compiled_bootstrap_without_worker_argv_input(self):
        config = self.prepare()
        profile = config.profile()
        self.assertEqual(LISTENER, profile['ipc_profile'])
        self.assertEqual('DENIED', profile['host_socket_creation'])
        self.assertEqual('DENIED', profile['host_connect'])
        self.assertEqual('UNIX_STREAM_ONLY', profile['private_listener_creation'])
        self.assertEqual(0, profile['inherited_control_fds'])
        self.assertEqual('OFF', profile['network'])
        self.assertEqual(sandbox_linux.build_filter(final=True, ipc_profile=LISTENER),
                         (config.root / 'final_filter.bpf').read_bytes())
        self.assertEqual(config.profile_digest,
                         config.registry.recipes[0].payload('workspace', 'task', 'step')['sandbox_profile_digest'])
        selected = [call for call in self.calls if '-DAIOA_RENDER_LISTENER=1' in call]
        self.assertEqual(1, len(selected))
        self.assertTrue(any(str(item).endswith('/native/bootstrap.c') for item in selected[0]))

    def test_existing_renderer_choice_keeps_old_profile_and_default_bootstrap_variant(self):
        config = self.prepare(listener=None)
        self.assertEqual(PAIR, config.profile()['ipc_profile'])
        self.assertFalse(any('-DAIOA_RENDER_LISTENER=1' in call for call in self.calls))
        self.assertNotIn('private_listener_creation', config.profile())

    def test_listener_selection_requires_explicit_renderer_resources_before_configuration(self):
        for listener, renderer in ((LISTENER, False), ('ANY_UNIX', True), (False, True), ({}, True)):
            with self.subTest(listener=listener, renderer=renderer), self.assertRaisesRegex(
                    ValueError, 'UNAPPROVED_SANDBOX_IPC_PROFILE'):
                self.prepare(listener=listener, renderer=renderer)
            self.assertFalse((self.root / 'config').exists())

    def test_operator_html_preparation_selects_the_new_closed_profile(self):
        recipe = render_recipe.HtmlRenderRecipe((('index.html', b'<title>Title</title><h1>Text</h1>'),),
                                                (320, 200), 'Title', 'Text')
        manifest = {'/usr/bin/python3.12': self.entry, '/opt/google/chrome/chrome': self.entry}
        with patch.object(render_runtime, 'snapshot_renderer_runtime', return_value=manifest), \
                patch.object(sandbox_linux.subprocess, 'run', side_effect=self.compiler):
            config = render_runtime.prepare_html_render_sandbox(self.root / 'html', workspace='workspace',
                                                                recipe=recipe)
        self.assertEqual(LISTENER, config.profile()['ipc_profile'])
        self.assertEqual(20000, config.registry.recipes[0].timeout_ms)
        self.assertEqual(16384, config.registry.recipes[0].max_output_bytes)
