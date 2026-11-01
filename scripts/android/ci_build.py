"""Manual GitHub-hosted profile; never an override for local disk admission.

Runner SDK integrity is observed against an owner-reviewed image, not promoted
to a claim about independently published SDK archive SHA256 values.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

if __package__:
    from . import build_apk,installer,toolchain_lib as lib,verify_apk
else:
    import build_apk
    import installer
    import toolchain_lib as lib
    import verify_apk


SOURCE_REF='refs/heads/main'
WORKFLOW_PATH='.github/workflows/android-manual-build.yml'
REVIEWED_IMAGE_VERSION='20261026.354.1'
REVIEWED_WORKFLOW_SHA256='3ce2f8be0d65d43a5af967656427e9f1a2f4221fa6f584ce1f2865511ea3774e'


def context_check(env,source_sha,image,*,purpose='apk'):
    expected={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
        'GITHUB_REPOSITORY':'luciferprosun/AIOA-spArkHAT',
        'GITHUB_REPOSITORY_OWNER':'luciferprosun','GITHUB_ACTOR':'luciferprosun',
        'GITHUB_TRIGGERING_ACTOR':'luciferprosun','GITHUB_REF':SOURCE_REF,
        'GITHUB_WORKFLOW_REF':'luciferprosun/AIOA-spArkHAT/'+WORKFLOW_PATH+'@'+SOURCE_REF,
        'GITHUB_JOB':'debug-apk','GITHUB_RUN_ATTEMPT':'1',
        'RUNNER_ENVIRONMENT':'github-hosted','RUNNER_ARCH':'X64','ImageOS':'ubuntu24',
        'RUNNER_TEMP':'/home/runner/work/_temp','AIOA_APPROVE_RUN':'true',
        'AIOA_SDK_LICENSE_ACK':'true','AIOA_ARTIFACT_ACK':'true'}
    lib.require(all(env.get(k)==v for k,v in expected.items()),'BLOCKED_CI_OWNER_OR_RUNNER_CONTEXT')
    lib.require(purpose=='apk','BLOCKED_CI_PURPOSE')
    lib.require(type(source_sha) is str and re.fullmatch(r'[0-9a-f]{40}',source_sha)
        and env.get('GITHUB_SHA')==env.get('GITHUB_WORKFLOW_SHA')==source_sha,'BLOCKED_CI_SOURCE')
    lib.require(image==env.get('ImageVersion')==REVIEWED_IMAGE_VERSION,'BLOCKED_CI_IMAGE_DRIFT')
    lib.require(env.get('AIOA_WORKFLOW_REVISION')==REVIEWED_WORKFLOW_SHA256,'BLOCKED_CI_WORKFLOW_REVISION')
    lib.require(all(re.fullmatch(r'[0-9]{1,20}',env.get(k,''))
        for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')),'BLOCKED_CI_RUN_ID')


def workflow_check(env):
    path=lib.safe_path(lib.REPO/WORKFLOW_PATH);info=path.lstat()
    lib.require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=65536,
        'BLOCKED_CI_WORKFLOW_FILE')
    lib.require(lib.sha(path)==env.get('AIOA_WORKFLOW_REVISION')==REVIEWED_WORKFLOW_SHA256,
        'BLOCKED_CI_WORKFLOW_REVISION')


def branch_head_check(source_sha):
    # Anonymous fixed Git READ. No ambient credential helper, config or token.
    environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','GIT_TERMINAL_PROMPT':'0',
        'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1'}
    response=subprocess.run(['git','-c','credential.helper=','ls-remote','--exit-code','--refs',
        'https://github.com/luciferprosun/AIOA-spArkHAT.git',SOURCE_REF],
        capture_output=True,text=True,timeout=20,env=environment,stdin=subprocess.DEVNULL)
    lib.require(response.returncode==0 and response.stdout.splitlines()==[source_sha+'\t'+SOURCE_REF],
        'BLOCKED_CI_BRANCH_DRIFT')


def sdk_inventory(sdk):
    sdk=lib.safe_path(sdk)
    lib.require(lib.license_observed(sdk),'BLOCKED_CI_EXISTING_LICENSE_REQUIRED')
    inventory=[]
    for relative,revision,files in [('platforms/android-36','2',['android.jar']),
        ('build-tools/35.0.0','35.0.0',['aapt','apksigner'])]:
        package=lib.safe_path(sdk/relative)
        props=(package/'source.properties').read_text()
        lib.require(re.search(r'^Pkg\.Revision\s*=\s*'+re.escape(revision)+r'\s*$',props,re.M),
            'BLOCKED_CI_SDK_VERSION_OR_MISSING')
        lib.require(all(lib.safe_path(package/name).is_file() for name in files),'BLOCKED_CI_SDK_INCOMPLETE')
        inventory.append({'path':relative,'files':installer.tree_manifest(package)})
    digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'trust':'GITHUB_RUNNER_IMAGE_NOT_PUBLISHER_ARCHIVE_SHA256','inventory_sha256':digest,
        'license_record_observed':True,'licenses_accepted_by_tool':False}


def acquire(artifact,root):
    # Same downloader/extractor/seals as local profile; no local-admission flag.
    lib.validate_artifact(artifact)
    destination=lib.safe_path(root/artifact['destination'])
    lib.require(not destination.exists(),'BLOCKED_CI_COMPONENT_EXISTS')
    (root/'downloads').mkdir(mode=0o700,exist_ok=True)
    archive=lib.download(artifact,root/'downloads')
    stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=root/'downloads'))
    unpacked=lib.extract(archive,stage/'unpacked')
    installer.private_write(unpacked/installer.COMPONENT,{'schema':'aioa.android.component.v1',
        'id':artifact['id'],'version':artifact['version'],'archive_sha256':artifact['sha256'],
        'files':installer.tree_manifest(unpacked)})
    installer.component_check(artifact,root,directory=unpacked)
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    lib.promote(unpacked,destination)
    return installer.component_check(artifact,root)


def environment(root,jdk,sdk):
    return {'PATH':str(jdk/'bin')+':/usr/bin:/bin','LANG':'C.UTF-8','JAVA_HOME':str(jdk),
        'ANDROID_HOME':str(sdk),'ANDROID_SDK_ROOT':str(sdk),'ANDROID_USER_HOME':str(root/'android-user'),
        'GRADLE_USER_HOME':str(root/'gradle-cache'),'TMPDIR':str(root/'tmp'),
        'JDK_JAVA_OPTIONS':'-Xmx128m -Duser.home='+str(root/'java-user')+' -Djava.io.tmpdir='+str(root/'tmp')}


def command(cache,init):
    result=[part for part in build_apk.command(cache,init) if part!='--offline']
    return result[:1]+['-Pandroid.builder.sdkDownload=false',
        '-Dorg.gradle.java.installations.auto-download=false']+result[1:]


def check_sdkmanager_version(text,options):
    notice='NOTE: Picked up JDK_JAVA_OPTIONS: '+options
    lines=[line.strip() for line in text.splitlines() if line.strip() and line.strip()!=notice]
    lib.require(lines==['22.0'],'BLOCKED_CI_SDKMANAGER_VERSION')


def execute(env,source_sha,image):
    lib.source_check(source_sha)
    lib.require(Path(env.get('GITHUB_WORKSPACE',''))==lib.REPO
        and lib.REPO.is_relative_to(Path('/home/runner/work')),'BLOCKED_CI_WORKSPACE')
    sdk=lib.safe_path(env.get('ANDROID_SDK_ROOT',''))
    jdk=lib.safe_path(env.get('JAVA_HOME',''))
    lib.require(sdk==Path('/usr/local/lib/android/sdk')
        and jdk.is_relative_to(Path('/opt/hostedtoolcache')),'BLOCKED_CI_VENDOR_PATH')
    before=sdk_inventory(sdk)
    wrapper=lib.REPO/'clients/android/gradle/wrapper'
    lock=installer.catalog()
    lib.require(lib.sha(wrapper/'gradle-wrapper.jar')==lock['wrapper_sha256']
        and lock['artifacts'][1]['sha256'] in (wrapper/'gradle-wrapper.properties').read_text(),
        'BLOCKED_CI_WRAPPER')
    root=lib.safe_path(Path(env['RUNNER_TEMP'])/('aioa-android-'+env['GITHUB_RUN_ID']+'-'+env['GITHUB_RUN_ATTEMPT']))
    root.mkdir(mode=0o700)  # Exclusive: never overwrite an earlier run.
    for name in ('tmp','android-user','java-user','downloads'):(root/name).mkdir(mode=0o700)
    scoped=environment(root,jdk,sdk)
    status=build_apk.run_logged([str(jdk/'bin/java'),'-version'],cwd=root,environment=scoped,
        log=root/'java-version.log',timeout=15)
    lib.require(status==0 and re.search(r'17\.0\.21\+9(?:\D|$)',(root/'java-version.log').read_text()),
        'BLOCKED_CI_JDK_VERSION')
    gradle=next(a for a in lock['artifacts'] if a['id']=='gradle')
    manager=next(a for a in lock['artifacts'] if a['id']=='cmdline-tools')
    acquire(gradle,root);installer.seed_wrapper_cache(gradle,root)
    tools=acquire(manager,root)
    status=build_apk.run_logged([str(tools/'bin/sdkmanager'),'--version'],cwd=root,
        environment=scoped,log=root/'sdkmanager-version.log',timeout=30)
    lib.require(status==0,'BLOCKED_CI_SDKMANAGER_VERSION')
    check_sdkmanager_version((root/'sdkmanager-version.log').read_text(),scoped['JDK_JAVA_OPTIONS'])
    init=root/'redirect.gradle';init.write_text(build_apk.init_script(root));init.chmod(0o600)
    argv=command(root/'gradle-cache',init)
    installer.private_write(root/'BUILD_INVOCATION.json',{'schema':'aioa.android.controlled-build.v1',
        'source_sha':source_sha,'command':argv,'init_sha256':lib.sha(init),'started_at':lib.utc(),
        'profile':'GITHUB_HOSTED_MANUAL_V1'})
    lib.gradle_configuration_check(root/'gradle-cache')
    status=build_apk.run_logged(['./gradlew','--no-daemon','--offline','--version'],
        cwd=lib.REPO/'clients/android',environment=scoped,log=root/'gradle-version.log',timeout=60)
    lib.require(status==0 and 'Gradle 8.13' in (root/'gradle-version.log').read_text(),'BLOCKED_CI_GRADLE_VERSION')
    lib.gradle_configuration_check(root/'gradle-cache')
    status=build_apk.run_logged(argv,cwd=lib.REPO/'clients/android',
        environment=scoped,log=root/'build.log',timeout=1800)
    lib.require(status==0,'BLOCKED_CI_BUILD_FAILED_LOG_PRESERVED')
    lib.source_check(source_sha)
    lib.gradle_configuration_check(root/'gradle-cache')
    lib.require(before==sdk_inventory(sdk),'BLOCKED_CI_SDK_CHANGED')
    apk=root/'builds/_app/outputs/apk/debug/app-debug.apk'
    evidence=verify_apk.verify(apk,root,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=scoped)
    evidence=build_apk._bind_controlled_build(evidence,source_sha,root,argv)
    evidence.update(ci_profile='GITHUB_HOSTED_MANUAL_V1',runner_image=image,
        sdk=before,versions=lock['versions'],dependency_resolution='ONLINE_VENDOR_REPOSITORIES_NOT_FULLY_HASH_LOCKED',
        model_calls=0,workflow_run_id=env['GITHUB_RUN_ID'],workflow_run_attempt=env['GITHUB_RUN_ATTEMPT'])
    artifact=root/'artifact';artifact.mkdir(mode=0o700)
    shutil.copyfile(apk,artifact/'aioa-companion-debug.apk')
    lib.require(lib.sha(artifact/'aioa-companion-debug.apk')==evidence['apk_sha256'],'BLOCKED_CI_ARTIFACT_READBACK')
    installer.private_write(artifact/'APK_EVIDENCE.json',evidence)
    return evidence


def build(env,source_sha,image):
    context_check(env,source_sha,image)
    lib.source_check(source_sha)
    workflow_check(env)
    branch_head_check(source_sha)
    result=execute(env,source_sha,image)
    branch_head_check(source_sha)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha',required=True);parser.add_argument('--runner-image',required=True)
    args=parser.parse_args();os.umask(0o077)
    try:value=build(os.environ,args.source_sha,args.runner_image)
    except lib.Blocked as e:value={'status':e.code,'automatic_retry':False}
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):
        value={'status':'BLOCKED_CI_UNKNOWN','automatic_retry':False}
    print(json.dumps(value,sort_keys=True,indent=2))
    return 0 if value['status']=='DEBUG_APK_VERIFIED_HOST_ONLY' else 2


if __name__=='__main__':raise SystemExit(main())
