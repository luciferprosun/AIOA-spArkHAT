"""CI toolchain-cache reproduction; no JDK download or Java process."""
from pathlib import Path
from contextlib import ExitStack
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.android import ci_build as ci

SOURCE=Path(__file__).resolve().parents[1]


class PrivatePinnedJdkTests(unittest.TestCase):
    def test_runner_cached_jdk_symlink_is_unused_and_pinned_archive_owns_java_home(self):
        catalog=ci.installer.catalog()
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);repo=base/'work/project';sdk=base/'image-sdk';temp=base/'run-temp'
            repo.mkdir(parents=True);sdk.mkdir();temp.mkdir()
            shutil.copytree(SOURCE/'clients/android/gradle/wrapper',repo/'clients/android/gradle/wrapper')
            vendor=base/'system-jdk';vendor.mkdir();(vendor/'marker').write_text('existing image JDK')
            cached=base/'toolcache/Java_Temurin-Hotspot_jdk/17.0.21-9/x64'
            cached.parent.mkdir(parents=True);cached.symlink_to(vendor)
            env={'GITHUB_WORKSPACE':str(repo),'ANDROID_SDK_ROOT':str(sdk),'JAVA_HOME':str(cached),
                'RUNNER_TEMP':str(temp),'GITHUB_RUN_ID':'777','GITHUB_RUN_ATTEMPT':'1'}
            # Map only fixed hosted-runner roots to a private fixture layout.
            def path(value):
                return {'/home/runner/work':base/'work','/usr/local/lib/android/sdk':sdk}.get(str(value),Path(value))
            acquired=[];calls=[]
            def acquire(artifact,root):
                acquired.append(artifact)
                target=root/artifact['destination'];target.mkdir(parents=True)
                return target
            def run(argv,**kwargs):
                calls.append(argv)
                text=('openjdk version 17.0.21 Temurin-17.0.21+9\n' if argv[0].endswith('/bin/java')
                    else '22.0\n' if argv[0].endswith('/bin/sdkmanager') else 'Gradle 8.13\n')
                log=kwargs['log'];log.write_text(text);log.chmod(0o600)
                return 0
            with ExitStack() as stack:
                for obj,name,value in [(ci,'Path',path),(ci.lib,'REPO',repo),
                    (ci.installer,'catalog',lambda:catalog),(ci,'acquire',acquire),
                    (ci.build_apk,'run_logged',run),(ci,'sdk_inventory',lambda _:{}),
                    (ci.lib,'source_check',lambda _:None),(ci.installer,'seed_wrapper_cache',lambda *_:None)]:
                    stack.enter_context(patch.object(obj,name,value))
                root,jdk,_,_,scoped,_,_=ci.prepare(env,'a'*40,ci.REVIEWED_IMAGE_VERSION)
            self.assertEqual(root/'jdk-17',jdk)
            self.assertEqual(str(jdk),scoped['JAVA_HOME'])
            self.assertEqual('jdk',acquired[0]['id'])
            self.assertEqual('8b9b611d917e3dfd8419d3566b5949226f69b052fed7e109c1368add1dfe8711',acquired[0]['sha256'])
            self.assertTrue(cached.is_symlink());self.assertEqual('existing image JDK',(vendor/'marker').read_text())
            self.assertTrue(calls[0][0].startswith(str(jdk)))
            self.assertNotIn(str(cached),repr(calls))


if __name__=='__main__':unittest.main()
