"""Prepared P05 negative contracts; UNAPPLIED/NOT RUN during Wave A freeze.

The intended package lock is inert operator input. These tests must not install
or import package content on the host; real installation belongs in the one
LinuxSandboxBroker acceptance, followed by independent Core observation.
"""
import base64
import csv
import hashlib
import importlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

DIST = 'fixture_math-1.0.0.dist-info'
FILENAME = 'fixture_math-1.0.0-py3-none-any.whl'


def wheel_bytes(*, extras=(), metadata=None, record_override=None, symlink=False, package=None):
    """Build a tiny local fixture, never download a package or execute its code."""
    entries = [
        ('fixture_math/__init__.py', package or b'def twice(value):\n    return value * 2\n'),
        (DIST + '/METADATA', metadata or b'Metadata-Version: 2.1\nName: fixture-math\nVersion: 1.0.0\n\n'),
        (DIST + '/WHEEL', b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n'),
        *extras,
    ]
    record = io.StringIO()
    writer = csv.writer(record, lineterminator='\n')
    for name, raw in entries:
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b'=').decode()
        writer.writerow([name, 'sha256=' + digest, len(raw)])
    writer.writerow([DIST + '/RECORD', '', ''])
    entries.append((DIST + '/RECORD', record_override or record.getvalue().encode()))
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning, message='Duplicate name:.*')
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, raw in entries:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                if symlink and name == 'fixture_math/__init__.py':
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, raw)
    return output.getvalue()


