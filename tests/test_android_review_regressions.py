"""Review reproductions: temporary files/processes only, no real toolchain."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from scripts.android import build_apk,ci_build,installer,toolchain_lib as lib,verify_apk

REPO=Path(__file__).resolve().parents[1]


class AndroidReviewRegressions(unittest.TestCase):
    def archive(self,root,count=1):
        cache=root/'downloads';cache.mkdir();archive=cache/'fixture.zip'
        with zipfile.ZipFile(archive,'w') as stream:
            for n in range(count):stream.writestr('package/bin/file-'+str(n).zfill(4),b'fixture')
        return {'id':'fixture','version':'1','filename':archive.name,
            'url':'https://dl.google.com/android/repository/fixture.zip',
            'size':archive.stat().st_size,'sha256':lib.sha(archive),
            'destination':'installed','license':'fixture'}

    def test_package_scale_manifest_is_readable_after_promotion_and_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);artifact=self.archive(root,450)
            installed=ci_build.acquire(artifact,root)
            self.assertGreater((installed/installer.COMPONENT).stat().st_size,65536)
            self.assertEqual(installed,installer.component_check(artifact,root))
            self.assertEqual(450,len(installer.tree_manifest(installed)))
            pin=root/'large-authority-pin';pin.write_bytes(b' '*65537);pin.chmod(0o600)
            with self.assertRaises(lib.Blocked):lib.private_bytes(pin)

    def test_replaced_binary_and_rewritten_inventory_cannot_claim_archive_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);artifact=self.archive(root);installed=ci_build.acquire(artifact,root)
            (installed/'bin/file-0000').write_bytes(b'unverified replacement')
            marker=installed/installer.COMPONENT;value=json.loads(marker.read_text())
            value['files']=installer.tree_manifest(installed);marker.write_text(json.dumps(value))
            with self.assertRaises(lib.Blocked):installer.component_check(artifact,root)

    def test_missing_or_corrupt_archive_cannot_authenticate_an_installed_component(self):
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);artifact=self.archive(root);ci_build.acquire(artifact,root)
                archive=root/'downloads'/artifact['filename']
                if corrupt:archive.write_bytes(b'corrupt')
                else:archive.unlink()
                with self.assertRaises(lib.Blocked):installer.component_check(artifact,root)

    def test_readonly_archive_inventory_matches_materialized_tar_file_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'aliases.tar.gz'
            with tarfile.open(archive,'w:gz') as stream:
                item=tarfile.TarInfo('package/bin/tool');item.mode=0o755;item.size=7
                stream.addfile(item,io.BytesIO(b'fixture'))
                link=tarfile.TarInfo('package/bin/alias');link.type=tarfile.SYMTYPE;link.linkname='tool';stream.addfile(link)
            installed=lib.extract(archive,root/'stage')
            before=set(root.rglob('*'))
            self.assertEqual(installer.tree_manifest(installed),lib.archive_inventory(archive))
            self.assertEqual(before,set(root.rglob('*')))

    def source_fixture(self,root):
        shutil.copytree(REPO/'clients/android',root/'clients/android')
        for args in [('init','-q'),('add','clients/android'),('-c','user.name=Fixture','-c',
            'user.email=fixture@localhost','commit','-qm','offline fixture')]:
            subprocess.run(['git','-C',str(root),*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        return subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()

    def test_ignored_sdk_override_is_rejected_even_when_git_status_is_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);head=self.source_fixture(root)
            with patch.object(lib,'REPO',root):
                lib.source_check(head)
                (root/'clients/android/local.properties').write_text('sdk.dir=/tmp/unverified-sdk\n')
                self.assertEqual('',lib.git('status','--porcelain','-uall'))
                with self.assertRaises(lib.Blocked):lib.source_check(head)

    def test_gradle_user_configuration_is_rejected_before_any_tool_process(self):
        for relative in ('gradle.properties','init.gradle','init.gradle.kts','init.d/unreviewed.gradle'):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);cache=root/'gradle-cache';target=cache/relative
                target.parent.mkdir(parents=True);target.write_text('unreviewed config')
                with patch.object(lib,'ROOT',root),patch.object(lib,'source_check',return_value={}),\
                    patch.object(lib,'assert_admitted',return_value={}),\
                    patch.object(installer,'verify_versions',side_effect=AssertionError('process launched')):
                    with self.assertRaises(lib.Blocked):build_apk.execute_build('a'*40)

    def test_sigterm_supervisor_cleans_its_owned_child_and_restores_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pidfile=root/'child.pid'
            child='import os,time;from pathlib import Path;Path('+repr(str(pidfile))+').write_text(str(os.getpid()));time.sleep(30)'
            supervisor='from pathlib import Path;from scripts.android.build_apk import run_logged;run_logged('+repr([sys.executable,'-B','-c',child])+',cwd=Path('+repr(str(root))+'),environment={"PATH":"/usr/bin:/bin"},log=Path('+repr(str(root/'output.log'))+'),timeout=20)'
            process=subprocess.Popen([sys.executable,'-B','-c',supervisor],cwd=REPO,
                env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            childfd=None
            try:
                deadline=time.monotonic()+10
                while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(pidfile.is_file());childpid=int(pidfile.read_text());childfd=os.pidfd_open(childpid)
                process.terminate();process.wait(timeout=5)
                try:signal.pidfd_send_signal(childfd,0);alive=True
                except ProcessLookupError:alive=False
                self.assertFalse(alive,'child outlived terminated supervisor')
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=5)
                if childfd is not None:
                    try:signal.pidfd_send_signal(childfd,signal.SIGKILL)
                    except ProcessLookupError:pass
                    os.close(childfd)
            before=signal.getsignal(signal.SIGTERM)
            build_apk.run_logged([sys.executable,'-B','-c','pass'],cwd=root,environment={'PATH':'/usr/bin:/bin'},log=root/'normal.log')
            self.assertEqual(before,signal.getsignal(signal.SIGTERM))

    def test_artifact_reuse_under_new_sha_cannot_gain_new_source_provenance(self):
        badging="package: name='eu.sparkhat.aioa.companion' versionCode='2' versionName='0.2.0-n1'\nsdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\napplication-debuggable\n"
        signature='Verified using v2 scheme (APK Signature Scheme v2): true\nSigner #1 certificate DN: CN=Android Debug\nSigner #1 certificate SHA-256 digest: '+'a'*64+'\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';old.mkdir();(old/'app-debug.apk').write_bytes(b'old-artifact-fixture')
            new=root/('b'*40);new.mkdir();shutil.copyfile(old/'app-debug.apk',new/'app-debug.apk')
            reports=new/'builds/_app';(reports/'test-results/testDebugUnitTest').mkdir(parents=True);(reports/'reports').mkdir()
            (reports/'test-results/testDebugUnitTest/TEST-fixture.xml').write_text('<testsuite tests="1"><testcase name="fixture"/></testsuite>')
            (reports/'reports/lint-results-debug.xml').write_text('<issues/>')
            def tool(argv,**kwargs):return subprocess.CompletedProcess(argv,0,badging if Path(argv[0]).name=='aapt' else signature,'')
            with patch.object(verify_apk.subprocess,'run',side_effect=tool):
                result=verify_apk.verify(new/'app-debug.apk',new,sdk=root/'sdk',jdk=root/'jdk',source_sha='b'*40,environment={})
            self.assertIsNone(result['source_sha'])
            self.assertEqual('UNKNOWN',result['source_binding'])
            self.assertEqual('DEBUG_APK_VALID_SOURCE_UNBOUND',result['status'])

    def test_existing_launcher_receives_jvm_limits_through_a_java_native_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);java=root/'jdk/bin/java';java.parent.mkdir(parents=True)
            java.write_text('#!'+sys.executable+'\nimport json,os,sys\nprint(json.dumps({"options":os.environ.get("JDK_JAVA_OPTIONS"),"argv":sys.argv[1:]}))\n');java.chmod(0o755)
            env=ci_build.environment(root,root/'jdk',root/'sdk')
            self.assertIn('-Xmx128m',env.get('JDK_JAVA_OPTIONS',''))
            self.assertIn('-Djava.io.tmpdir='+str(root/'tmp'),env['JDK_JAVA_OPTIONS'])
            result=subprocess.run([str(REPO/'clients/android/gradlew'),'--version'],env=env,capture_output=True,text=True,check=True)
            observed=json.loads(result.stdout)
            self.assertEqual(env['JDK_JAVA_OPTIONS'],observed['options'])
            self.assertIn('org.gradle.wrapper.GradleWrapperMain',observed['argv'])

    def test_sdkmanager_version_check_accepts_only_expected_jvm_notice_and_exact_version(self):
        options='-Xmx128m -Duser.home=/owned/run/java-user'
        ci_build.check_sdkmanager_version('NOTE: Picked up JDK_JAVA_OPTIONS: '+options+'\n22.0\n',options)
        for text in ('23.0\n','error\n22.0\n','22.0\n22.0\n'):
            with self.subTest(text=text),self.assertRaises(lib.Blocked):ci_build.check_sdkmanager_version(text,options)


if __name__=='__main__':unittest.main()
