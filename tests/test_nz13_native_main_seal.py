"""Main-only drift fences a synthetic Native host before any mocked dispatch."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from runtime.core_admission import AdmissionError
from runtime.meta_hackathon import runtime_adapter as api


class NativeMainSealTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source_root = self.root / 'synthetic-source'
        for relative in set(api.SOURCE_FILES) | {'runtime/main.py'}:
            path = self.source_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC_SOURCE_ONLY\n')
        self.enterContext(patch.object(api, 'ROOT', self.source_root))
        self.enterContext(patch.object(api.subprocess, 'run',
                                      return_value=SimpleNamespace(stdout='a' * 40)))
        authentication = {'uid': os.getuid(), 'test_only': True}
        with patch.object(api, '_desktop_operator_uid', return_value=(os.getuid(), authentication)):
            self.host = api.NativeMobileComposition(
                self.root / 'synthetic-native-state', origin='https://host.example.org',
                source_probe=api.current_source, key_path=self.root / 'unused-provider-key')
        self.addCleanup(self.host.close)
        self.initial = self.host.source
        self.assertIsNotNone(self.host.operator_principal())
        self.assertIs(self.host.runtime._memory_patch_admission, self.host.core)
        self.assertIs(self.host.ledger.core, self.host.core)
        self.assertIsNone(self.host.runtime.provider_manager)
        self.assertIsNone(self.host.runtime.executor)
        self.assertEqual(0, self.host.model_calls())

    def test_main_is_sealed_exactly_once(self):
        self.assertEqual(1, api.SOURCE_FILES.count('runtime/main.py'))

    def test_same_head_main_drift_fences_each_operator_dispatch(self):
        (self.source_root / 'runtime/main.py').write_bytes(b'CHANGED_SYNTHETIC_MAIN\n')
        self.assertEqual(self.initial[0], api.current_source()[0])
        for operation in ('github_prepare', 'github_approve', 'github_apply'):
            with self.subTest(operation=operation), \
                    patch('runtime.meta_hackathon.github_write.dispatch', return_value={'mock_only': True}) as dispatch:
                with self.assertRaises(AdmissionError):
                    self.host.operator_request(os.getuid(), {'op': operation})
                dispatch.assert_not_called()

    def test_existing_sealed_path_is_a_positive_drift_control(self):
        (self.source_root / 'runtime/core_admission.py').write_bytes(b'CHANGED_EXISTING_SOURCE\n')
        with self.assertRaises(AdmissionError):
            self.host.operator_principal()

    def test_missing_main_fences_before_dispatch(self):
        (self.source_root / 'runtime/main.py').unlink()
        with patch('runtime.meta_hackathon.github_write.dispatch') as dispatch:
            with self.assertRaises((AdmissionError, ValueError, OSError)):
                self.host.operator_request(os.getuid(), {'op': 'github_prepare'})
            dispatch.assert_not_called()

    def test_symlink_main_fences_before_dispatch(self):
        path = self.source_root / 'runtime/main.py'
        path.unlink()
        path.symlink_to(self.source_root / 'runtime/core_admission.py')
        with patch('runtime.meta_hackathon.github_write.dispatch') as dispatch:
            with self.assertRaises((AdmissionError, ValueError, OSError)):
                self.host.operator_request(os.getuid(), {'op': 'github_prepare'})
            dispatch.assert_not_called()

    def test_unchanged_source_allows_only_the_mocked_dispatch_control(self):
        with patch('runtime.meta_hackathon.github_write.dispatch', return_value={'mock_only': True}) as dispatch:
            value = self.host.operator_request(os.getuid(), {'op': 'github_prepare'})
        self.assertEqual({'mock_only': True}, value)
        self.assertEqual(1, dispatch.call_count)
        self.assertEqual(self.initial, api.current_source())
        self.assertEqual(40, len(self.host.source[0]))


    def test_pytest_contract_is_sealed_exactly_once(self):
        self.assertEqual(1, api.SOURCE_FILES.count('runtime/mission/python_test_contracts.py'))

    def test_same_head_pytest_contract_drift_fences_before_owner_dispatch(self):
        path = self.source_root / 'runtime/mission/python_test_contracts.py'
        path.write_bytes(b'CHANGED_SYNTHETIC_PYTEST_CONTRACT\n')
        self.assertEqual(self.initial[0], api.current_source()[0])
        with patch('runtime.meta_hackathon.github_write.dispatch') as dispatch:
            with self.assertRaises(AdmissionError):
                self.host.operator_request(os.getuid(), {'op': 'github_prepare'})
            dispatch.assert_not_called()
