"""Source-only importer controls use deliberate cache poison only in owned temp dirs."""
import importlib
import json
import os
import py_compile
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path


class SourceOnlyImportControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original_path = list(sys.path)
        self.original_meta = list(sys.meta_path)
        self.original_flag = sys.dont_write_bytecode
        self.addCleanup(self.restore)
        sys.path.insert(0, str(self.root))

    def restore(self):
        sys.path[:] = self.original_path
        sys.meta_path[:] = self.original_meta
        sys.dont_write_bytecode = self.original_flag
        for name in list(sys.modules):
            if name.startswith('nz13_cache_probe'):
                del sys.modules[name]
        importlib.invalidate_caches()

    def support(self):
        path = Path(__file__).with_name('nz13_source_only_imports.py')
        self.assertTrue(path.is_file(), 'SOURCE_ONLY_IMPORT_GUARD_NOT_IMPLEMENTED')
        return types.SimpleNamespace(**runpy.run_path(str(path)))

    def test_valid_timestamp_poison_is_read_by_normal_import_but_never_source_only(self):
        support = self.support()
        path = self.root / 'nz13_cache_probe_poison.py'
        path.write_text("VALUE = 'PYCFAKE'\n", encoding='utf-8')
        before = path.stat()
        py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        path.write_text("VALUE = 'CURRENT'\n", encoding='utf-8')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(before.st_size, path.stat().st_size)
        self.assertEqual('PYCFAKE', importlib.import_module(path.stem).VALUE)
        del sys.modules[path.stem]
        support.install(self.root)
        self.assertEqual('CURRENT', importlib.import_module(path.stem).VALUE)

    def test_source_import_enforces_no_bytecode_writes_even_if_caller_flag_was_false(self):
        support = self.support()
        path = self.root / 'nz13_cache_probe_clean.py'
        path.write_text('VALUE = 7\n', encoding='utf-8')
        sys.dont_write_bytecode = False
        support.install(self.root)
        self.assertIs(sys.dont_write_bytecode, True)
        self.assertEqual(7, importlib.import_module(path.stem).VALUE)
        self.assertFalse((self.root / '__pycache__').exists())

    def test_sourceless_bytecode_in_the_bound_root_is_rejected(self):
        support = self.support()
        path = self.root / 'nz13_cache_probe_only.py'
        path.write_text('VALUE = 1\n', encoding='utf-8')
        py_compile.compile(str(path), cfile=str(path.with_suffix('.pyc')), doraise=True)
        path.unlink()  # Only this newly created private fixture source.
        support.install(self.root)
        with self.assertRaises(ImportError):
            importlib.import_module(path.stem)

    def test_namespace_packages_work_and_unbound_standard_library_is_unchanged(self):
        support = self.support()
        namespace = self.root / 'nz13_cache_probe_namespace'
        namespace.mkdir()
        (namespace / 'value.py').write_text('VALUE = 29\n', encoding='utf-8')
        json_before = json
        finder = support.install(self.root)
        self.assertIn(finder, sys.meta_path)
        self.assertEqual(29, importlib.import_module('nz13_cache_probe_namespace.value').VALUE)
        self.assertIs(json_before, importlib.import_module('json'))
        self.assertFalse((namespace / '__pycache__').exists())
