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


RECEIVER_PERMISSION='eu.sparkhat.aioa.companion.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'


def parse_badging(text):
    p=re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'",text,re.M)
    minimum=re.search(r"^sdkVersion:'([0-9]+)'",text,re.M)
    target=re.search(r"^targetSdkVersion:'([0-9]+)'",text,re.M)
    permissions=set(re.findall(r"^uses-permission(?:-sdk-[0-9]+)?: name='([^']+)'",text,re.M))
    lib.require(p is not None and minimum is not None and target is not None,'BLOCKED_APK_METADATA')
    lib.require(p.groups()==('eu.sparkhat.aioa.companion','3','0.3.0-cosmic'),'BLOCKED_APK_IDENTITY')
    lib.require(minimum.group(1)=='26' and target.group(1)=='36','BLOCKED_APK_SDK')
    lib.require(permissions in ({'android.permission.INTERNET'},
        {'android.permission.INTERNET',RECEIVER_PERMISSION}),'BLOCKED_APK_PERMISSIONS')
    return {'package':p.group(1),'version_code':3,'version_name':p.group(3),'min_sdk':26,'target_sdk':36,
        'permissions':sorted(permissions),'debuggable':'application-debuggable' in text}


def parse_receiver_permission(text,permissions):
    """Check the actual compiled manifest, not just the uses-permission name.

    AndroidX adds this app-private signature permission for non-exported
    receivers before API33. Never remove its protection or allow a foreign
    name, normal/dangerous level, extra flag or duplicate declaration.
    """
    code='BLOCKED_APK_RECEIVER_PERMISSION'
    lines=text.splitlines()
    roots=[re.fullmatch(r'( *)E: manifest \(line=[0-9]+\)',line) for line in lines]
    roots=[match for match in roots if match]
    lib.require(len(roots)==1,code)
    expected_indent=len(roots[0][1])+2
    definitions=[]
    for i,line in enumerate(lines):
        element=re.fullmatch(r'( *)E: (permission(?:-tree|-group)?) \(line=[0-9]+\)',line)
        if element is None:continue
        lib.require(element[2]=='permission' and len(element[1])==expected_indent,code)
        attributes=[]
        for child in lines[i+1:]:
            if len(child)-len(child.lstrip())<=expected_indent:break
            lib.require(child.startswith(' '*(expected_indent+2)+'A: '),code)
            attributes.append(child.strip())
        names=[re.fullmatch(r'A: android:name\(0x01010003\)="([^"]+)" \(Raw: "\1"\)',value)
            for value in attributes]
        names=[match[1] for match in names if match]
        levels=[value for value in attributes if re.fullmatch(
            r'A: android:protectionLevel\(0x01010009\)=\(type 0x1[01]\)0x2',value)]
        lib.require(len(attributes)==2 and names==[RECEIVER_PERMISSION] and len(levels)==1,code)
        definitions.append(names[0])
    expected=[RECEIVER_PERMISSION] if RECEIVER_PERMISSION in permissions else []
    lib.require(definitions==expected,code)
    return {name:'signature' for name in definitions}


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
    metadata['signature_permissions']=parse_receiver_permission(
        call('aapt',['dump','xmltree',str(apk),'AndroidManifest.xml']),metadata['permissions'])
    signature=parse_signature(call('apksigner',['verify','--verbose','--print-certs',str(apk)]))
    junit=list((build_root/'builds/_app/test-results/testDebugUnitTest').glob('TEST-*.xml'))
    lint=build_root/'builds/_app/reports/lint-results-debug.xml'
    reports=test_evidence(junit,lint)
    report_digests=[{'path':p.relative_to(build_root).as_posix(),'sha256':lib.sha(p)} for p in sorted([*junit,lint])]
    return {'schema':'aioa.android.apk-evidence.v1','status':'DEBUG_APK_VALID_SOURCE_UNBOUND',
        'source_sha':None,'inspected_checkout_sha':source_sha,'source_binding':'UNKNOWN',
        'report_digests':report_digests,'apk_sha256':lib.sha(apk),'bytes':apk.stat().st_size,
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
