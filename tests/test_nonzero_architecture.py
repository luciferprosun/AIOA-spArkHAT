"""Installed-compatible, baseline-free one-system architecture regression."""
import tempfile
import unittest
from pathlib import Path

import nonzero_cloudops
from tools.nonzero_architecture import inspect_module, inspect_python, verify_ownership


class NativeOneSystemArchitectureTests(unittest.TestCase):
    def test_current_native_tree_has_no_embedded_project(self):
        module = Path(nonzero_cloudops.__file__).parent
        result = inspect_module(module)
        self.assertEqual(result['status'], 'PASS', result['findings'])
        self.assertEqual(result['BASELINE_PATH_EXISTS'], 'NO')
        self.assertEqual(result['NESTED_GIT'], 'NO')
        self.assertEqual(result['SECOND_PACKAGE'], 'NO')

    def test_existing_core_owns_module_authority_and_lifecycle(self):
        self.assertEqual(verify_ownership(Path(nonzero_cloudops.__file__).parent.parent), [])

    def test_static_gate_rejects_old_imports_launchers_network_and_path_hacks(self):
        candidates = ('import aioa_cloudops_agent', 'import subprocess', 'import boto3',
            'import http.server', 'import socket', 'import sys\nsys.path.append("other")',
            'import os\nos.system("command")', '__import__("something")',
            'from importlib import import_module\nimportlib.import_module("something")',
            'value = "git clone"', 'value = "AIOA-Integration-Sandbox"',
            'class SessionManager: pass', 'ProviderManager()')
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertTrue(inspect_python(candidate))

    def test_static_gate_detects_nested_git_manifest_and_retired_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'baseline').mkdir()
            (root/'.git').mkdir()
            (root/'pyproject.toml').write_text('[project]\nname="second"\n')
            result = inspect_module(root)
            self.assertEqual(result['status'], 'FAIL')
            codes = {item['code'] for item in result['findings']}
            self.assertTrue({'BASELINE_PATH_EXISTS', 'NESTED_GIT', 'SECOND_PACKAGE'} <= codes)

    def test_static_gate_rejects_symlinked_native_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'target').mkdir()
            (root/'module').symlink_to(root/'target', target_is_directory=True)
            self.assertEqual(inspect_module(root/'module')['status'], 'FAIL')

    def test_static_gate_accepts_plain_native_domain_imports(self):
        self.assertEqual(inspect_python('from ..models import Run\nfrom tools.provenance import AppendOnlyProvenanceStore\n'), [])
