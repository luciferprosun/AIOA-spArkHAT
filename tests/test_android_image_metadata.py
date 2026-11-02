"""Real-run discrepancy reproduction: bootstrap guard, no runner or network."""
import json
import errno
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

ROOT=Path(__file__).resolve().parents[1]


class ImageMetadataConsistencyTests(unittest.TestCase):
    def bootstrap(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        run=workflow['jobs']['debug-apk']['steps'][0]['run']
        self.assertIn("python3 -B - <<'PY'",run,'env-only image guard missed real startup metadata discrepancy')
        script=run.split("python3 -B - <<'PY'\n",1)[1].rsplit('\nPY',1)[0]
        namespace={'__name__':'offline_guard_test'};exec(compile(script,'reviewed-image-bootstrap','exec'),namespace)
        return namespace,script

    def raw(self,version='20261026.354.1'):
        return json.dumps([{'group':'Operating System','detail':'Ubuntu 24.04'},
            {'group':'Runner Image','detail':'Image: ubuntu-24.04\nVersion: '+version+'\nIncluded Software: https://github.com/actions/runner-images'}]).encode()

    def test_env_claim_cannot_override_conflicting_native_image_metadata(self):
        ns,_=self.bootstrap()
        with self.assertRaises(SystemExit):ns['check_image'](self.raw('20261025.353.1'),{'ImageVersion':'20261026.354.1'})

    def test_matching_independent_metadata_is_accepted_and_hashed(self):
        ns,_=self.bootstrap();result=ns['check_image'](self.raw(),{'ImageVersion':'20261026.354.1'})
        self.assertEqual('20261026.354.1',result['metadata_version']);self.assertEqual(64,len(result['metadata_sha256']))

    def test_duplicate_or_wrong_image_metadata_and_wrong_env_are_denied(self):
        ns,_=self.bootstrap()
        duplicate=json.loads(self.raw());duplicate.append(duplicate[-1])
        for raw,env in [(json.dumps(duplicate).encode(),{'ImageVersion':'20261026.354.1'}),
            (self.raw().replace(b'ubuntu-24.04',b'ubuntu-22.04'),{'ImageVersion':'20261026.354.1'}),
            (self.raw(),{'ImageVersion':'20261025.353.1'})]:
            with self.subTest(raw=raw),self.assertRaises(SystemExit):ns['check_image'](raw,env)

    def test_metadata_reader_rejects_symlink(self):
        ns,_=self.bootstrap()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'data.json';target.write_bytes(self.raw())
            link=root/'link.json';link.symlink_to(target);ns['IMAGE_PATH']=str(link)
            # Qualify only the fixture parent. The real kernel open must then
            # reject the actual symlink, rather than failing an earlier UID check.
            with patch.object(ns['os'],'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)):
                with self.assertRaises(OSError) as caught:ns['read_image']()
            self.assertEqual(errno.ELOOP,caught.exception.errno)

    def test_all_three_jobs_keep_strict_check_before_any_checkout(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        static=yaml.safe_load((ROOT/'.github/workflows/codeql-static.yml').read_text())
        for job in (workflow['jobs']['debug-apk'],workflow['jobs']['codeql-kotlin'],static['jobs']['analyze']):
            steps=job['steps'];run=steps[0]['run']
            self.assertNotIn('uses',steps[0])
            self.assertTrue(steps[1]['uses'].startswith('actions/checkout@'))
            script=run.split("python3 -B - <<'PY'\n",1)[1].rsplit('\nPY',1)[0]
            namespace={'__name__':'offline_guard_test'}
            exec(compile(script,'reviewed-image-bootstrap','exec'),namespace)
            env={'ImageVersion':'20261026.354.1','AIOA_BUILD_PROFILE':'STRICT','AIOA_DEBUG_ENVIRONMENT_ACK':'true'}
            self.assertEqual('20261026.354.1',namespace['check_image'](self.raw(),env)['metadata_version'])
            with self.assertRaises(SystemExit):
                namespace['check_image'](self.raw('20261025.353.1'),env)


if __name__=='__main__':unittest.main()
