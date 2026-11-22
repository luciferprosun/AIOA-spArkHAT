"""Exercise the broker's real file publication without an external target."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.providers.exact import CancellationToken

REF_BYTES = b'a' * 40 + b'\n'
REF_NAME = 'private-ref'


class NativeGitPublicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ref = self.root / REF_NAME
        self.parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, self.parent)

    def test_process_exit_around_link_has_no_success_ack(self):
        for stage in ('before-link', 'after-link', 'after-directory-sync'):
            with self.subTest(stage=stage):
                completed = subprocess.run(
                    [sys.executable, '-B', __file__, str(self.root), stage],
                    capture_output=True, timeout=15, check=False,
                )
                self.assertEqual(75, completed.returncode, completed.stderr)
                self.assertEqual(b'', completed.stdout)
                self.assertEqual(stage != 'before-link', self.ref.exists())
                if self.ref.exists():
                    self.assertEqual(REF_BYTES, self.ref.read_bytes())
                    self.ref.unlink()

    def test_preexisting_equal_ref_stays_on_original_inode(self):
        self.ref.write_bytes(REF_BYTES)
        before = self.ref.stat()
        self.assertFalse(LinuxSandboxBroker._git_publish_new(self.parent, REF_NAME, REF_BYTES, cancel=None))
        self.assertEqual(before.st_ino, self.ref.stat().st_ino)
        self.assertEqual(REF_BYTES, self.ref.read_bytes())

    def test_success_ack_follows_file_sync_link_and_directory_sync(self):
        link, fsync = os.link, os.fsync
        events = []

        def sync(fd):
            fsync(fd)
            events.append('directory-sync' if fd == self.parent else 'file-sync')

        def publish(*args, **kwargs):
            self.assertFalse(self.ref.exists())
            link(*args, **kwargs)
            self.assertEqual(REF_BYTES, self.ref.read_bytes())
            events.append('link')

        with patch.object(os, 'link', publish), patch.object(os, 'fsync', sync):
            self.assertTrue(LinuxSandboxBroker._git_publish_new(self.parent, REF_NAME, REF_BYTES, cancel=None))
        self.assertEqual(['file-sync', 'link', 'directory-sync'], events)

    def test_stop_before_link_leaves_ref_absent(self):
        token = CancellationToken()
        fsync = os.fsync

        def sync_and_stop(fd):
            fsync(fd)
            token.cancel()

        with (patch.object(os, 'fsync', sync_and_stop),
              self.assertRaisesRegex(ValueError, '^GIT_PLUMBING_CANCELLED$')):
            LinuxSandboxBroker._git_publish_new(self.parent, REF_NAME, REF_BYTES, cancel=token)
        self.assertFalse(self.ref.exists())

    def test_equal_bytes_on_replacement_inode_fail_publication_binding(self):
        link = os.link
        replacement = self.root / 'replacement'
        replacement.write_bytes(REF_BYTES)
        original_inode = replacement.stat().st_ino

        def link_then_replace(*args, **kwargs):
            link(*args, **kwargs)
            replacement.replace(self.ref)

        with (patch.object(os, 'link', link_then_replace),
              self.assertRaisesRegex(ValueError, '^GIT_PUBLISHED_NAME_CHANGED$')):
            LinuxSandboxBroker._git_publish_new(self.parent, REF_NAME, REF_BYTES, cancel=None)
        self.assertEqual(original_inode, self.ref.stat().st_ino)
        self.assertEqual(REF_BYTES, self.ref.read_bytes())


def exit_at_publication_boundary(root, stage):
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    link, fsync = os.link, os.fsync

    def sync(fd):
        fsync(fd)
        if stage == 'after-directory-sync' and fd == parent:
            os._exit(75)

    def publish(*args, **kwargs):
        if stage == 'before-link':
            os._exit(75)
        link(*args, **kwargs)
        if stage == 'after-link':
            os._exit(75)

    try:
        with patch.object(os, 'link', publish), patch.object(os, 'fsync', sync):
            print(LinuxSandboxBroker._git_publish_new(parent, REF_NAME, REF_BYTES, cancel=None))
    finally:
        os.close(parent)


if __name__ == '__main__':
    exit_at_publication_boundary(Path(sys.argv[1]), sys.argv[2])
