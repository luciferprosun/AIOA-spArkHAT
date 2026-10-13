"""Fresh-process import provenance, foreign HOME denial and fixture drift checks."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from native_subprocess_support import FIXTURES, native_command


class NativeSubprocessSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.foreign = Path(self.temp.name)
        self.marker = self.foreign / 'foreign-executed'
        self.env = dict(os.environ, HOME=str(self.foreign), PYTHONPATH=str(self.foreign),
                        PYTHONUSERBASE=str(self.foreign))

    def child(self, command):
        return subprocess.run(command, cwd=self.foreign, env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_real_fixtures_import_from_pinned_source_in_isolated_child(self):
        for name in FIXTURES:
            (self.foreign / (name + '.py')).write_text('raise AssertionError("foreign fixture")\n')
        code = '''
import json, sys
from pathlib import Path
import test_dual_governor, mission_completion_support, nv03_support
assert sys.flags.isolated and sys.flags.no_user_site and sys.flags.ignore_environment
tests = Path(sys.argv[1])
for module in (test_dual_governor, mission_completion_support, nv03_support):
    assert Path(module.__file__).parent == tests
assert sys.argv[2] == 'native-argument'
print('PINNED_NATIVE_IMPORTS_PASS')
'''
        result = self.child(native_command(__file__, code, Path(__file__).resolve().parent,
                                           'native-argument'))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('PINNED_NATIVE_IMPORTS_PASS', result.stdout.strip())

    def test_foreign_home_module_is_not_importable(self):
        source = 'from pathlib import Path\nPath(' + repr(str(self.marker)) + ').touch()\n'
        (self.foreign / 'foreign_home_fixture.py').write_text(source)
        result = self.child(native_command(__file__, 'import foreign_home_fixture'))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("ModuleNotFoundError: No module named 'foreign_home_fixture'", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_changed_fixture_bytes_fail_before_probe_execution(self):
        for name in FIXTURES:
            with self.subTest(fixture=name):
                # Mutate only a disposable fixture copy after its parent pins the bytes.
                copied_tests = self.foreign / name / 'tests'
                copied_tests.mkdir(parents=True)
                source_tests = Path(__file__).resolve().parent
                for fixture in (*FIXTURES, 'native_subprocess_support'):
                    (copied_tests / (fixture + '.py')).write_bytes(
                        (source_tests / (fixture + '.py')).read_bytes())
                copied_runtime = copied_tests.parent / 'runtime'
                copied_runtime.mkdir()
                (copied_runtime / '__init__.py').write_text('"""Inert drift-test fixture."""\n')
                spec = importlib.util.spec_from_file_location(
                    'copied_native_support', copied_tests / 'native_subprocess_support.py')
                helper = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(helper)
                command = helper.native_command(copied_tests / 'test_probe.py',
                                                "print('PROBE_EXECUTED')")
                changed = copied_tests / (name + '.py')
                changed.write_bytes(changed.read_bytes() + b'\nraise AssertionError("altered fixture")\n')
                result = self.child(command)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('NATIVE_FIXTURE_BYTES_DRIFT', result.stderr)
                self.assertNotIn('PROBE_EXECUTED', result.stdout)

    def test_foreign_fixture_origin_fails_before_module_execution(self):
        fixture = self.foreign / 'test_dual_governor.py'
        fixture.write_text('from pathlib import Path\nPath(' + repr(str(self.marker)) + ').touch()\n')
        command = native_command(__file__, "print('PROBE_EXECUTED')")
        command[4] = '''
import importlib.abc, importlib.util, sys
class ForeignOrigin(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'test_dual_governor':
            return importlib.util.spec_from_file_location(fullname, ''' + repr(str(fixture)) + ''')
sys.meta_path.insert(0, ForeignOrigin())
''' + command[4]
        result = self.child(command)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('NATIVE_FIXTURE_ORIGIN_DRIFT', result.stderr)
        self.assertNotIn('PROBE_EXECUTED', result.stdout)
        self.assertFalse(self.marker.exists())

    def test_foreign_caller_cannot_rebind_the_source_root(self):
        with self.assertRaisesRegex(ValueError, 'NATIVE_CALLER_PATH_DRIFT'):
            native_command(self.foreign / 'test_foreign.py', "print('PROBE_EXECUTED')")
