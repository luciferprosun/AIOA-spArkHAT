"""Offline regressions for actual Cosmic build blockers, no toolchain execution."""
import json
from pathlib import Path
import unittest

from scripts.android import ci_build as ci, verify_apk
import test_android_image_metadata as metadata_tests
from test_android_postmerge_ci import context, SHA


PROFILE = 'DEBUG_UBUNTU22_V1'
IMAGE = '20261026.341.1'


class CosmicDeliveryTests(unittest.TestCase):
    def raw(self):
        return json.dumps([{'group': 'Runner Image', 'detail':
            'Image: ubuntu-22.04\nVersion: ' + IMAGE}]).encode()

    def environment(self):
        return {**context(), 'AIOA_BUILD_PROFILE': PROFILE,
            'AIOA_DEBUG_ENVIRONMENT_ACK': 'true', 'AIOA_CODEQL_REQUESTED': 'false',
            'ImageOS': 'ubuntu22', 'ImageVersion': IMAGE}

    def guard(self):
        return metadata_tests.ImageMetadataConsistencyTests().bootstrap()[0]['check_image']

    def test_exact_published_alternate_image_passes_both_guards(self):
        env = self.environment()
        snapshot = self.guard()(self.raw(), env)
        self.assertEqual('MATCHED', snapshot['image_identity_status'])
        self.assertEqual(IMAGE, snapshot['metadata_version'])
        env['AIOA_IMAGE_SNAPSHOT'] = json.dumps(snapshot)
        ci.context_check(env, SHA, IMAGE)
        for field, value in [('ImageOS', 'ubuntu24'), ('GITHUB_SHA', 'b'*40),
                ('AIOA_WORKFLOW_REVISION', '0'*64), ('GITHUB_ACTOR', 'other'),
                ('AIOA_CODEQL_REQUESTED', 'true'), ('GITHUB_RUN_ATTEMPT', '2')]:
            with self.subTest(field=field), self.assertRaises(ci.lib.Blocked):
                ci.context_check({**env, field: value}, SHA, IMAGE)

    def test_alternate_rejects_unknown_image_mismatch_no_consent_and_codeql(self):
        for raw, delta in [(self.raw().replace(IMAGE.encode(), b'20261018.96.1'), {}),
                (self.raw(), {'ImageVersion': '20261018.96.1'}),
                (self.raw(), {'AIOA_DEBUG_ENVIRONMENT_ACK': 'false'}),
                (self.raw(), {'AIOA_CODEQL_REQUESTED': 'true'}),
                (self.raw().replace(b'ubuntu-22.04', b'ubuntu-24.04'), {})]:
            with self.subTest(delta=delta, raw=raw), self.assertRaises(SystemExit):
                self.guard()(raw, {**self.environment(), **delta})

    def test_strict_does_not_accept_alternate_image(self):
        with self.assertRaises(SystemExit):
            self.guard()(self.raw(), {**self.environment(), 'AIOA_BUILD_PROFILE': 'STRICT'})

    def test_cosmic_apk_identity_matches_current_build_manifest_and_rejects_n1(self):
        manifest = json.loads((Path(__file__).resolve().parents[1] /
            'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json').read_text())
        raw = ("package: name='eu.sparkhat.aioa.companion' versionCode='3' versionName='0.3.0-cosmic'\n"
            "sdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\n")
        value = verify_apk.parse_badging(raw)
        self.assertEqual(manifest['version_code'], value['version_code'])
        self.assertEqual(manifest['version_name'], value['version_name'])
        for bad in [raw.replace("versionCode='3'", "versionCode='2'"),
                raw.replace('0.3.0-cosmic', '0.2.0-n1')]:
            with self.subTest(bad=bad), self.assertRaises(verify_apk.lib.Blocked):
                verify_apk.parse_badging(bad)
