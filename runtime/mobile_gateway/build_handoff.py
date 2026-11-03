"""Read-only deterministic Android input manifest; never launches a toolchain."""
import argparse
import hashlib
import json
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = '81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f'
DISTRIBUTION = '20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78'
NAME = 'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json'


def manifest():
    directory=ROOT/'clients/android'
    files=[]
    for path in sorted(directory.rglob('*'),key=lambda value:value.relative_to(ROOT).as_posix()):
        relative=path.relative_to(ROOT).as_posix()
        if relative==NAME or any(p in ('build','.gradle','.kotlin','__pycache__') for p in path.parts):continue
        if path.is_symlink():raise ValueError('BUILD_INPUT_SYMLINK_DENIED')
        if path.is_dir():continue
        if not stat.S_ISREG(path.stat().st_mode):raise ValueError('BUILD_INPUT_TYPE_DENIED')
        if path.suffix in ('.apk','.aab','.jks','.keystore') or path.name=='local.properties':
            raise ValueError('PRIVATE_OR_BUILD_ARTIFACT_DENIED')
        files.append({'path':relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'bytes':path.stat().st_size,'executable':bool(path.stat().st_mode & 0o111)})
    wrapper=next(f for f in files if f['path'].endswith('/gradle-wrapper.jar'))
    if wrapper['sha256'] != WRAPPER:raise ValueError('WRAPPER_SHA_DENIED')
    props=(directory/'gradle/wrapper/gradle-wrapper.properties').read_text()
    if 'distributionSha256Sum='+DISTRIBUTION not in props:raise ValueError('DISTRIBUTION_SHA_DENIED')
    from scripts.android.cosmic4_channel import CHANNEL, manifest_identity
    return {'schema':'aioa.android.build-inputs.v1','status':'APK_BUILD_BLOCKED_TOOLCHAIN',
        'apk_built':False,'phone_installed':False,'package':'eu.sparkhat.aioa.companion',
        'version_code':4,'version_name':'0.3.1-cosmic','source_baseline':'4960ba2c56c55abfbf234909e7b8127beda06057',
        # Public certificate fingerprint of the physically installed Cosmic0.3.0.
        # A fresh ephemeral CI signer is not an acceptable update of that app.
        'update_signing_certificate_sha256':'75a539bc1cc1cf9ca9cde7fddf32f8dc82ceaee3fd2c8831d9e32a7a14ab6404',
        'channels':{CHANNEL:manifest_identity()},
        'required_toolchain':{'jdk':17,'gradle':'8.13','android_gradle_plugin':'8.11.1',
            'kotlin':'2.2.21','compile_sdk':36,'build_tools':'35.0.0','min_sdk':26,'target_sdk':36},
        'gradle_wrapper_sha256':WRAPPER,'gradle_distribution_sha256':DISTRIBUTION,
        'verification_reference':'https://gradle.org/release-checksums/',
        'command_cwd':'clients/android',
        'build_command':['./gradlew','--offline','--no-daemon','--max-workers=1',
                         'testDebugUnitTest','lintDebug','assembleDebug'],
        'preconditions':['independently verify complete local JDK17/SDK36/build-tools35.0.0',
            'verify Gradle8.13 cache before wrapper invocation; wrapper may otherwise download',
            'verify dependency cache, signing continuity and free RAM/disk',
            'owner decision required for any phone installation; no automatic ADB'],
        'not_run':['Gradle testDebugUnitTest','Android lint','assembleDebug','apksigner','physical device'],
        'files':files}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true');args=parser.parse_args()
    value=manifest()
    if args.check:
        ok=json.loads((ROOT/NAME).read_text())==value
        print('BUILD_INPUTS_MATCH' if ok else 'BUILD_INPUTS_DRIFT')
        return 0 if ok else 1
    print(json.dumps(value,sort_keys=True,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
