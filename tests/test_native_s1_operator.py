"""Unprivileged checks of the operator kit, not a Noble qualification."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.mission.sandbox_linux import _open_s1_git_tool, _s1_connected_git_child
from scripts.unification.native_s1 import host, policy
from runtime.red_hat.broker_protocol import read_frame, send_frame


class NativeS1OperatorTests(unittest.TestCase):
    def test_private_control_framing_keeps_adjacent_commands_separate(self):
        import socket

        left, right = socket.socketpair()
        with left, right:
            send_frame(left, {'action': 'start-core'}, finish=False)
            send_frame(left, {'action': 'reconcile'})
            self.assertEqual(read_frame(right, finished=False), {'action': 'start-core'})
            self.assertEqual(read_frame(right), {'action': 'reconcile'})

    def test_external_receipt_and_manifest_bind_bytes_and_install_is_host_gated(self):
        with tempfile.TemporaryDirectory() as root:
            receipt = Path(root) / "receipt.json"
            pinned = Path(root) / "manifest.json"
            receipt_hash = host.management_receipt(image="1" * 64, boot="2" * 64,
                                                   signed_packages="3" * 64, output=receipt)
            digest = host.manifest(source="a" * 40, tree="b" * 40, kernel="fixture-pinned",
                                   receipt=receipt, runtime_digest="4" * 64, wheels_digest="5" * 64,
                                   core_uid=2000, output=pinned)
            self.assertEqual(digest, hashlib.sha256(pinned.read_bytes()).hexdigest())
            manifest = json.loads(pinned.read_bytes())
            self.assertEqual(manifest["host"]["management_receipt_sha256"], receipt_hash)
            self.assertEqual(manifest["host"]["boot_sha256"], "2" * 64)
            self.assertEqual(manifest["s1"]["wheels_lock_sha256"], "5" * 64)
            with self.assertRaises(FileExistsError):
                host.management_receipt(image="1" * 64, boot="2" * 64,
                                        signed_packages="3" * 64, output=receipt)
            with patch("scripts.unification.native_s1.host.os.getresuid", return_value=(1000,) * 3):
                with self.assertRaisesRegex(ValueError, "NATIVE_S1_INSTALL_ROOT"):
                    host.install(pinned, digest, receipt, receipt, wheelhouse=Path(root))

    @unittest.skipUnless(sys.platform == "linux" and Path("/usr/bin/prlimit").is_file(), "Linux prlimit is required")
    def test_connected_launch_is_limited_to_enforced_core_and_pinned_inode(self):
        with patch("pathlib.Path.read_text", return_value="aioa-n69-" + "1" * 32 + "-core (enforce)\n"):
            self.assertTrue(_s1_connected_git_child())
        for name in ("unconfined", "aioa-n69-" + "1" * 32 + "-core (complain)",
                     "aioa-n69-" + "1" * 32 + "-broker (enforce)"):
            with patch("pathlib.Path.read_text", return_value=name):
                self.assertFalse(_s1_connected_git_child())
        with self.assertRaisesRegex(ValueError, "GIT_S1_LAUNCH_TOOL"):
            _open_s1_git_tool("/usr/bin/git")
        fd = _open_s1_git_tool("/usr/bin/prlimit")
        try:
            self.assertTrue(os.path.samestat(os.fstat(fd), os.stat("/usr/bin/prlimit")))
            self.assertFalse(os.get_inheritable(fd))
        finally:
            os.close(fd)

    @unittest.skipUnless(shutil.which("apparmor_parser"), "AppArmor parser is unavailable")
    def test_full_profiles_parse_without_kernel_load(self):
        ref = "refs/heads/aioa/nz11-" + "3" * 32
        rendered = policy.profiles("1" * 32, "2" * 40, 1000, exact_ref=ref)
        self.assertEqual(set(rendered), {"broker", "sequencer", "core", "verifier"})
        self.assertIn("/repo/" + ref, rendered["broker"])
        self.assertNotIn("/refs/** w", rendered["broker"])
        for role in ("broker", "verifier", "sequencer"):
            self.assertNotIn("attach_disconnected", rendered[role])
            self.assertNotIn("dbus send", rendered[role])
        alias = "/.aioa-s1-worker-" + "1" * 32
        core_rules = rendered["core"].splitlines()
        self.assertIn(f"{alias}/{{artifacts,work,tmp}}/{{,**}} r,", core_rules)
        self.assertIn(f"{alias}/bootstrap r,", core_rules)
        self.assertEqual(sum(line.startswith(alias) for line in core_rules), 2)
        self.assertNotIn(" complain", "".join(rendered.values()))
        with tempfile.TemporaryDirectory() as root:
            for role, text in rendered.items():
                path = Path(root) / role
                path.write_text(text)
                result = subprocess.run([shutil.which("apparmor_parser"), "--skip-kernel-load",
                                         "--skip-cache", str(path)], capture_output=True, text=True, timeout=12)
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "S1 is Linux-only")
    def test_worker_seccomp_denies_export_cgroups_and_fork_in_real_process(self):
        code = '''
import array, ctypes, errno, os, socket
from runtime.red_hat.broker_protocol import read_frame, send_frame
from scripts.unification.native_s1.policy import install_worker_filter
a, b = socket.socketpair()
fd = os.open("/dev/null", os.O_RDONLY)
lib = ctypes.CDLL(None, use_errno=True)
assert lib.prctl(38, 1, 0, 0, 0) == 0 and lib.prctl(4, 0, 0, 0, 0) == 0
install_worker_filter("broker")
assert lib.prctl(4, 1, 0, 0, 0) == -1 and ctypes.get_errno() == errno.EPERM
try:
    a.sendmsg([b"x"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
except OSError as error:
    assert error.errno == errno.EPERM
else:
    raise AssertionError("descriptor export permitted")
try:
    os.fork()
except OSError as error:
    assert error.errno == errno.EPERM
else:
    os._exit(12)
assert lib.unshare(0) == -1 and ctypes.get_errno() == errno.EPERM
try:
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except OSError as error:
    assert error.errno == errno.EPERM
else:
    raise AssertionError("IPv4 socket permitted")
send_frame(a, {"published": False})
assert read_frame(b) == {"published": False}
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
