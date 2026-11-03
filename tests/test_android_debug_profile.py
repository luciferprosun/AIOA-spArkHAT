"""Offline policy cases; reconstructed metadata is never a live runner receipt."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from scripts.android import ci_build as ci
import test_android_image_metadata as metadata_tests
from test_android_postmerge_ci import context, SHA, IMAGE


ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'DEBUG_TOOLCHAIN_V1'
# Reconstructed from the vendor's configure-image-data.sh format. Its hash
# matches the actual pre-checkout snapshot in run41331318973; these bytes are a
# unit-test fixture, not bytes retained from that VM.
RAW = b'''[
  {
    "group": "Operating System",
    "detail": "Ubuntu\\n24.04.5\\nLTS"
  },
  {
    "group": "Runner Image",
    "detail": "Image: ubuntu-24.04\\nVersion: 20261025.353.1\\nIncluded Software: https://github.com/actions/runner-images/blob/ubuntu24/20261025.353/images/ubuntu/Ubuntu2404-Readme.md\\nImage Release: https://github.com/actions/runner-images/releases/tag/ubuntu24%2F20261025.353"
  }
]
'''
SNAPSHOT = {
    'build_profile': PROFILE,
    'metadata_version': '20261025.353.1',
    'declared_version': '20261026.354.1',
    'metadata_sha256': '6d35057ab003af4dc74998526957d7bde2e5526e1da06b4ed93201f6fa82e8ba',
    'image_identity_status': 'MISMATCH_ACCEPTED_DEBUG',
}


def debug_context():
    return {**context(), 'AIOA_BUILD_PROFILE': PROFILE,
        'AIOA_DEBUG_ENVIRONMENT_ACK': 'true', 'AIOA_CODEQL_REQUESTED': 'false',
        'AIOA_IMAGE_SNAPSHOT': json.dumps(SNAPSHOT)}


class AndroidDebugProfileTests(unittest.TestCase):
    def guard(self):
        return metadata_tests.ImageMetadataConsistencyTests().bootstrap()[0]['check_image']

    def test_debug_accepts_only_explicit_observed_exception_and_reports_the_mismatch(self):
        self.assertEqual('6d35057ab003af4dc74998526957d7bde2e5526e1da06b4ed93201f6fa82e8ba',
            hashlib.sha256(RAW).hexdigest())
        try:
            result = self.guard()(RAW, debug_context())
        except SystemExit as error:
            self.fail('Explicit DEBUG exception is unavailable: ' + str(error))
        self.assertEqual(SNAPSHOT, result)

    def test_strict_still_rejects_known_mismatch_even_with_debug_ack(self):
        for profile in ('STRICT', None):
            env = debug_context()
            if profile is None: env.pop('AIOA_BUILD_PROFILE')
            else: env['AIOA_BUILD_PROFILE'] = profile
            with self.subTest(profile=profile), self.assertRaises(SystemExit):
                self.guard()(RAW, env)

    def test_debug_denies_missing_ack_unknown_image_and_modified_metadata(self):
        cases = [(RAW, {**debug_context(), 'AIOA_DEBUG_ENVIRONMENT_ACK': 'false'}),
            (RAW, {**debug_context(), 'AIOA_BUILD_PROFILE': 'unreviewed'}),
            (RAW.replace(b'20261025.353.1', b'20261018.339.1'), debug_context()),
            (RAW + b' ', debug_context()),
            (RAW, {**debug_context(), 'ImageVersion': '20261025.353.1'})]
        for index, (raw, env) in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(SystemExit):
                self.guard()(raw, env)

    def test_context_requires_new_debug_consent_and_known_profile(self):
        for field, value in [('AIOA_DEBUG_ENVIRONMENT_ACK', 'false'),
            ('AIOA_DEBUG_ENVIRONMENT_ACK', ''), ('AIOA_BUILD_PROFILE', 'unreviewed')]:
            with self.subTest(field=field, value=value), self.assertRaises(ci.lib.Blocked):
                ci.context_check({**debug_context(), field: value}, SHA, IMAGE)

    def test_context_rejects_missing_forged_or_unrecognized_snapshot(self):
        changed = []
        for field, value in [('metadata_version', '20261018.339.1'),
            ('declared_version', '20261025.353.1'), ('metadata_sha256', '0'*64),
            ('image_identity_status', 'MATCHED'), ('build_profile', 'STRICT')]:
            changed.append(json.dumps({**SNAPSHOT, field: value}))
        for payload in ['', '{}', '[]', '{bad', *changed]:
            with self.subTest(payload=payload), self.assertRaises(ci.lib.Blocked):
                ci.context_check({**debug_context(), 'AIOA_IMAGE_SNAPSHOT': payload}, SHA, IMAGE)

    def test_debug_cannot_enter_codeql_or_enable_scoped_upload_permission(self):
        env = {**debug_context(), 'AIOA_CODEQL_REQUESTED': 'true',
            'AIOA_CODEQL_ACK': 'true', 'AIOA_CODEQL_PROFILE': 'advanced-v1'}
        with self.assertRaises(ci.lib.Blocked):
            ci.context_check(env, SHA, IMAGE)
        with self.assertRaises(ci.lib.Blocked):
            ci.context_check({**env, 'GITHUB_JOB': 'codeql-kotlin'}, SHA, IMAGE, purpose='codeql')
        with self.assertRaises(SystemExit):
            self.guard()(RAW, env)

    def test_debug_preserves_exact_source_actor_and_workflow_binding(self):
        ci.context_check(debug_context(), SHA, IMAGE)
        for field, value in [('GITHUB_SHA', 'b'*40), ('GITHUB_ACTOR', 'other'),
            ('GITHUB_WORKFLOW_SHA', 'b'*40), ('AIOA_WORKFLOW_REVISION', '0'*64),
            ('GITHUB_RUN_ATTEMPT', '2'), ('RUNNER_ENVIRONMENT', 'self-hosted')]:
            with self.subTest(field=field), self.assertRaises(ci.lib.Blocked):
                ci.context_check({**debug_context(), field: value}, SHA, IMAGE)

    def test_profile_evidence_retains_actual_identity_without_claiming_equality(self):
        check = getattr(ci, 'profile_evidence', None)
        self.assertIsNotNone(check, 'DEBUG receipt must retain actual metadata and profile')
        evidence = check(debug_context())
        self.assertEqual(PROFILE, evidence['build_profile'])
        self.assertEqual(SNAPSHOT, evidence['runner_observation'])
        self.assertEqual({'build_profile': 'STRICT'}, check(context()))

    def test_debug_sdk_drift_is_refused_by_preflight_before_build(self):
        # External observations are fixed here; the production preflight still
        # decides whether the inventory is admitted. No toolchain/network runs.
        with patch.object(ci.lib, 'source_check', return_value={}), \
            patch.object(ci, 'workflow_check', return_value=None), \
            patch.object(ci, 'branch_head_check', return_value=None), \
            patch.object(ci, 'sdk_inventory', return_value={'inventory_sha256': '0'*64}):
            with self.assertRaises(ci.lib.Blocked):
                ci.preflight({**debug_context(), 'ANDROID_SDK_ROOT': '/usr/local/lib/android/sdk'}, SHA, IMAGE)

    def test_sdk_cannot_change_after_preflight_and_become_the_build_baseline(self):
        pinned = {'inventory_sha256': '9f81aed02ae39189e55282cd66a561969590f2c032a868beaa1afc7e3b51e793'}
        changed = {'inventory_sha256': '0'*64}
        checkout = Path('/home/runner/work/AIOA-spArkHAT/AIOA-spArkHAT')
        env = {**debug_context(), 'ANDROID_SDK_ROOT': '/usr/local/lib/android/sdk',
            'GITHUB_WORKSPACE': str(checkout)}
        with patch.object(ci.lib, 'REPO', checkout), \
            patch.object(ci.lib, 'source_check', return_value={}), \
            patch.object(ci, 'workflow_check', return_value=None), \
            patch.object(ci, 'branch_head_check', return_value=None), \
            patch.object(ci, 'sdk_inventory', side_effect=[pinned, changed, changed]), \
            patch.object(ci.installer, 'catalog', side_effect=AssertionError('advanced past SDK gate')):
            ci.preflight(env, SHA, IMAGE)
            try:
                ci.prepare(env, SHA, IMAGE)
            except Exception as error:
                self.assertIsInstance(error, ci.lib.Blocked)
                self.assertEqual('BLOCKED_CI_DEBUG_SDK_INVENTORY', error.code)
            else:
                self.fail('SDK changed after preflight; prepare must refuse before tool acquisition')

    def test_matching_image_is_allowed_in_debug_and_still_discloses_profile(self):
        fixture = metadata_tests.ImageMetadataConsistencyTests().raw()
        try:
            result = self.guard()(fixture, debug_context())
        except SystemExit as error:
            self.fail(str(error))
        self.assertEqual(PROFILE, result.get('build_profile'))
        self.assertEqual('MATCHED', result.get('image_identity_status'))

    def test_manual_profile_defaults_strict_and_debug_has_separate_false_ack(self):
        workflow = yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertIn('build_profile', inputs)
        self.assertEqual('STRICT', inputs['build_profile']['default'])
        self.assertEqual(['STRICT', PROFILE, 'DEBUG_UBUNTU22_V1'], inputs['build_profile']['options'])
        self.assertIn('debug_environment_ack', inputs)
        self.assertFalse(inputs['debug_environment_ack']['default'])
        self.assertFalse(inputs['enable_codeql']['default'])
        self.assertEqual({'contents': 'read'}, workflow['jobs']['debug-apk']['permissions'])


if __name__ == '__main__': unittest.main()