class LockedWheelTests(unittest.TestCase):
    def api(self):
        name = 'runtime.mission.dependency_lock'
        self.assertIsNotNone(importlib.util.find_spec(name), 'P05 closed wheel lock contract is missing')
        module = importlib.import_module(name)
        for symbol in ('LockedWheel', 'PythonWheelLock'):
            self.assertTrue(callable(getattr(module, symbol, None)), symbol + ' is missing')
        return module

    def locked(self, raw=None, *, filename=FILENAME, digest=None):
        raw = wheel_bytes() if raw is None else raw
        return self.api().LockedWheel(
            distribution='fixture-math', version='1.0.0', filename=filename,
            sha256=hashlib.sha256(raw).hexdigest() if digest is None else digest,
            content=raw,
        )

    def test_locked_fixture_is_data_only_and_binds_exact_bytes(self):
        raw = wheel_bytes()
        wheel = self.locked(raw)
        lock = self.api().PythonWheelLock((wheel,))
        value = json.loads(lock.manifest_bytes())
        self.assertEqual('aioa.python-wheel-lock.v1', value['schema'])
        self.assertEqual('NONE', value['authority'])
        self.assertEqual('OFF', value['network'])
        self.assertEqual([{'distribution': 'fixture-math', 'version': '1.0.0', 'filename': FILENAME,
                           'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}], value['wheels'])
        self.assertEqual(hashlib.sha256(lock.manifest_bytes()).hexdigest(), lock.digest)
        self.assertNotIn('def twice', repr(wheel))
        self.assertNotIn('content', value['wheels'][0])
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            wheel.content = b'changed'

    def test_pinned_package_is_never_imported_or_executed_during_host_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'package-was-executed'
            code = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("unexpected")\n').encode()
            wheel = self.locked(wheel_bytes(package=code))
            lock = self.api().PythonWheelLock((wheel,))
            lock.manifest_bytes()
            lock.inputs()
            self.assertFalse(marker.exists(), 'Package code executed on the host')
            self.assertNotIn('fixture_math', sys.modules)

    def test_missing_or_changed_hash_refuses_before_archive_inspection(self):
        for digest in ('0' * 64, '', True, None):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.locked(digest=digest if digest is not None else 'not-a-sha256')
        original = self.locked()
        with self.assertRaises(ValueError):
            replace(original, content=original.content + b'changed')

    def test_wheel_filename_and_distribution_are_not_paths_or_urls(self):
        for filename in ('../' + FILENAME, '/tmp/' + FILENAME, 'https://invalid/' + FILENAME,
                         'fixture_math-1.0.0-cp312-cp312-linux_x86_64.whl', 'fixture_math-2.0.0-py3-none-any.whl'):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.locked(filename=filename)

    def test_archive_traversal_absolute_and_case_collision_are_refused(self):
        for path in ('../escape.py', '/tmp/escape.py', 'fixture_math/../escape.py',
                     'fixture_math\\escape.py', 'FIXTURE_MATH/__INIT__.PY'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.locked(wheel_bytes(extras=((path, b'pass\n'),)))

    def test_archive_size_and_member_count_are_rejected_before_install(self):
        cases = (
            wheel_bytes(extras=(('fixture_math/oversize.txt', b'X' * 1048577),)),
            wheel_bytes(extras=tuple(('fixture_math/data_' + str(i) + '.txt', b'x') for i in range(257))),
        )
        for raw in cases:
            with self.subTest(bytes=len(raw)), self.assertRaises(ValueError):
                self.locked(raw)

    def test_symbolic_links_and_duplicate_entries_are_refused(self):
        with self.assertRaises(ValueError):
            self.locked(wheel_bytes(symlink=True))
        with self.assertRaises(ValueError):
            self.locked(wheel_bytes(extras=(('fixture_math/__init__.py', b'changed\n'),)))

    def test_startup_hooks_scripts_entrypoints_and_native_code_are_unsupported(self):
        for path in ('sitecustomize.py', 'usercustomize.py', 'bootstrap.pth',
                     DIST + '/entry_points.txt', 'fixture_math-1.0.0.data/scripts/install',
                     'fixture_math/native.so', 'setup.py', 'postinstall.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.locked(wheel_bytes(extras=((path, b'print("not executed")\n'),)))

    def test_unlocked_requires_dist_and_wrong_package_metadata_are_refused(self):
        for metadata in (
            b'Metadata-Version: 2.1\nName: fixture-math\nVersion: 1.0.0\nRequires-Dist: surprise>=1\n\n',
            b'Metadata-Version: 2.1\nName: foreign-package\nVersion: 1.0.0\n\n',
            b'Metadata-Version: 2.1\nName: fixture-math\nVersion: 9.0.0\n\n',
            b'Metadata-Version: 2.1\nName: fixture-math\nName: duplicate\nVersion: 1.0.0\n\n',
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.locked(wheel_bytes(metadata=metadata))

    def test_record_must_cover_exact_archive_with_sha256_and_size(self):
        for record in (b'', b'fixture_math/__init__.py,,\n', b'../escape.py,sha256=wrong,5\n',
                       (DIST + '/RECORD,,\n').encode()):
            # Empty override uses an explicit malformed nonempty record, since
            # the fixture helper's default is a valid generated RECORD.
            raw = wheel_bytes(record_override=record or b'\n')
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.locked(raw)

    def test_unknown_zip_and_content_types_never_become_an_install_recipe(self):
        for raw in (b'', b'not a wheel', b'PK\x03\x04', None, bytearray(b'not a wheel')):
            with self.subTest(kind=type(raw).__name__), self.assertRaises((ValueError, TypeError)):
                self.api().LockedWheel(distribution='fixture-math', version='1.0.0', filename=FILENAME,
                                       sha256='0' * 64, content=raw)

    def test_lock_is_closed_bounded_and_does_not_deduplicate_silently(self):
        wheel = self.locked()
        cls = self.api().PythonWheelLock
        for wheels in ([], (), (wheel, wheel), (wheel,) * 4, ({'approved': True},)):
            with self.subTest(kind=type(wheels).__name__, count=len(wheels)), self.assertRaises(ValueError):
                cls(wheels)

    def test_declared_install_inputs_are_hash_bound_and_contain_no_shell_command(self):
        wheel = self.locked()
        lock = self.api().PythonWheelLock((wheel,))
        inputs = lock.inputs()
        self.assertEqual({'python-wheel-lock.json', FILENAME}, set(inputs))
        self.assertEqual(lock.manifest_bytes(), inputs['python-wheel-lock.json'])
        self.assertEqual(wheel.content, inputs[FILENAME])
        self.assertNotIn('pip install', json.dumps(json.loads(lock.manifest_bytes())))


if __name__ == '__main__':
    unittest.main()
