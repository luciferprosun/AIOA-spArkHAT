"""Offline checks for the pinned storage contract and its reader-only entry."""

import os
import stat
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
from runtime.mission.git_publish import _git_target_identity
from runtime.mission.sandbox_linux import LinuxSandboxBroker, mountid
from runtime.red_hat.broker_protocol import read_record
from runtime.red_hat.executor_custody import ExecutorRoles, load_broker_signer
from runtime.red_hat.fixture_repository import open_repository
from runtime.red_hat.role_storage import CoreTargetStorage, DirectoryPin, RoleStorage, StorageActor


class NativeRoleStorageTests(unittest.TestCase):
    def setUp(self):
        self.ref = "refs/heads/aioa/nz11-" + "a" * 32
        core = StorageActor(1101, 1101, "aioa-core (enforce)", "0::/native/core")
        broker = StorageActor(1102, 1102, "aioa-broker (enforce)", "0::/native/broker")
        verifier = StorageActor(1103, 1103, "aioa-verifier (enforce)", "0::/native/verifier")
        anchor, repo, refs, evidence = (DirectoryPin(12, i, 7) for i in range(1, 5))
        self.storage = RoleStorage(core, broker, verifier, 1200, 17, self.ref,
                                   anchor, repo, refs, evidence)

    def test_aliases_and_ambiguous_domains_are_rejected(self):
        for change in (
            {"verifier": replace(self.storage.verifier, uid=self.storage.core.uid)},
            {"verifier": replace(self.storage.verifier, apparmor=self.storage.core.apparmor)},
            {"reader_gid": self.storage.core.gid},
            {"evidence": self.storage.ref_parent},
            {"evidence": replace(self.storage.evidence, mount=8)},
            {"exact_ref": "refs/heads/main"},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "STORAGE_CONTRACT"):
                replace(self.storage, **change)

    def test_serialized_layout_requires_all_pins_and_exact_shape(self):
        product = replace(self.storage, staging=DirectoryPin(12, 5, 7), state=DirectoryPin(12, 6, 7),
                          policy_sha256="a"*64)
        wire = product.to_dict()
        self.assertEqual(product, RoleStorage.from_dict(wire))
        self.assertEqual(product.digest, RoleStorage.from_dict(wire).digest)
        with self.assertRaisesRegex(ValueError, "WRITER_PINS"):
            RoleStorage.from_dict({**wire, "staging": None})
        with self.assertRaisesRegex(ValueError, "STORAGE_SCHEMA"):
            RoleStorage.from_dict({**wire, "anchor": {**wire["anchor"], "extra": True}})

    def test_replaced_attempt_state_cannot_use_the_original_writer_pin(self):
        with tempfile.TemporaryDirectory() as work, ExitStack() as stack:
            root = Path(work)
            for name in ("repo", "refs", "evidence", "staging", "state"):
                (root / name).mkdir(mode=0o700)
            def pin(path):
                fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                return fd, DirectoryPin(info.st_dev, info.st_ino, mountid(fd))
            _, anchor = pin(root)
            _, repo = pin(root / "repo")
            _, refs = pin(root / "refs")
            _, evidence = pin(root / "evidence")
            _, staging = pin(root / "staging")
            original_fd, state = pin(root / "state")
            writer = replace(self.storage, anchor=anchor, repository=repo, ref_parent=refs,
                             evidence=evidence, staging=staging, state=state, policy_sha256="a"*64)
            writer.state.require_fd(original_fd)
            (root / "state").rename(root / "retained-state")
            (root / "state").mkdir(mode=0o700)
            replacement_fd, replacement_pin = pin(root / "state")
            self.assertNotEqual(writer.digest, replace(writer, state=replacement_pin).digest)
            with self.assertRaisesRegex(ValueError, "DIRECTORY_MOVED"):
                writer.require_state(replacement_fd)

    def test_layout_distinguishes_immutable_ancestors_and_exact_ref(self):
        s = self.storage
        def entry(owner, mode, gid=s.reader_gid):
            return SimpleNamespace(st_uid=owner, st_gid=gid, st_mode=mode)
        directory = stat.S_IFDIR
        regular = stat.S_IFREG
        self.assertTrue(s.entry_matches("refs/heads", entry(0, directory | 0o750)))
        self.assertFalse(s.entry_matches("refs/heads", entry(s.broker.uid, directory | 0o2750)))
        self.assertTrue(s.entry_matches("refs/heads/aioa", entry(s.broker.uid, directory | 0o2750)))
        self.assertTrue(s.entry_matches(self.ref, entry(s.broker.uid, regular | 0o440)))
        self.assertFalse(s.entry_matches(self.ref, entry(s.broker.uid, regular | 0o640)))
        sibling = self.ref[:-1] + "b"
        self.assertFalse(s.entry_matches(sibling, entry(s.broker.uid, regular | 0o440)))
        self.assertFalse(s.entry_matches(self.ref + ".lock", entry(0, regular | 0o440)))
        self.assertFalse(s.entry_matches(self.ref, entry(s.broker.uid, regular | 0o440, gid=s.broker.gid)))

    def test_pre_capsule_read_scope_cannot_accept_an_already_published_ref(self):
        reader = self.storage.core_target()
        early = reader.pre_capsule()
        current_ref = SimpleNamespace(st_uid=self.storage.broker.uid, st_gid=self.storage.reader_gid,
                                      st_mode=stat.S_IFREG | 0o440)
        self.assertFalse(early.entry_matches(self.ref, current_ref))
        self.assertTrue(reader.entry_matches(self.ref, current_ref))
        self.assertEqual(reader, early.with_ref(self.ref))
        with self.assertRaisesRegex(ValueError, "STORAGE_REF"):
            reader.with_ref(self.ref[:-1] + "b")

    def test_target_fingerprint_is_the_same_before_and_after_capsule_ref_assignment(self):
        reader = self.storage.core_target()
        # Exercise the fingerprint algorithm with real FDs. The role/topology
        # observation and privileged marker owner are fixture inputs here.
        with tempfile.TemporaryDirectory() as work, patch.object(
            CoreTargetStorage, "observe", autospec=True,
            side_effect=lambda _reader, fd: (os.fstat(fd), (("objects", (1, 2, 3)),)),
        ) as observe, patch("runtime.red_hat.broker_protocol.read_record",
                            return_value=b"AIOA_DISPOSABLE_BARE_PATCH_V1\n"):
            root = Path(work).resolve()
            before = _git_target_identity(root, shared_reader=reader.pre_capsule())
            after = _git_target_identity(root, shared_reader=reader)
            self.assertEqual(before, after)
            self.assertEqual(2, observe.call_count)

    def test_cold_compose_switches_to_exact_ref_without_changing_layout_digest(self):
        reader = self.storage.core_target()
        config = NativeHostCompositionConfig(b'{"profile":"OWNED_OFFLINE_PROOF_V1"}', None, None, None, None)
        initial = config.with_qualification_target(reader.pre_capsule())
        cold = config.with_qualification_target(reader)
        self.assertEqual(initial.digest, cold.digest)
        self.assertNotEqual(config.digest, cold.digest)
        owner_without_live_port = SimpleNamespace()
        self.assertIsNone(initial.qualification_reader(owner_without_live_port).exact_ref)
        self.assertEqual(self.ref, cold.qualification_reader(owner_without_live_port).exact_ref)
        changed = config.with_qualification_target(replace(reader, ref_parent=DirectoryPin(12, 9, 7)))
        self.assertNotEqual(cold.digest, changed.digest)

    def test_shared_git_reader_denies_mutation_before_opening_repository(self):
        reader = self.storage.core_target()
        for arguments, data in (
            (("update-ref", self.ref, "a" * 40, "0" * 40), None),
            (("hash-object", "-w", "-t", "blob", "--stdin"), b"payload"),
        ):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, "STORAGE_READ_ONLY"):
                LinuxSandboxBroker._git_plumbing(-1, arguments, git_sha256="a" * 64,
                                                   data=data, shared_reader=reader)

    def test_inode_pin_rejects_replacement_with_open_original_fd(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work, "repo")
            path.mkdir()
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                observed = os.fstat(fd)
                physical = DirectoryPin(observed.st_dev, observed.st_ino, mountid(fd))
                path.rename(Path(work, "old"))
                path.mkdir()
                physical.require_fd(fd)
                replacement = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    with self.assertRaisesRegex(ValueError, "DIRECTORY_MOVED"):
                        physical.require_fd(replacement)
                finally:
                    os.close(replacement)
            finally:
                os.close(fd)

    def test_reader_entry_denies_broker_and_wrong_original_targets_first(self):
        s = self.storage
        request = SimpleNamespace(exact_ref=s.exact_ref,
                                  repository=(s.repository.device, s.repository.inode),
                                  ref_directory=(s.ref_parent.device, s.ref_parent.inode))
        with patch.object(StorageActor, "require_process") as process:
            with self.assertRaisesRegex(ValueError, "ORIGINAL_TARGET"):
                with open_repository(-1, request, s.broker.uid, storage=s, role="broker"):
                    self.fail("writer admitted")
            request.ref_directory = (s.ref_parent.device, s.ref_parent.inode + 1)
            with self.assertRaisesRegex(ValueError, "ORIGINAL_TARGET"):
                with open_repository(-1, request, s.broker.uid, storage=s, role="verifier"):
                    self.fail("foreign ref parent admitted")
            process.assert_not_called()

    def test_signer_checks_bound_role_and_refuses_before_reading_fd(self):
        s = self.storage
        wrong = ExecutorRoles(s.core.uid, s.broker.uid, s.verifier.uid, s.core.gid)
        correct = replace(wrong, broker_gid=s.broker.gid)
        with patch.object(StorageActor, "require_process", side_effect=ValueError("DENIED")) as actor, patch(
            "runtime.red_hat.executor_custody._read_signer_fd"
        ) as read:
            with self.assertRaisesRegex(ValueError, "BROKER_ROLE"):
                load_broker_signer(3, wrong, None, key_epoch=1, now=1, enabled=True, storage=s)
            actor.assert_not_called()
            with patch("runtime.red_hat.role_storage.os.stat", return_value=SimpleNamespace(st_ino=18)):
                with self.assertRaisesRegex(ValueError, "STORAGE_MOUNT_NAMESPACE"):
                    load_broker_signer(3, correct, None, key_epoch=1, now=1, enabled=True, storage=s)
            read.assert_not_called()

    def test_readonly_record_requires_exact_owner_group_and_mode(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work, "evidence")
            path.write_bytes(b"signed evidence")
            path.chmod(0o440)
            gid = path.stat().st_gid
            fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.assertEqual(b"signed evidence", read_record(
                    fd, path.name, os.getuid(), reader_gid=gid))
                with self.assertRaisesRegex(ValueError, "RECORD_STORAGE"):
                    read_record(fd, path.name, os.getuid(), reader_gid=gid + 1)
                with self.assertRaisesRegex(ValueError, "RECORD_STORAGE"):
                    read_record(fd, path.name, os.getuid())
                path.chmod(0o660)
                with self.assertRaisesRegex(ValueError, "RECORD_STORAGE"):
                    read_record(fd, path.name, os.getuid(), reader_gid=gid)
            finally:
                os.close(fd)
