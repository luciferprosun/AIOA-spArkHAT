"""Fixed Git plumbing cannot follow internal links beyond its approved target."""

import fcntl
import os
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nz11_support import BareRepository

from runtime.mission.git_publish import (
    CoreRemoteGitRoute,
    _bounded_git,
    _git_target_identity,
)
from runtime.mission.git_recipe import git_object
from runtime.providers.exact import CancellationToken


class GitConfinementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = BareRepository(
            self.root / "approved.git", {"src/value.py": b"value = 1\n"}
        )
        self.repo.mark_disposable()
        self.foreign = self.root / "foreign"

    @staticmethod
    def files(root):
        return {
            str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file()
        }

    def substitute(self, name):
        path = self.repo.path / name
        path.rename(self.foreign)
        path.symlink_to(self.foreign, target_is_directory=True)

    def test_preexisting_objects_link_is_denied_without_foreign_write(self):
        self.substitute("objects")
        before = self.files(self.foreign)
        with self.assertRaises(ValueError):
            _bounded_git(
                self.repo.path,
                ("hash-object", "-w", "-t", "blob", "--stdin"),
                data=b"approved new postimage\n",
            )
        self.assertEqual(self.files(self.foreign), before)
        with self.assertRaises(ValueError):
            _git_target_identity(self.repo.path)

    def test_objects_swap_after_preflight_cannot_write_outside_target(self):
        _git_target_identity(self.repo.path)
        original = subprocess.Popen
        observations = {}

        def swap(*args, **kwargs):
            self.substitute("objects")
            observations["before"] = self.files(self.foreign)
            return original(*args, **kwargs)

        with patch("subprocess.Popen", side_effect=swap), self.assertRaises(ValueError):
            _bounded_git(
                self.repo.path,
                ("hash-object", "-w", "-t", "blob", "--stdin"),
                data=b"post-check substitution canary\n",
            )
        self.assertIn("before", observations)
        self.assertEqual(self.files(self.foreign), observations["before"])

    def test_preexisting_ref_parent_link_is_denied_without_foreign_write(self):
        self.substitute("refs/heads")
        before = self.files(self.foreign)
        with self.assertRaises(ValueError):
            _bounded_git(
                self.repo.path,
                ("update-ref", "refs/heads/aioa-canary", self.repo.base, "0" * 40),
            )
        self.assertEqual(self.files(self.foreign), before)

    def test_ref_parent_swap_after_preflight_cannot_write_outside_target(self):
        _git_target_identity(self.repo.path)
        original = subprocess.Popen
        observations = {}

        def swap(*args, **kwargs):
            self.substitute("refs/heads")
            observations["before"] = self.files(self.foreign)
            return original(*args, **kwargs)

        with patch("subprocess.Popen", side_effect=swap), self.assertRaises(ValueError):
            _bounded_git(
                self.repo.path,
                ("update-ref", "refs/heads/aioa-canary", self.repo.base, "0" * 40),
            )
        self.assertIn("before", observations)
        self.assertEqual(self.files(self.foreign), observations["before"])

    def test_registered_transport_rejects_whole_root_replacement_after_release(self):
        # Isolate the real transport handoff, not the independent Core proof
        # gates (those are exercised by the kernel acceptance).
        approved_identity = _git_target_identity(self.repo.path)
        replacement = BareRepository(self.root / "replacement.git", self.repo.files)
        replacement.mark_disposable()
        payload = b"whole-root substitution canary\n"
        route = CoreRemoteGitRoute.__new__(CoreRemoteGitRoute)
        route.journal = SimpleNamespace(_run=lambda *_: True)
        route.target_repository = self.repo.path
        route.plan = SimpleNamespace(
            operation_id="a" * 32,
            target_identity=approved_identity,
            objects=(("blob", payload, git_object("blob", payload)),),
            ref="refs/heads/aioa-canary",
            commit_sha=self.repo.base,
        )
        releases = []

        def release():
            if not releases:
                self.repo.path.rename(self.root / "approved-pinned.git")
                replacement.path.rename(self.repo.path)
            releases.append(True)

        before = self.files(replacement.path)
        denied = False
        with patch.object(route, "_complete_local_patch", return_value=None):
            try:
                route._dispatch_local_patch(
                    None, None, None, release, CancellationToken()
                )
            except ValueError:
                denied = True
        self.assertEqual(self.files(self.repo.path), before)
        self.assertTrue(denied)

    def test_existing_object_hardlink_after_scan_has_no_foreign_metadata_write(self):
        payload = self.repo.files["src/value.py"]
        object_id = git_object("blob", payload)
        object_path = self.repo.path / "objects" / object_id[:2] / object_id[2:]
        foreign = self.root / "foreign-object"
        foreign.write_bytes(object_path.read_bytes())
        os.utime(foreign, ns=(1000000000, 1000000000))
        original = subprocess.Popen
        observed = {}

        def swap(*args, **kwargs):
            object_path.unlink()
            os.link(foreign, object_path)
            info = foreign.stat()
            observed["before"] = (info.st_size, info.st_atime_ns, info.st_mtime_ns)
            return original(*args, **kwargs)

        with patch("subprocess.Popen", side_effect=swap):
            try:
                _bounded_git(
                    self.repo.path,
                    ("hash-object", "-w", "-t", "blob", "--stdin"),
                    data=payload,
                )
            except ValueError:
                pass
        self.assertIn("before", observed)
        info = foreign.stat()
        self.assertEqual(
            (info.st_size, info.st_atime_ns, info.st_mtime_ns), observed["before"]
        )

    def test_hardlinked_internal_file_is_denied(self):
        head = self.repo.path / "HEAD"
        os.link(head, self.root / "foreign-head")
        with self.assertRaises(ValueError):
            _bounded_git(self.repo.path, ("rev-parse", "--is-bare-repository"))

    def test_alternate_object_store_is_denied(self):
        (self.repo.path / "objects/info/alternates").write_text(str(self.root) + "\n")
        with self.assertRaises(ValueError):
            _bounded_git(self.repo.path, ("rev-parse", "--is-bare-repository"))

    def test_real_git_object_publication_and_readback(self):
        payload = b"approved immutable object\n"
        object_id = (
            _bounded_git(
                self.repo.path,
                ("hash-object", "-w", "-t", "blob", "--stdin"),
                data=payload,
                expected_target_identity=_git_target_identity(self.repo.path),
            )
            .decode()
            .strip()
        )
        self.assertEqual(object_id, git_object("blob", payload))
        self.assertEqual(self.repo.git("cat-file", "blob", object_id), payload)
        self.assertEqual(
            (self.repo.path / "objects" / object_id[:2] / object_id[2:])
            .stat()
            .st_nlink,
            1,
        )

    def test_memfd_sealing_works_when_python_omits_linux_constant_names(self):
        names = (
            "F_ADD_SEALS",
            "F_GET_SEALS",
            "F_SEAL_WRITE",
            "F_SEAL_GROW",
            "F_SEAL_SHRINK",
            "F_SEAL_SEAL",
        )
        with ExitStack() as restore:
            for name in names:
                if hasattr(fcntl, name):
                    restore.callback(setattr, fcntl, name, getattr(fcntl, name))
                    delattr(fcntl, name)
            payload = b"Python export independence\n"
            object_id = (
                _bounded_git(
                    self.repo.path,
                    ("hash-object", "-w", "-t", "blob", "--stdin"),
                    data=payload,
                    expected_target_identity=_git_target_identity(self.repo.path),
                )
                .decode()
                .strip()
            )
            self.assertEqual(self.repo.git("cat-file", "blob", object_id), payload)

    def test_kernel_sealing_denial_never_executes_an_unsealed_runtime(self):
        original = fcntl.fcntl

        def denied(fd, command, *args):
            if command == 1033:
                raise PermissionError("FIXTURE_KERNEL_SEAL_DENIED")
            return original(fd, command, *args)

        with (
            patch.object(fcntl, "fcntl", side_effect=denied),
            patch("subprocess.Popen") as spawned,
        ):
            with self.assertRaises(PermissionError):
                _bounded_git(self.repo.path, ("rev-parse", "--is-bare-repository"))
            spawned.assert_not_called()

    def test_real_git_ref_create_is_atomic_and_never_replayed(self):
        arguments = ("update-ref", "refs/heads/aioa-approved", self.repo.base, "0" * 40)
        identity = _git_target_identity(self.repo.path)
        self.assertEqual(
            _bounded_git(self.repo.path, arguments, expected_target_identity=identity),
            b"",
        )
        self.assertEqual(
            self.repo.git("rev-parse", "refs/heads/aioa-approved").decode().strip(),
            self.repo.base,
        )
        with self.assertRaisesRegex(ValueError, "GIT_REF_ALREADY_EXISTS"):
            _bounded_git(self.repo.path, arguments, expected_target_identity=identity)

    def test_config_alias_during_namespace_setup_has_no_foreign_write(self):
        config = self.repo.path / "config"
        foreign = self.root / "foreign-config"
        foreign.write_bytes(b"foreign configuration canary\n")
        os.utime(foreign, ns=(1000000000, 1000000000))
        original = subprocess.Popen
        observed = {}

        def swap(*args, **kwargs):
            config.unlink()
            os.link(foreign, config)
            observed["before"] = foreign.stat()
            # All host storage binds are read-only; config is a new private
            # tmpfs file. No setup operation receives a host writable mount.
            self.assertNotIn("--bind-fd", args[0])
            self.assertNotIn("--bind", args[0])
            return original(*args, **kwargs)

        with patch("subprocess.Popen", side_effect=swap), self.assertRaises(ValueError):
            _bounded_git(self.repo.path, ("rev-parse", "--is-bare-repository"))
        after = foreign.stat()
        before = observed["before"]
        self.assertEqual(
            (after.st_size, after.st_atime_ns, after.st_mtime_ns),
            (before.st_size, before.st_atime_ns, before.st_mtime_ns),
        )

    def test_critical_directory_replacement_changes_target_identity(self):
        before = _git_target_identity(self.repo.path)
        (self.repo.path / "objects/pack").rename(self.foreign)
        (self.repo.path / "objects/pack").mkdir()
        self.assertNotEqual(_git_target_identity(self.repo.path), before)

    def test_fixed_transport_does_not_offer_a_generic_git_command_port(self):
        with self.assertRaisesRegex(ValueError, "GIT_PLUMBING_COMMAND_DENIED"):
            _bounded_git(self.repo.path, ("config", "--get", "core.bare"))


if __name__ == "__main__":
    unittest.main()
