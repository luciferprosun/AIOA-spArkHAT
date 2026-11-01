"""Offline guarded toolchain tests. No actual drive, download or binary executed."""
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch
import zipfile


class ToolchainGuardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.android'),'guarded toolchain package missing')
        self.lib=importlib.import_module('scripts.android.toolchain_lib')

    def facts(self):
        return dict(target='/media/l/LSC_DATA3',device='/dev/sda1',uuid='1c748500-8e12-4e23-80be-115ce7f3937a',
            fstype='ext4',options=['rw','nosuid','nodev'],mount_id='12',path_safe=True,destination_writable=True,
            external_free=80*1024**3,root_free=20*1024**3,kernel_readable=True,io_errors=0,ext4_errors=0)

    def qualification(self):
        return dict(schema='aioa.storage.independent-qualification.v1',publisher='AIOA_WD_WATCH',status='PASS',
            observed_at=1000,expires_at=2000,target='/media/l/LSC_DATA3',device='/dev/sda1',
            uuid=self.facts()['uuid'],mount_id='12',smart='PASS',usb='PASS',prior_faults='RESOLVED',
            report_pin_verified=True)

    def test_missing_independent_report_never_grants_write_permission(self):
        result=self.lib.storage_decision(self.facts(),None,now=1100)
        self.assertEqual('BLOCKED_STORAGE_TOOLCHAIN',result['status']);self.assertFalse(result['may_stage'])

    def test_qualified_facts_require_probe_not_blanket_storage_certificate(self):
        result=self.lib.storage_decision(self.facts(),self.qualification(),now=1100)
        self.assertEqual('PRECHECK_PASS_PROBE_REQUIRED',result['status']);self.assertTrue(result['may_stage'])
        self.assertFalse(result['storage_certified'])

    def test_each_storage_uncertainty_blocks(self):
        variants=[{'uuid':'wrong'},{'device':'/dev/sdb1'},{'target':'/tmp'}, {'fstype':'vfat'},
            {'options':['rw','noexec']},{'options':['ro']},{'path_safe':False},{'destination_writable':False},
            {'external_free':30*1024**3},{'root_free':9*1024**3},{'kernel_readable':False},
            {'io_errors':1},{'ext4_errors':1}]
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertFalse(self.lib.storage_decision(dict(self.facts(),**changed),self.qualification(),now=1100)['may_stage'])

    def test_stale_forged_wrong_mount_and_unresolved_qualification_block(self):
        for changed in [{'expires_at':1001},{'observed_at':1200},{'report_pin_verified':False},
                        {'prior_faults':'UNKNOWN'},{'smart':'UNKNOWN'},{'usb':'FAILED'},
                        {'mount_id':'11'},{'uuid':'wrong'},{'publisher':'MODEL_OUTPUT'},{'status':'PASS_BY_FLAG'}]:
            with self.subTest(changed=changed):
                self.assertFalse(self.lib.storage_decision(self.facts(),dict(self.qualification(),**changed),now=1100)['may_stage'])

    def test_catalog_rejects_unpublished_sha256_and_unknown_origin(self):
        for value in [dict(url='https://dl.google.com/android/repository/sdk.zip',sha256=None,size=3),
                      dict(url='http://dl.google.com/sdk.zip',sha256='a'*64,size=3),
                      dict(url='https://evil.invalid/sdk.zip',sha256='a'*64,size=3),
                      dict(url='https://user:pass@dl.google.com/sdk.zip',sha256='a'*64,size=3)]:
            with self.subTest(value=value),self.assertRaises(self.lib.Blocked):self.lib.validate_artifact(value)

    def test_download_is_verified_resumable_and_cached_without_second_network_call(self):
        raw=b'verified-small-fixture'; artifact=dict(id='fixture',filename='fixture.zip',
            url='https://dl.google.com/android/repository/fixture.zip',sha256=hashlib.sha256(raw).hexdigest(),size=len(raw))
        class Response(io.BytesIO):
            status=206
            headers={'Content-Range':'bytes 8-21/22'}
            def geturl(self):return artifact['url']
        seen=[]
        def request(url,offset):seen.append(offset);return Response(raw[offset:])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'fixture.zip.part').write_bytes(raw[:8])
            result=self.lib.download(artifact,root,request=request)
            self.assertEqual(raw,result.read_bytes());self.assertEqual([8],seen)
            self.assertEqual(result,self.lib.download(artifact,root,request=lambda *a:self.fail('cached archive redownload')))

    def test_wrong_hash_bad_range_network_error_and_symlink_never_promote(self):
        raw=b'small-fixture';artifact=dict(id='fixture',filename='fixture.zip',url='https://dl.google.com/android/repository/fixture.zip',
            sha256='f'*64,size=len(raw))
        class Response(io.BytesIO):
            status=200;headers={}
            def geturl(self):return artifact['url']
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(self.lib.Blocked):self.lib.download(artifact,root,request=lambda *a:Response(raw))
            self.assertFalse((root/'fixture.zip').exists())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def fail(*a):raise OSError('fixture network failure')
            with self.assertRaises(self.lib.Blocked):self.lib.download(artifact,root,request=fail)
            self.assertFalse((root/'fixture.zip').exists())
            partial=root/'fixture.zip.part'
            if partial.exists():partial.unlink()
            partial.symlink_to(root/'outside')
            with self.assertRaises(self.lib.Blocked):self.lib.download(artifact,root,request=lambda *a:self.fail('followed symlink'))

    def test_archive_traversal_symlink_and_expansion_budget_fail_closed(self):
        for filename,mode in [('../escape',None),('/absolute',None),('root/link',0o120777)]:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);archive=root/'fixture.zip'
                with zipfile.ZipFile(archive,'w') as out:
                    item=zipfile.ZipInfo(filename)
                    if mode:item.external_attr=mode<<16
                    out.writestr(item,b'payload')
                with self.assertRaises(self.lib.Blocked):self.lib.extract(archive,root/'stage',max_bytes=1024)
                self.assertFalse((root/'escape').exists())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'fixture.zip'
            with zipfile.ZipFile(archive,'w') as out:out.writestr('root/large',b'x'*100)
            with self.assertRaises(self.lib.Blocked):self.lib.extract(archive,root/'stage',max_bytes=10)

    def test_atomic_promotion_never_overwrites_an_existing_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stage=root/'stage';stage.mkdir();(stage/'new').write_text('fixture')
            destination=root/'installed';destination.mkdir();(destination/'keep').write_text('owner')
            with self.assertRaises(self.lib.Blocked):self.lib.promote(stage,destination)
            self.assertEqual('owner',(destination/'keep').read_text());self.assertTrue(stage.exists())
            self.lib.promote(stage,root/'fresh');self.assertEqual('fixture',(root/'fresh/new').read_text())

    def test_tar_internal_file_aliases_are_materialized_within_expansion_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'fixture.tar.gz'
            with tarfile.open(archive,'w:gz') as out:
                item=tarfile.TarInfo('jdk/LICENSE');item.size=8;out.addfile(item,io.BytesIO(b'license!'))
                for name in ('A','B'):
                    link=tarfile.TarInfo('jdk/'+name);link.type=tarfile.SYMTYPE;link.linkname='LICENSE';out.addfile(link)
            with self.assertRaises(self.lib.Blocked):self.lib.extract(archive,root/'small',max_bytes=16)
            destination=self.lib.extract(archive,root/'good',max_bytes=24)
            self.assertEqual(b'license!',(destination/'A').read_bytes());self.assertFalse((destination/'A').is_symlink())

    def test_unknown_license_and_dirty_source_are_closed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertFalse(self.lib.license_observed(root))
            p=root/'licenses';p.mkdir();(p/'android-sdk-license').write_text('0'*40+'\n')
            self.assertFalse(self.lib.license_observed(root))
        with patch.object(self.lib,'git',side_effect=lambda *a:'a'*40 if a==('rev-parse','HEAD') else ' M owner-file'):
            with self.assertRaises(self.lib.Blocked):self.lib.source_check('a'*40)

    def test_duplicate_private_evidence_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'report.json';p.write_text('{"status":"FAIL","status":"PASS"}');p.chmod(0o600)
            with self.assertRaises(self.lib.Blocked):self.lib.private_json(p)

    def test_qualification_digest_is_bound_to_the_bytes_parsed_not_a_second_path_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=root/'qualification.json';pin=root/'pin.json'
            value=self.qualification();value.pop('report_pin_verified')
            raw=json.dumps(value).encode();report.write_bytes(raw);report.chmod(0o600)
            pin.write_text(json.dumps({'schema':'aioa.storage.report-pin.v1','publisher':'AIOA_WD_WATCH',
                'report_path':str(report),'report_sha256':hashlib.sha256(raw).hexdigest()}));pin.chmod(0o600)
            with patch.object(self.lib,'PIN',pin),patch.object(self.lib,'QUALIFICATION_ROOT',root),\
                 patch.object(self.lib,'sha',side_effect=AssertionError('second pathname read can race')):
                self.assertTrue(self.lib.load_qualification()['report_pin_verified'])


if __name__=='__main__':unittest.main()
