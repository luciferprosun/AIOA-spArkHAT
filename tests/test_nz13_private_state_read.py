"""Actual FD/type/identity boundaries of the shared private JSON reader."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nonzero_cloudops.state import files


class PrivateStateReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'state.json'
        self.raw = b'{"value":1}\n'
        self.path.write_bytes(self.raw)
        self.path.chmod(0o600)

    def read(self, **kwargs):
        return files.read_private_json(self.path, **kwargs)

    def after_read(self, action):
        original = os.fdopen

        class ControlledRead:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def read(self, *args, **kwargs):
                data = self.stream.read(*args, **kwargs)
                action()
                return data

            def fileno(self):
                return self.stream.fileno()

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

        def wrap(*args, **kwargs):
            return ControlledRead(original(*args, **kwargs))
        return patch.object(files.os, 'fdopen', wrap)

    def test_private_regular_file_reads_without_mutation(self):
        before = self.path.stat()
        self.assertEqual({'value': 1}, self.read())
        after = self.path.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns),
                         (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_hardlinked_input_is_denied_before_parsing(self):
        alias = self.root / 'alias.json'
        os.link(self.path, alias)
        with self.assertRaises(files.StateIntegrityError):
            self.read()
        self.assertEqual(self.raw, self.path.read_bytes())
        self.assertEqual(self.raw, alias.read_bytes())

    def test_parent_symlink_is_denied(self):
        actual = self.root / 'actual'
        actual.mkdir(mode=0o700)
        target = actual / 'state.json'
        target.write_bytes(self.raw)
        target.chmod(0o600)
        alias = self.root / 'alias'
        alias.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(files.StateIntegrityError):
            files.read_private_json(alias / 'state.json')
        self.assertEqual(self.raw, target.read_bytes())

    def test_final_symlink_is_denied(self):
        alias = self.root / 'link.json'
        alias.symlink_to(self.path)
        with self.assertRaises((files.StateIntegrityError, OSError)):
            files.read_private_json(alias)
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_fifo_is_opened_nonblocking_and_then_denied(self):
        fifo = self.root / 'fifo.json'
        os.mkfifo(fifo, 0o600)
        original = os.open

        def checked(path, flags, *args, **kwargs):
            if Path(path) == fifo:
                self.assertTrue(flags & os.O_NONBLOCK, 'reader could block before file type validation')
            return original(path, flags, *args, **kwargs)

        with patch.object(files.os, 'open', checked), self.assertRaises(files.StateIntegrityError):
            files.read_private_json(fifo)

    def test_group_readable_input_is_denied(self):
        self.path.chmod(0o640)
        with self.assertRaises(files.StateIntegrityError):
            self.read()

    def test_exact_byte_limit_is_accepted(self):
        self.assertEqual({'value': 1}, self.read(max_bytes=len(self.raw)))

    def test_oversize_is_denied(self):
        with self.assertRaises(files.StateIntegrityError):
            self.read(max_bytes=len(self.raw) - 1)

    def test_duplicate_json_keys_are_denied(self):
        self.path.write_bytes(b'{"value":1,"value":2}')
        with self.assertRaises(files.StateIntegrityError):
            self.read()

    def test_nonfinite_json_is_denied(self):
        self.path.write_bytes(b'{"value":NaN}')
        with self.assertRaises(files.StateIntegrityError):
            self.read()

    def test_invalid_utf8_is_denied(self):
        self.path.write_bytes(b'{"value":"\xff"}')
        with self.assertRaises(files.StateIntegrityError):
            self.read()

    def test_truncate_or_extend_after_read_is_denied(self):
        def change():
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
            try:
                os.write(fd, b' ')
            finally:
                os.close(fd)
        with self.after_read(change), self.assertRaises(files.StateIntegrityError):
            self.read()
        self.assertEqual(self.raw + b' ', self.path.read_bytes())

    def test_same_size_content_change_with_restored_mtime_is_denied(self):
        before = self.path.stat()

        def change():
            fd = os.open(self.path, os.O_WRONLY)
            try:
                os.write(fd, b'{"value":2}\n')
            finally:
                os.close(fd)
            os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.after_read(change), self.assertRaises(files.StateIntegrityError):
            self.read()
        self.assertEqual(b'{"value":2}\n', self.path.read_bytes())

    def test_named_inode_replacement_after_read_is_denied(self):
        replacement = self.root / 'replacement.json'
        replacement.write_bytes(b'{"value":2}\n')
        replacement.chmod(0o600)
        with self.after_read(lambda: os.replace(replacement, self.path)), self.assertRaises(files.StateIntegrityError):
            self.read()
        self.assertEqual(b'{"value":2}\n', self.path.read_bytes())

    def test_hardlink_created_after_read_is_denied(self):
        alias = self.root / 'late-alias.json'
        with self.after_read(lambda: os.link(self.path, alias)), self.assertRaises(files.StateIntegrityError):
            self.read()
        self.assertEqual(self.raw, alias.read_bytes())

    def test_mode_changed_after_read_is_denied(self):
        with self.after_read(lambda: self.path.chmod(0o640)), self.assertRaises(files.StateIntegrityError):
            self.read()
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_excessive_json_depth_is_a_typed_denial(self):
        self.path.write_bytes(b'[' * 2000 + b'\n')
        caught = None
        try:
            self.read()
        except (files.StateIntegrityError, RecursionError) as error:
            caught = error
        self.assertIsInstance(caught, files.StateIntegrityError)

    def test_valid_wire_bytes_are_unchanged(self):
        value = {'format_version': 1, 'resources': [], 'receipts': []}
        files.atomic_write_private_json(self.path, value)
        expected = (json.dumps(value, allow_nan=False, ensure_ascii=True,
                               indent=2, sort_keys=True) + '\n').encode()
        self.assertEqual(expected, self.path.read_bytes())
        self.assertEqual(value, self.read())
        self.assertEqual(expected, self.path.read_bytes())

    def test_atomic_replace_between_separate_reads_is_supported(self):
        self.assertEqual({'value': 1}, self.read())
        files.atomic_write_private_json(self.path, {'value': 2})
        self.assertEqual({'value': 2}, self.read())

    def test_fifo_substitution_after_path_check_reaches_nonblocking_fd(self):
        real_validate, real_open = files.validate_local_path, os.open
        swapped, opened_types = [], []

        def validate(path):
            real_validate(path)
            if Path(path) == self.path and not swapped:
                self.path.unlink()
                os.mkfifo(self.path, 0o600)
                swapped.append(True)

        def opened(path, flags, *args, **kwargs):
            if Path(path) == self.path:
                self.assertTrue(flags & os.O_NONBLOCK, 'unsafe substituted FIFO open')
            fd = real_open(path, flags, *args, **kwargs)
            if Path(path) == self.path:
                opened_types.append(stat.S_ISFIFO(os.fstat(fd).st_mode))
            return fd

        with (
            patch.object(files, 'validate_local_path', validate),
            patch.object(files.os, 'open', opened),
            self.assertRaises(files.StateIntegrityError),
        ):
            self.read()
        self.assertEqual([True], swapped)
        self.assertEqual([True], opened_types)

    def test_leaf_symlink_substitution_after_path_check_is_not_followed(self):
        real_validate = files.validate_local_path
        victim = self.root / 'victim.json'
        victim.write_bytes(b'{"value":2}\n')
        victim.chmod(0o600)
        swapped = []

        def validate(path):
            real_validate(path)
            if Path(path) == self.path and not swapped:
                self.path.unlink()
                self.path.symlink_to(victim)
                swapped.append(True)

        with (
            patch.object(files, 'validate_local_path', validate),
            self.assertRaises((files.StateIntegrityError, OSError)),
        ):
            self.read()
        self.assertEqual([True], swapped)
        self.assertEqual(b'{"value":2}\n', victim.read_bytes())

    def test_boolean_integrity_version_is_not_integer_version_one(self):
        envelope = files.seal_local_payload({'value': 1}, payload_type='AIOA_TEST_READ')
        envelope['integrity_version'] = True
        with self.assertRaises(files.StateIntegrityError):
            files.open_local_payload(envelope, payload_type='AIOA_TEST_READ')


if __name__ == '__main__':
    unittest.main()
