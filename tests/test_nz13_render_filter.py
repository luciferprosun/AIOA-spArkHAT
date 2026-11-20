"""Proposed restricted IPC bytecode invariants; not a kernel certificate.

The real renderer must separately pass the existing broker/kernel acceptance.
"""
import hashlib
import inspect
import socket
import struct
import unittest

from runtime.mission.sandbox_linux import build_filter

ALLOW = 0x7FFF0000
DENY = 0x00050001
KILL = 0x80000000
RENDER_IPC = 'RENDER_UNIX_SOCKETPAIR_V1'


def evaluate(raw, number, args=(), *, arch=0xC000003E):
    """Small test-side evaluator of the emitted classic BPF, with no syscall."""
    data = struct.pack('<iI7Q', number, arch, 0, *(tuple(args) + (0,) * (6 - len(args))))
    rows = [struct.unpack('<HBBI', raw[i:i+8]) for i in range(0, len(raw), 8)]
    accumulator, position = 0, 0
    for _ in range(len(rows) * 4):
        code, yes, no, value = rows[position]
        if code == 0x20:
            assert value % 4 == 0 and value <= 60
            accumulator = struct.unpack('<I', data[value:value+4])[0]
        elif code == 0x54:
            accumulator &= value
        elif code == 0x15:
            position += yes if accumulator == value else no
        elif code == 0x35:
            position += yes if accumulator >= value else no
        elif code == 0x06:
            return value
        else:
            raise AssertionError('Unexpected emitted BPF instruction')
        position += 1
        assert 0 <= position < len(rows)
    raise AssertionError('Nonterminating emitted filter')


