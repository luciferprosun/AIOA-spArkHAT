"""Unprivileged checks of the operator kit, not a Noble qualification."""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mission.sandbox_linux import _open_s1_git_tool, _s1_connected_git_child, mountid
from runtime.red_hat.broker_protocol import read_frame, send_frame
from runtime.red_hat.fixture_repository import FixtureRepository, open_dir
from runtime.red_hat.role_storage import DirectoryPin
from scripts.unification.native_s1 import host, policy
from scripts.unification.native_s1.probes import SIBLING, VerifierDenials, verifier_writable_control


class NativeS1OperatorTests(unittest.TestCase):
    def test_verifier_uses_borrowed_reader_handles_for_real_denials_and_preserves_bytes(self):
        for case in ("N2", "N3"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                root = Path(temporary)
                leaf = "nz11-" + "1" * 32
                ref = "refs/heads/aioa/" + leaf
                folder = root / "repo" / ref.rsplit("/", 1)[0]
                folder.mkdir(parents=True)
                content = b"commit 4\0test"
                oid = hashlib.sha1(content).hexdigest()
                objects = root / "repo" / "objects" / oid[:2]
                objects.mkdir(parents=True)
                for directory in (root / "evidence", root / "state"):
                    directory.mkdir()
                for path, value in ((root / "repo" / ref, (oid + "\n").encode()),
                                    (root / "repo" / SIBLING, b"a" * 40 + b"\n"),
                                    (objects / oid[2:], zlib.compress(content)),
                                    (root / "evidence/witness", b"signed"),
                                    (root / "evidence/completion", b"completed"),
                                    (root / "state/lock", b"attempt")):
                    path.write_bytes(value)
                    path.chmod(0o400)
                anchor = open_dir(None, root, stack)
                repo = open_dir(anchor, "repo", stack)
                parent = open_dir(repo, ref.rsplit("/", 1)[0], stack)
                evidence = open_dir(anchor, "evidence", stack)
                target = FixtureRepository(anchor, repo, -1, -1, parent, (), os.getuid())

                def pin(fd):
                    info = os.fstat(fd)
                    return DirectoryPin(info.st_dev, info.st_ino, mountid(fd))

                # This tests the actual DAC checks on this fixture. Role admission is a separate Noble check.
                storage = SimpleNamespace(exact_ref=ref, require_role=self.assert_verifier_role,
                                          mount_namespace=Path("/proc/self/ns/mnt").stat().st_ino,
                                          repository=pin(repo), ref_parent=pin(parent))
                reports = []
                probe = VerifierDenials(case, storage, lambda *value: reports.append(value))
                request = SimpleNamespace(exact_ref=ref, new_oid=oid)
                for path in (root / "repo", folder, objects):
                    stack.callback(path.chmod, 0o700)
                    path.chmod(0o500)
                target.check_commit(request, inspect=partial(probe, target, "commit"))
                stamp = target.observe(request, inspect=partial(probe, target, "ref"))
                for kind in ("witness", "completion"):
                    target.record(evidence, kind, os.getuid(), inspect=partial(probe, target, kind))

                self.assertEqual(1, len(reports))
                denials, observed = reports[0]
                controls = set(verifier_writable_control(root, case))
                self.assertEqual(controls | ({"attempt-state"} if case == "N3" else set()), set(denials))
                self.assertTrue(all(read["before"] == read["after"] for read in observed["reads"].values()))
                ref_read = observed["reads"]["ref"]
                self.assertEqual((ref_read["before"]["file"]["dev"], ref_read["before"]["file"]["ino"]), stamp[:2])
                self.assertEqual(oid + "\n", ref_read["ref_bytes"])
                event = {"status": "DENIALS", "result": denials, "observation": observed}
                left, right = socket.socketpair()
                with left, right:
                    send_frame(left, event, finish=False)
                    self.assertEqual(event, read_frame(right, finished=False))

    def assert_verifier_role(self, name):
        self.assertEqual("verifier", name)

    def test_private_control_framing_keeps_adjacent_commands_separate(self):
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
