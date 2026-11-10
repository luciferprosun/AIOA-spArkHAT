"""Same-HEAD source drift fences an owned synthetic Native before dispatch."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from runtime.core_admission import AdmissionError
from runtime.meta_hackathon import runtime_adapter as api

G08_DRIFT_PATHS = (
    'runtime/nonzero_cloudops/adapters/portable.py',
    'runtime/nonzero_cloudops/state/files.py',
    'runtime/nonzero_cloudops/models/contracts.py',
    'runtime/nonzero_cloudops/models/digest.py',
    'lab/archaioa/canonical.py',
    'lab/archaioa/contracts.py',
    'lab/archaioa/outcome.py',
    'lab/archaioa/faults.py',
    'runtime/nonzero_cloudops/models/__init__.py',
    'lab/archaioa/__init__.py',
    'runtime/__init__.py',
    'runtime/memory_patch/adapters/cockroach/repositories.py',
    'runtime/memory_patch/persistence/retry.py',
    'runtime/mission/completion.py',
    'runtime/mission/jobs.py',
    'runtime/mission/job_contracts.py',
)


class NativeMainSealTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source_root = self.root / 'synthetic-source'
        for relative in set(api.SOURCE_FILES) | set(G08_DRIFT_PATHS):
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

    def _assert_source_denied_before_dispatch(self, errors=(AdmissionError,)):
        with patch('runtime.meta_hackathon.github_write.dispatch',
                   return_value={'mock_only': True}) as dispatch:
            denied = False
            try:
                self.host.operator_request(os.getuid(), {'op': 'github_prepare'})
            except errors:
                denied = True
            self.assertEqual((True, 0), (denied, dispatch.call_count),
                             'Source gate must refuse drift before the existing dispatcher')

    def test_same_head_physical_core_dependency_drift_fences_before_dispatch(self):
        for relative in G08_DRIFT_PATHS:
            with self.subTest(path=relative):
                path = self.source_root / relative
                original = path.read_bytes()
                try:
                    path.write_bytes(b'CHANGED_SYNTHETIC_DEPENDENCY_ONLY\n')
                    self.assertEqual(self.initial[0], api.current_source()[0])
                    self._assert_source_denied_before_dispatch()
                finally:
                    path.write_bytes(original)
        self.assertEqual(self.initial, api.current_source())

    def test_missing_physical_core_dependencies_fence_before_dispatch(self):
        for relative in G08_DRIFT_PATHS:
            with self.subTest(path=relative):
                path = self.source_root / relative
                original = path.read_bytes()
                path.unlink()
                try:
                    self._assert_source_denied_before_dispatch((AdmissionError, ValueError, OSError))
                finally:
                    path.write_bytes(original)
        self.assertEqual(self.initial, api.current_source())

    def test_symlink_physical_core_dependency_leaves_fence_before_dispatch(self):
        target = self.root / 'synthetic-unsealed-copy'
        for relative in G08_DRIFT_PATHS:
            with self.subTest(path=relative):
                path = self.source_root / relative
                original = path.read_bytes()
                target.write_bytes(original)
                path.unlink()
                path.symlink_to(target)
                try:
                    self._assert_source_denied_before_dispatch((AdmissionError, ValueError, OSError))
                finally:
                    path.unlink()
                    path.write_bytes(original)
        self.assertEqual(self.initial, api.current_source())

    def test_symlink_physical_core_dependency_parents_fence_before_dispatch(self):
        parents = sorted({str(Path(name).parent) for name in G08_DRIFT_PATHS})
        for index, relative in enumerate(parents):
            with self.subTest(parent=relative):
                path = self.source_root / relative
                moved = self.root / f'synthetic-parent-{index}'
                path.rename(moved)
                path.symlink_to(moved, target_is_directory=True)
                try:
                    self._assert_source_denied_before_dispatch((AdmissionError, ValueError, OSError))
                finally:
                    path.unlink()
                    moved.rename(path)
        self.assertEqual(self.initial, api.current_source())

    def test_nonregular_physical_source_leaf_fences_before_dispatch(self):
        path = self.source_root / 'runtime/nonzero_cloudops/adapters/portable.py'
        original = path.read_bytes()
        path.unlink()
        path.mkdir()
        try:
            self._assert_source_denied_before_dispatch((AdmissionError, ValueError, OSError))
        finally:
            path.rmdir()
            path.write_bytes(original)
        self.assertEqual(self.initial, api.current_source())


class FoundationSourceSealReviewTests(unittest.TestCase):
    """Both new source leaves gate actual owner/capacity on fresh owned data."""
    paths = ('runtime/meta_hackathon/native_authority.py', 'runtime/mission/execution_capacity.py')

    def source_host(self):
        from tempfile import mkdtemp

        import nz13_native_foundation_support as fx

        from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
        root = Path(mkdtemp(prefix='owned-review-source-')); fx.OWNED_ROOTS.append(str(root))
        source_root = root / 'source'
        for relative in api.SOURCE_FILES:
            path = source_root / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC_SEALED_SOURCE_ONLY\n')
        self.enterContext(patch.object(api, 'ROOT', source_root))
        self.enterContext(patch.object(api.subprocess, 'run', return_value=SimpleNamespace(stdout='a' * 40)))
        data_root = root / 'data'; data_root.mkdir(mode=0o700)
        data = fx.config_data(data_root)
        source = api.current_source()
        data['host_source'] = {'source_sha': source[0], 'capsule_digest': source[1]}
        authentication = {'uid': os.getuid(), 'method': 'SYNTHETIC_TEST_ONLY'}
        with patch.object(api, '_desktop_operator_uid', return_value=(os.getuid(), authentication)):
            host = api.NativeMobileComposition(root / 'native', origin='https://fixture.example.org',
                source_probe=api.current_source, host_composition=NativeHostCompositionConfig.from_dict(data))
        self.addCleanup(host.close); fx.fixture_tls(host); fx.initialize(host)
        return host, source_root

    def assert_mutation_denied(self, mode):
        import nz13_native_foundation_support as fx

        from runtime.memory_patch.errors import MemoryPatchError
        for relative in self.paths:
            with self.subTest(path=relative, mode=mode):
                host, source_root = self.source_host()
                path = source_root / relative
                if mode == 'drift': path.write_bytes(b'CHANGED_NEW_SOURCE_ONLY\n')
                elif mode == 'missing': path.unlink()
                else:
                    target = path.parent / 'owned-unsealed-copy'
                    target.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(target)
                with patch.object(host.foundation.governor, 'execution_capacity_review') as review:
                    with self.assertRaises((AdmissionError, ValueError, OSError, MemoryPatchError)): fx.review(host)
                    review.assert_not_called()
                with self.assertRaises((AdmissionError, ValueError, OSError)): host.operator_principal()

    def test_new_foundation_and_codec_drift_deny_before_capacity_or_owner(self):
        self.assert_mutation_denied('drift')

    def test_new_foundation_and_codec_missing_deny_before_capacity_or_owner(self):
        self.assert_mutation_denied('missing')

    def test_new_foundation_and_codec_symlink_deny_before_capacity_or_owner(self):
        self.assert_mutation_denied('symlink')

    def test_both_new_source_paths_have_unchanged_positive_capacity_control(self):
        import nz13_native_foundation_support as fx
        for relative in self.paths:
            with self.subTest(path=relative):
                host, _ = self.source_host()
                self.assertEqual(1, api.SOURCE_FILES.count(relative))
                with patch.object(host.foundation.governor, 'execution_capacity_review',
                                  wraps=host.foundation.governor.execution_capacity_review) as review:
                    self.assertEqual('REVIEWED', fx.review(host)['status'])
                    self.assertEqual(1, review.call_count)
