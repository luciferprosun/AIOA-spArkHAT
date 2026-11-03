"""Deterministic source handoff, never executes Gradle/SDK/JDK."""
import importlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BuildHandoffTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mobile_gateway.build_handoff'))
        self.module=importlib.import_module('runtime.mobile_gateway.build_handoff')

    def test_input_manifest_is_exact_and_labels_unbuilt_artifacts(self):
        manifest=self.module.manifest()
        stored=json.loads((self.module.ROOT/'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json').read_text())
        self.assertEqual(stored,manifest);self.assertEqual('APK_BUILD_BLOCKED_TOOLCHAIN',manifest['status'])
        self.assertEqual(17,manifest['required_toolchain']['jdk']);self.assertEqual(36,manifest['required_toolchain']['compile_sdk'])
        self.assertGreater(len(manifest['files']),15);self.assertFalse(manifest['apk_built'])

    def test_source_drift_is_detected_and_manifest_generation_has_no_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);shutil.copytree(self.module.ROOT/'clients/android',root/'clients/android')
            with patch.object(self.module,'ROOT',root):
                before=self.module.manifest();self.assertEqual(before,self.module.manifest())
                (root/'clients/android/app/src/main/AndroidManifest.xml').write_text('changed fixture')
                self.assertNotEqual(before,self.module.manifest())

    def test_manifest_order_uses_portable_posix_strings(self):
        # pathlib compares path segments differently between Python3.11/3.12.
        # The serialized source manifest must have one version-independent order.
        paths=[item['path'] for item in self.module.manifest()['files']]
        self.assertEqual(sorted(paths),paths)

    def test_unverified_wrapper_is_not_a_build_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);shutil.copytree(self.module.ROOT/'clients/android',root/'clients/android')
            (root/'clients/android/gradle/wrapper/gradle-wrapper.jar').write_bytes(b'unverified')
            with patch.object(self.module,'ROOT',root),self.assertRaises(ValueError):self.module.manifest()


if __name__=='__main__':unittest.main()
