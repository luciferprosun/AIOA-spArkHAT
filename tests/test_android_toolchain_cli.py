"""CLI contracts run with synthetic admission and no actual disk/network."""
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class ToolchainCLITests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.android.installer'))
        self.module=importlib.import_module('scripts.android.installer')

    def test_blocked_install_and_dry_run_make_no_directory_or_network_effect(self):
        for dry in (True,False):
            with patch.object(self.module.lib,'admission',return_value={'status':'BLOCKED_STORAGE_TOOLCHAIN','may_stage':False,'reasons':['UNKNOWN']}),\
                 patch.object(self.module,'perform_install',side_effect=AssertionError('write reached')):
                result=self.module.install(dry_run=dry,expected_source='a'*40)
                self.assertEqual('BLOCKED_STORAGE_TOOLCHAIN',result['status']);self.assertEqual(0,result['downloads'])

    def test_dry_run_with_qualified_facts_still_has_no_probe_or_download(self):
        with patch.object(self.module.lib,'admission',return_value={'status':'PRECHECK_PASS_PROBE_REQUIRED','may_stage':True,'reasons':[]}),\
             patch.object(self.module.lib,'source_check',return_value={}),\
             patch.object(self.module,'perform_install',side_effect=AssertionError('dry-run effect')):
            result=self.module.install(dry_run=True,expected_source='a'*40)
            self.assertEqual('DRY_RUN_NO_EFFECTS',result['status'])

    def test_missing_license_or_checksum_is_not_toolchain_ready(self):
        plan=self.module.plan()
        self.assertIn('BLOCKED_LICENSE',plan['possible_blockers'])
        self.assertIn('BLOCKED_PUBLISHED_SHA256',plan['possible_blockers'])
        self.assertEqual('8.13',plan['versions']['gradle'])
        self.assertEqual('35.0.0',plan['versions']['build_tools'])

    def test_gradle_cache_uses_upstream_wrapper_url_hash_not_global_install(self):
        import hashlib
        cache=self.module.wrapper_relative_home()
        self.assertEqual('gradle-cache/wrapper/dists/gradle-8.13-bin',str(cache.parent.parent))
        self.assertEqual('gradle-8.13',cache.name)
        expected=int.from_bytes(hashlib.md5(b'https://services.gradle.org/distributions/gradle-8.13-bin.zip',usedforsecurity=False).digest(),'big')
        self.assertEqual(expected,int(cache.parent.name,36))
        self.assertEqual(str(cache),self.module.catalog()['artifacts'][1]['destination'])

    def test_owned_bounded_probe_cleans_only_its_own_bytes_and_reports_narrow_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'downloads').mkdir();(root/'reports').mkdir()
            (root/'owner-file').write_text('preserve')
            with patch.object(self.module.lib,'assert_admitted',return_value={}):
                result=self.module.bounded_probe(root)
            self.assertEqual(16384,result['bytes']);self.assertFalse(result['global_storage_certification'])
            self.assertEqual('preserve',(root/'owner-file').read_text());self.assertEqual([],list((root/'downloads').iterdir()))

    def test_probe_eio_stops_without_cleanup_of_diagnostics_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'downloads').mkdir();(root/'reports').mkdir()
            with patch.object(self.module.lib,'assert_admitted',return_value={}),patch.object(self.module.os,'fsync',side_effect=OSError(5,'fixture EIO')):
                with self.assertRaises(self.module.lib.Blocked):self.module.bounded_probe(root)
            self.assertEqual(1,len(list((root/'downloads').glob('.probe-*/probe.bin'))))

    def test_installed_manifest_cannot_turn_null_publication_hash_into_verified_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);dest=root/'installed';dest.mkdir();(dest/'binary').write_bytes(b'fixture')
            artifact={'id':'platform','version':'36-r02','sha256':None,'size':7,
                'url':'https://dl.google.com/android/repository/platform.zip','destination':'installed'}
            value={'id':'platform','version':'36-r02','archive_sha256':None,'files':self.module.tree_manifest(dest)}
            manifest=dest/self.module.COMPONENT;manifest.write_text(json.dumps(value));manifest.chmod(0o600)
            with self.assertRaises(self.module.lib.Blocked):self.module.component_check(artifact,root)

    def test_shell_wrappers_parse_and_environment_has_no_unsafe_side_effect(self):
        for name in ['install_toolchain.sh','build_apk.sh','env.sh']:
            path=ROOT/'scripts/android'/name
            self.assertTrue(path.is_file())
            result=subprocess.run(['bash','-n',str(path)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            text=path.read_text()
            for token in ['sudo ','apt-get','yes |','curl |','rm -rf','--licenses','GITHUB_TOKEN']:
                self.assertNotIn(token,text)
        text=(ROOT/'scripts/android/env.sh').read_text()
        self.assertNotIn('export HOME=',text)


if __name__=='__main__':unittest.main()
