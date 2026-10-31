"""Read-only DEBUG APK verification using an already verified toolchain."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

if __package__:
    from . import installer,toolchain_lib as lib
else:
    import installer
    import toolchain_lib as lib


def parse_badging(text):
    p=re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'",text,re.M)
    minimum=re.search(r"^sdkVersion:'([0-9]+)'",text,re.M)
    target=re.search(r"^targetSdkVersion:'([0-9]+)'",text,re.M)
    permissions=set(re.findall(r"^uses-permission(?:-sdk-[0-9]+)?: name='([^']+)'",text,re.M))
    lib.require(p is not None and minimum is not None and target is not None,'BLOCKED_APK_METADATA')
    lib.require(p.groups()==('eu.sparkhat.aioa.companion','2','0.2.0-n1')
        and minimum.group(1)=='26' and target.group(1)=='36'
        and permissions=={'android.permission.INTERNET'},'BLOCKED_APK_CONTRACT')
    return {'package':p.group(1),'version_code':2,'version_name':p.group(3),'min_sdk':26,'target_sdk':36,
        'permissions':sorted(permissions),'debuggable':'application-debuggable' in text}


def parse_signature(text):
    hashes=re.findall(r'^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-f]{64})$',text,re.M)
    lib.require(len(hashes)==1 and re.search(r'Verified using v[23](?:\.1)? scheme .*: true',text)
        and re.search(r'^Signer #1 certificate DN: CN=Android Debug(?:,|$)',text,re.M),'BLOCKED_DEBUG_SIGNATURE')
    return {'kind':'DEBUG','certificate_sha256':hashes[0],'phone_tested':False,'release_signed':False,
            'old_apk_update_signature_compatibility':'UNKNOWN'}


def test_evidence(junit_files,lint_file):
    lib.require(bool(junit_files),'BLOCKED_JUNIT_MISSING')
    count=0;seen=set()
    for path in junit_files:
        path=lib.safe_path(path);lib.require(path.stat().st_size<=4*1024*1024,'BLOCKED_REPORT_SIZE')
        root=ET.fromstring(path.read_bytes());suites=list(root.iter('testsuite'))
        lib.require(bool(suites),'BLOCKED_JUNIT_MISSING')
        for suite in suites:
            tests=int(suite.attrib.get('tests','0'))
            lib.require(tests>0 and all(int(suite.attrib.get(k,'0'))==0 for k in ('failures','errors','skipped')),'BLOCKED_JUNIT_RESULT')
            cases=suite.findall('testcase')
            lib.require(len(cases)==tests,'BLOCKED_JUNIT_COUNT')
            for case in cases:
                identity=(case.attrib.get('classname',''),case.attrib.get('name'))
                lib.require(bool(identity[1]) and identity not in seen and not any(case.find(k) is not None
                    for k in ('failure','error','skipped')),'BLOCKED_JUNIT_CASE')
                seen.add(identity)
            count+=tests
    lint=lib.safe_path(lint_file);lib.require(lint.is_file() and lint.stat().st_size<=4*1024*1024,'BLOCKED_LINT_MISSING')
    issues=ET.fromstring(lint.read_bytes())
    lib.require(issues.tag=='issues' and not any(x.attrib.get('severity') in ('Error','Fatal') for x in issues.iter('issue')),'BLOCKED_LINT_RESULT')
    return {'junit_pass':count,'junit_fail':0,'junit_skip':0,'lint_errors':0}


def verify(apk,build_root,*,sdk,jdk,source_sha,environment):
    apk=lib.safe_path(apk);build_root=lib.safe_path(build_root)
    lib.require(apk.is_relative_to(build_root) and apk.is_file() and apk.stat().st_size<=128*1024*1024,'BLOCKED_APK_PATH')
    tools=lib.safe_path(sdk/'build-tools/35.0.0')
    def call(binary,args):
        result=subprocess.run([str(tools/binary),*args],env=environment,stdin=subprocess.DEVNULL,
                              capture_output=True,text=True,timeout=45)
        lib.require(result.returncode==0 and len(result.stdout)+len(result.stderr)<=1024*1024,'BLOCKED_APK_TOOL')
        return result.stdout
    metadata=parse_badging(call('aapt',['dump','badging',str(apk)]))
    lib.require(metadata['debuggable'],'BLOCKED_NOT_DEBUG_APK')
    signature=parse_signature(call('apksigner',['verify','--verbose','--print-certs',str(apk)]))
    reports=test_evidence(list((build_root/'builds/_app/test-results/testDebugUnitTest').glob('TEST-*.xml')),
        build_root/'builds/_app/reports/lint-results-debug.xml')
    return {'schema':'aioa.android.apk-evidence.v1','status':'DEBUG_APK_VERIFIED_HOST_ONLY',
        'source_sha':source_sha,'apk_sha256':lib.sha(apk),'bytes':apk.stat().st_size,
        **metadata,**signature,**reports,'android_e2e_verified':False,'meta_live_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk',required=True,type=Path);parser.add_argument('--build-root',required=True,type=Path)
    parser.add_argument('--source-sha',required=True);args=parser.parse_args()
    try:
        lib.assert_admitted();lib.source_check(args.source_sha);installer.verify_versions()
        lib.require(args.build_root.absolute().is_relative_to(lib.ROOT/'build-output'/args.source_sha),'BLOCKED_BUILD_PATH')
        value=verify(args.apk,args.build_root,sdk=lib.ROOT/'sdk',jdk=lib.ROOT/'jdk-17',
            source_sha=args.source_sha,environment=installer.scoped_environment())
    except lib.Blocked as e:value={'status':e.code}
    except (OSError,ValueError,KeyError,ET.ParseError,subprocess.SubprocessError):value={'status':'BLOCKED_VERIFICATION_UNKNOWN'}
    print(json.dumps(value,sort_keys=True,indent=2))
    return 0 if value['status']=='DEBUG_APK_VERIFIED_HOST_ONLY' else 2


if __name__=='__main__':raise SystemExit(main())