class RenderFilterTests(unittest.TestCase):
    def renderer(self):
        self.assertIn('ipc_profile', inspect.signature(build_filter).parameters,
                      'No explicit separately pinned renderer IPC filter')
        return build_filter(final=True, ipc_profile=RENDER_IPC)

    def test_default_filter_bytes_and_all_socket_denials_are_preserved(self):
        raw = build_filter(final=True)
        self.assertEqual('9a3611e0becc74bd45f3ccb7b8b35eb19bb61f56307128049db0ee0156dadb36',
                         hashlib.sha256(raw).hexdigest())
        for number in (41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55):
            with self.subTest(syscall=number):
                self.assertEqual(DENY, evaluate(raw, number, (socket.AF_UNIX, socket.SOCK_STREAM)))

    def test_renderer_cannot_create_or_connect_a_socket_even_to_host_control(self):
        raw = self.renderer()
        for family in (socket.AF_UNIX, socket.AF_INET, socket.AF_INET6, socket.AF_NETLINK):
            with self.subTest(family=family):
                self.assertEqual(DENY, evaluate(raw, 41, (family, socket.SOCK_STREAM)))
                self.assertEqual(DENY, evaluate(raw, 42))
        for number in (43, 44, 45, 49, 50, 51, 52, 54, 55, 288, 299, 307):
            self.assertEqual(DENY, evaluate(raw, number))

    def test_only_private_pair_read_or_write_half_close_is_allowed(self):
        raw = self.renderer()
        for descriptor in (0, 3, 63):
            for how in (socket.SHUT_RD, socket.SHUT_WR):
                with self.subTest(descriptor=descriptor, how=how):
                    self.assertEqual(ALLOW, evaluate(raw, 48, (descriptor, how)))
                    self.assertEqual(DENY, evaluate(build_filter(final=True), 48, (descriptor, how)))

    def test_half_close_rejects_full_shutdown_high_bits_and_unbounded_descriptors(self):
        raw = self.renderer()
        for descriptor, how in ((64, 0), (2**32 + 3, 0), (3, socket.SHUT_RDWR),
                                 (3, 2**32), (3, 2**32 + 1), (3, 2**32 - 1)):
            with self.subTest(descriptor=descriptor, how=how):
                self.assertEqual(DENY, evaluate(raw, 48, (descriptor, how)))

    def test_half_close_never_opens_host_connection_or_ptrace_routes(self):
        raw = self.renderer()
        for number in (41, 42, 49, 50, 101, 165, 272, 438):
            with self.subTest(number=number):
                self.assertEqual(DENY, evaluate(raw, number, (3, 0)))

    def test_only_unix_stream_or_seqpacket_pairs_with_known_flags_are_admitted(self):
        raw = self.renderer()
        for kind in (socket.SOCK_STREAM, socket.SOCK_SEQPACKET):
            for flags in (0, socket.SOCK_CLOEXEC, socket.SOCK_NONBLOCK,
                          socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK):
                with self.subTest(kind=kind, flags=flags):
                    self.assertEqual(ALLOW, evaluate(raw, 53, (socket.AF_UNIX, kind | flags)))

    def test_inet_pairs_raw_datagram_and_high_argument_bits_stay_denied(self):
        raw = self.renderer()
        for family, kind in ((socket.AF_INET, socket.SOCK_STREAM), (socket.AF_INET6, socket.SOCK_STREAM),
                             (socket.AF_UNIX, socket.SOCK_DGRAM), (socket.AF_UNIX, socket.SOCK_RAW),
                             (socket.AF_UNIX | 2**32, socket.SOCK_STREAM),
                             (socket.AF_UNIX, socket.SOCK_STREAM | 2**32),
                             (socket.AF_UNIX, socket.SOCK_STREAM | 0x40000000)):
            with self.subTest(family=family, kind=kind):
                self.assertEqual(DENY, evaluate(raw, 53, (family, kind)))

    def test_only_pair_message_io_is_added_and_default_message_io_is_still_denied(self):
        raw = self.renderer()
        for number in (46, 47):
            self.assertEqual(ALLOW, evaluate(raw, number))
            self.assertEqual(DENY, evaluate(build_filter(final=True), number))

    def test_only_renderer_private_pair_credential_option_with_int_size_is_allowed(self):
        raw = self.renderer()
        for descriptor in (0, 3, 63):
            args = (descriptor, socket.SOL_SOCKET, socket.SO_PASSCRED, 0x1000, 4)
            with self.subTest(descriptor=descriptor):
                self.assertEqual(ALLOW, evaluate(raw, 54, args))
                self.assertEqual(DENY, evaluate(build_filter(final=True), 54, args))

    def test_credential_option_rejects_other_levels_options_and_lengths(self):
        raw = self.renderer()
        for level, option, size in ((0, socket.SO_PASSCRED, 4),
                                    (socket.SOL_SOCKET, socket.SO_SNDBUF, 4),
                                    (socket.SOL_SOCKET, socket.SO_RCVBUF, 4),
                                    (socket.SOL_SOCKET, socket.SO_PASSCRED, 0),
                                    (socket.SOL_SOCKET, socket.SO_PASSCRED, 8)):
            with self.subTest(level=level, option=option, size=size):
                self.assertEqual(DENY, evaluate(raw, 54, (3, level, option, 0x1000, size)))

    def test_credential_option_rejects_high_argument_bits_and_out_of_bound_descriptors(self):
        raw = self.renderer()
        for descriptor, level, option, size in ((64, 1, 16, 4), (2**32 + 3, 1, 16, 4),
                                               (3, 2**32 + 1, 16, 4), (3, 1, 2**32 + 16, 4),
                                               (3, 1, 16, 2**32 + 4)):
            with self.subTest(descriptor=descriptor, level=level, option=option, size=size):
                self.assertEqual(DENY, evaluate(raw, 54, (descriptor, level, option, 0x1000, size)))

    def test_credential_option_never_opens_getsockopt_or_a_network_socket(self):
        raw = self.renderer()
        for number in (41, 42, 49, 50, 101, 438):
            with self.subTest(number=number):
                self.assertEqual(DENY, evaluate(raw, number, (3, 1, 16, 0x1000, 4)))
        self.assertEqual(DENY, evaluate(raw, 55, (3, 1, socket.SO_ERROR, 0x1000, 0x2000)))
        self.assertEqual(DENY, evaluate(build_filter(final=True), 55, (3, 1, 16, 0x1000, 0x2000)))

    def test_renderer_can_query_only_its_private_pair_credential_flag(self):
        raw = self.renderer()
        for descriptor in (0, 3, 63):
            for value_pointer, length_pointer in ((0x1000, 0x2000), (2**40, 2**41)):
                with self.subTest(descriptor=descriptor, pointer=value_pointer):
                    self.assertEqual(ALLOW, evaluate(raw, 55, (
                        descriptor, socket.SOL_SOCKET, socket.SO_PASSCRED, value_pointer, length_pointer)))

    def test_private_credential_getter_refuses_unapproved_options_levels_and_high_bits(self):
        raw = self.renderer()
        for descriptor, level, option in ((64, 1, 16), (2**32 + 3, 1, 16),
                                          (3, 0, 16), (3, 2**32 + 1, 16),
                                          (3, 1, socket.SO_ERROR), (3, 1, socket.SO_PEERCRED),
                                          (3, 1, 2**32 + 16)):
            with self.subTest(descriptor=descriptor, level=level, option=option):
                self.assertEqual(DENY, evaluate(raw, 55, (descriptor, level, option, 0x1000, 0x2000)))

    def test_getter_length_is_an_opaque_pointer_not_a_model_selected_integer_size(self):
        raw = self.renderer()
        for length_pointer in (0, 4, 0x2000, 2**40):
            with self.subTest(pointer=length_pointer):
                self.assertEqual(ALLOW, evaluate(raw, 55, (3, 1, 16, 0x1000, length_pointer)))
        # The kernel still validates and bounds these guest pointers. Classic
        # BPF neither dereferences them nor turns IPC flags into owner auth.

    def test_renderer_keeps_abi_namespace_and_ptrace_denials(self):
        raw = self.renderer()
        self.assertEqual(KILL, evaluate(raw, 59, arch=0x40000003))
        self.assertEqual(KILL, evaluate(raw, 0x40000000 | 59))
        for number in (101, 165, 166, 272, 310, 311, 317, 321):
            self.assertEqual(DENY, evaluate(raw, number))
        for flags in (0x10000000, 0x40000000, 0x02000000, 0x80, 2**32):
            self.assertEqual(DENY, evaluate(raw, 56, (flags,)))
        self.assertEqual(0x00050026, evaluate(raw, 435))

    def test_unknown_ipc_profiles_and_setup_phase_opt_in_are_refused(self):
        self.renderer()
        for value in ('', 'ALLOW_UNIX', False, {}, 7):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_filter(final=True, ipc_profile=value)
        with self.assertRaises(ValueError):
            build_filter(final=False, ipc_profile=RENDER_IPC)
