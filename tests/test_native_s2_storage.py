"""Offline controller state, actual raw-file I/O and failure atomicity."""

import errno
import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.authenticated_boundary import _open_seal
from runtime.red_hat.s2_admission import WRITER_SCHEMA
from scripts.unification.native_s2 import storage


class NativeS2StorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.volume = hashlib.sha256(b"disposable disk").hexdigest()
        self.disk = self.root / "disk.raw"
        self.disk.write_bytes(bytes(8192))
        self.disk.chmod(0o600)
        storage.initialize(self.root, self.volume)
        self.first = storage.advance(self.root, self.volume, 0)
        self.old = storage.Export(self.root, self.first)
        self.addCleanup(self.old.close)

    def test_concurrent_successors_fence_open_handle_and_cloned_credential(self):
        rendezvous = threading.Barrier(2, timeout=5)
        def rotate():
            rendezvous.wait()
            try:
                return storage.advance(self.root, self.volume, 1)
            except storage.Fenced:
                return None
        self.old.write(b"live", 0)
        with ThreadPoolExecutor(2) as pool:
            candidates = list(pool.map(lambda _: rotate(), range(2)))
        winners = [name for name in candidates if name]
        self.assertEqual(1, len(winners))
        with self.assertRaises(storage.Fenced):
            self.old.write(b"past", 0)
        with self.assertRaises(storage.Fenced):
            storage.Export(self.root, self.first)
        with closing(storage.Export(self.root, winners[0])) as new:
            self.assertEqual(b"live", new.read(4, 0))
            new.write(b"next", 0)
        self.assertEqual(b"next", self.disk.read_bytes()[:4])
        with self.assertRaises(storage.Fenced):
            storage.Export(self.root, winners[0])

    def test_racing_write_finishes_before_successor_becomes_visible(self):
        entered, release, rotating = threading.Event(), threading.Event(), threading.Event()
        def pause(fd, data, offset):
            entered.set()
            self.assertTrue(release.wait(5))
            return real_write(fd, data, offset)
        def advance():
            rotating.set()
            return storage.advance(self.root, self.volume, 1)
        real_write = os.pwrite
        with ThreadPoolExecutor(2) as pool, patch.object(os, "pwrite", side_effect=pause):
            old_write = pool.submit(self.old.write, b"old", 0)
            self.assertTrue(entered.wait(5))
            rotation = pool.submit(advance)
            self.assertTrue(rotating.wait(5))
            self.assertFalse(rotation.done())
            release.set()
            old_write.result(timeout=5)
            with closing(storage.Export(self.root, rotation.result(timeout=5))) as new:
                self.assertEqual(b"old", new.read(3, 0))
        with self.assertRaises(storage.Fenced):
            self.old.flush()

    def test_generation_fault_is_sticky_and_outlives_reconnection(self):
        with patch.object(os, "fsync", side_effect=OSError(errno.EIO, "test I/O")):
            with self.assertRaises(OSError):
                self.old.write(b"?", 0)
        with self.assertRaisesRegex(storage.Fenced, "UNCERTAIN"):
            self.old.write(b"!", 0)
        with self.assertRaises(storage.Fenced):
            storage.check_attached(self.root, self.volume, self.first)
        storage.advance(self.root, self.volume, 1)
        with closing(sqlite3.connect(self.root / "controller.sqlite3")) as db:
            self.assertEqual((1,), db.execute("SELECT faulted FROM retired WHERE generation=1").fetchone())

    def test_replaced_disk_wrong_volume_and_failed_rotation_do_not_grant(self):
        with self.assertRaises(storage.Fenced):
            storage.advance(self.root, "0" * 64, 1)
        with patch.object(os, "fsync", side_effect=OSError(errno.EIO, "test flush")):
            with self.assertRaises(OSError):
                storage.advance(self.root, self.volume, 1)
        self.old.write(b"x", 0)
        self.disk.rename(self.root / "saved.raw")
        self.disk.write_bytes((self.root / "saved.raw").read_bytes())
        self.disk.chmod(0o600)
        with self.assertRaisesRegex(storage.Fenced, "DISK_REPLACED"):
            storage.advance(self.root, self.volume, 1)

    def test_lost_management_database_denies_open_io_and_never_reinitializes(self):
        path = self.root / "controller.sqlite3"
        path.rename(self.root / "management-disconnected")
        with self.assertRaises(FileNotFoundError):
            self.old.write(b"offline", 0)
        with self.assertRaises(FileExistsError):
            storage.initialize(self.root, self.volume)
        self.assertFalse(path.exists())
        self.assertEqual(bytes(8192), self.disk.read_bytes())

    def test_live_challenge_only_for_exact_attached_approved_start(self):
        signer = Identity(ec.generate_private_key(ec.SECP256R1()))
        ref = "refs/heads/aioa/nz11-" + "a" * 32
        query = {"schema": WRITER_SCHEMA, "volume_sha256": self.volume, "generation": 1,
                 "boot_sha256": "b" * 64, "storage_sha256": "c" * 64, "exact_ref": ref,
                 "binding_sha256": "d" * 64, "challenge": "e" * 64}
        with self.assertRaisesRegex(storage.Fenced, "NOT_ARMED"):
            storage.writer_readback(self.root, query, signer)
        storage.arm(self.root, self.volume, 1, "b" * 64, "c" * 64, ref, "d" * 64)
        self.assertEqual(query, _open_seal(storage.writer_readback(self.root, query, signer), signer.spki, WRITER_SCHEMA))
        for field in ("volume_sha256", "binding_sha256", "exact_ref", "boot_sha256"):
            with self.subTest(field=field), self.assertRaises(storage.Fenced):
                storage.writer_readback(self.root, dict(query, **{field: "0" * 64}), signer)
        storage.advance(self.root, self.volume, 1)
        with self.assertRaises(storage.Fenced):
            storage.writer_readback(self.root, query, signer)
