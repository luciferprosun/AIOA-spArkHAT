"""Manual GitHub-hosted profile; never an override for local disk admission.

Runner SDK integrity is observed against an owner-reviewed image, not promoted
to a claim about independently published SDK archive SHA256 values.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
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
REVIEWED_WORKFLOW_SHA256='759cb4e6f71470c0ba9df9edf29a9a00f3f4dba7d8006795cb63d791d8e6f038'
DEBUG_PROFILE='DEBUG_TOOLCHAIN_V1'
ALTERNATE_DEBUG_PROFILE='DEBUG_UBUNTU22_V1'
ALTERNATE_IMAGE_VERSION='20261026.341.1'
DEBUG_IMAGE_METADATA_SHA256='6d35057ab003af4dc74998526957d7bde2e5526e1da06b4ed93201f6fa82e8ba'
# Observed on the first authorized run41322536413, not a publisher SDK digest.
DEBUG_SDK_INVENTORY_SHA256='9f81aed02ae39189e55282cd66a561969590f2c032a868beaa1afc7e3b51e793'
CODEQL_VERSION='2.27.3'
CODEQL_HOME=Path('/opt/hostedtoolcache/CodeQL/2.27.3/x64/codeql')
CODEQL_DATABASE=Path('/home/runner/work/_temp/aioa-codeql-databases/java')
STAGES=('IMAGE_CHECK','JDK_PREPARE','SDK_CHECK','GRADLE_BOOTSTRAP','JVM_TESTS',
    'LINT','ASSEMBLE','SIGNATURE_VERIFY','ARTIFACT_UPLOAD','CODEQL')
PATH_ROLES=frozenset(('UNKNOWN','SDK_ROOT','JOB_ROOT','JDK_ARCHIVE','JDK_ROOT','JAVA','JAVAC',
    'GRADLE_WRAPPER','SDKMANAGER','ANDROID_PROJECT','DEBUG_SIGNER','APK','COPIED_APK','CODEQL_TOOL',
    'PROJECT_SOURCE','JUNIT_REPORT','LINT_REPORT'))


def new_stages():
    return dict.fromkeys(STAGES,'NOT_RUN')


def command_check(status,valid,code):
    if status!=0 or not valid:
        error=lib.Blocked(code);error.build_exit_code=status
        raise error


@contextmanager
def phase(stages,name,path_role):
    previous=stages[name]
    stages[name]='RUNNING'
    try:yield
    except (lib.Blocked,OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as error:
        chosen=getattr(error,'ci_stage',name)
        if chosen not in STAGES:chosen=name
        code=getattr(error,'code','')
        if name=='SIGNATURE_VERIFY' and path_role in ('APK','COPIED_APK'):
            if type(code) is str and code.startswith('BLOCKED_JUNIT_'):
                chosen='JVM_TESTS';error.ci_path_role='JUNIT_REPORT'
            elif type(code) is str and code.startswith('BLOCKED_LINT_'):
                chosen='LINT';error.ci_path_role='LINT_REPORT'
            if chosen!=name:stages[name]='PASS' if previous=='PASS' else 'UNKNOWN'
        stages[chosen]='FAIL'
        error.ci_stage=chosen
        if getattr(error,'ci_path_role',None) not in PATH_ROLES:error.ci_path_role=path_role
        error.ci_stage_statuses=dict(stages)
        raise
    else:stages[name]='PASS'


def gradle_stages(text,stages):
    failed=None
    for line in text.splitlines():
        match=re.fullmatch(r'> Task :app:([A-Za-z0-9]+)(?: (FAILED|UP-TO-DATE|FROM-CACHE|SKIPPED|NO-SOURCE))?',line.strip())
        if not match:continue
        name,outcome=match.groups()
        stage=('JVM_TESTS' if name in ('testDebugUnitTest','testCosmic4UnitTest') else 'LINT' if name in
            ('lintDebug','lintReportDebug','lintAnalyzeDebug','lintCosmic4','lintReportCosmic4','lintAnalyzeCosmic4') else 'ASSEMBLE' if name in
            ('assembleDebug','packageDebug','validateSigningDebug','assembleCosmic4','packageCosmic4','validateSigningCosmic4') else 'GRADLE_BOOTSTRAP')
        stages[stage]='FAIL' if outcome=='FAILED' else 'SKIPPED' if outcome else 'PASS'
        if outcome=='FAILED' and failed is None:failed=stage
    return failed


def check_jdk(root,jdk,scoped,stages=None):
    stages=stages if stages is not None else new_stages()
    with phase(stages,'JDK_PREPARE','JAVA'):
        status=build_apk.run_logged([str(jdk/'bin/java'),'-XshowSettings:properties','-version'],
            cwd=root,environment=scoped,log=root/'java-version.log',timeout=15)
        text=(root/'java-version.log').read_text()
        command_check(status,re.search(r'17\.0\.21\+9(?:\D|$)',text),'BLOCKED_CI_JDK_VERSION')
        command_check(status,re.search(r'^\s*os\.arch\s*=\s*amd64\s*$',text,re.M)
            and re.search(r'^\s*java\.home\s*=\s*'+re.escape(str(jdk))+r'\s*$',text,re.M),
            'BLOCKED_CI_JDK_ARCH_OR_HOME')
    with phase(stages,'JDK_PREPARE','JAVAC'):
        status=build_apk.run_logged([str(jdk/'bin/javac'),'-version'],cwd=root,
            environment=scoped,log=root/'javac-version.log',timeout=15)
        text=(root/'javac-version.log').read_text()
        command_check(status,re.search(r'^javac 17\.0\.21\s*$',text,re.M),'BLOCKED_CI_JAVAC_VERSION')
    return {'architecture':'amd64','java_version':'17.0.21+9','javac_version':'17.0.21'}


def profile_evidence(env,*,purpose='apk'):
    profile=env.get('AIOA_BUILD_PROFILE','STRICT')
    lib.require(profile in ('STRICT',DEBUG_PROFILE,ALTERNATE_DEBUG_PROFILE),'BLOCKED_CI_BUILD_PROFILE')
    if profile=='STRICT':return {'build_profile':profile}
    lib.require(purpose=='apk' and env.get('AIOA_DEBUG_ENVIRONMENT_ACK')=='true'
        and env.get('AIOA_CODEQL_REQUESTED')=='false','BLOCKED_CI_DEBUG_PROFILE_CONSENT')
    expected_image=ALTERNATE_IMAGE_VERSION if profile==ALTERNATE_DEBUG_PROFILE else REVIEWED_IMAGE_VERSION
    raw=env.get('AIOA_IMAGE_SNAPSHOT','')
    lib.require(type(raw) is str and 0<len(raw)<=2048,'BLOCKED_CI_DEBUG_IMAGE_SNAPSHOT')
    snapshot=lib.strict_json(raw.encode())
    fields={'build_profile','metadata_version','declared_version','metadata_sha256','image_identity_status'}
    lib.require(type(snapshot) is dict and set(snapshot)==fields
        and all(type(v) is str for v in snapshot.values())
        and snapshot['build_profile']==profile and snapshot['declared_version']==expected_image
        and re.fullmatch('[0-9a-f]{64}',snapshot['metadata_sha256']) is not None,
        'BLOCKED_CI_DEBUG_IMAGE_SNAPSHOT')
    matched=(snapshot['metadata_version']==expected_image and snapshot['image_identity_status']=='MATCHED')
    exception=(profile==DEBUG_PROFILE and snapshot['metadata_version']=='20261025.353.1'
        and snapshot['metadata_sha256']==DEBUG_IMAGE_METADATA_SHA256
        and snapshot['image_identity_status']=='MISMATCH_ACCEPTED_DEBUG')
    exception=exception or (profile==ALTERNATE_DEBUG_PROFILE
        and snapshot['metadata_version']=='20261025.340.1'
        and snapshot['metadata_sha256']=='08a840f7186e0ab52ee613d5cafee66d245430928627dd25f6dc638bdd7e481f'
        and snapshot['image_identity_status']=='MISMATCH_ACCEPTED_DEBUG')
    lib.require(matched or exception,'BLOCKED_CI_DEBUG_IMAGE_SNAPSHOT')
    return {'build_profile':profile,'runner_observation':snapshot}


def context_check(env,source_sha,image,*,purpose='apk'):
    lib.require(purpose in ('apk','codeql'),'BLOCKED_CI_PURPOSE')
    profile_evidence(env,purpose=purpose)
    channel=env.get('AIOA_APK_CHANNEL') or None
    cosmic=verify_apk.cosmic4.validate(channel)
    source_ref=verify_apk.cosmic4.SOURCE_REF if cosmic else SOURCE_REF
    if cosmic:lib.require(purpose=='apk' and env.get('AIOA_CODEQL_REQUESTED','false')=='false','BLOCKED_CI_COSMIC4_PURPOSE')
    expected={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
        'GITHUB_REPOSITORY':'luciferprosun/AIOA-spArkHAT',
        'GITHUB_REPOSITORY_OWNER':'luciferprosun','GITHUB_ACTOR':'luciferprosun',
        'GITHUB_TRIGGERING_ACTOR':'luciferprosun','GITHUB_REF':source_ref,
        'GITHUB_WORKFLOW_REF':'luciferprosun/AIOA-spArkHAT/'+WORKFLOW_PATH+'@'+source_ref,
        'GITHUB_JOB':'debug-apk' if purpose=='apk' else 'codeql-kotlin','GITHUB_RUN_ATTEMPT':'1',
        'RUNNER_ENVIRONMENT':'github-hosted','RUNNER_ARCH':'X64',
        'ImageOS':'ubuntu22' if env.get('AIOA_BUILD_PROFILE')==ALTERNATE_DEBUG_PROFILE else 'ubuntu24',
        'RUNNER_TEMP':'/home/runner/work/_temp','AIOA_APPROVE_RUN':'true',
        'AIOA_SDK_LICENSE_ACK':'true','AIOA_ARTIFACT_ACK':'true'}
    lib.require(all(env.get(k)==v for k,v in expected.items()),'BLOCKED_CI_OWNER_OR_RUNNER_CONTEXT')
    lib.require(type(source_sha) is str and re.fullmatch(r'[0-9a-f]{40}',source_sha)
        and env.get('GITHUB_SHA')==env.get('GITHUB_WORKFLOW_SHA')==source_sha,'BLOCKED_CI_SOURCE')
    expected_image=ALTERNATE_IMAGE_VERSION if env.get('AIOA_BUILD_PROFILE')==ALTERNATE_DEBUG_PROFILE else REVIEWED_IMAGE_VERSION
    lib.require(image==env.get('ImageVersion')==expected_image,'BLOCKED_CI_IMAGE_DRIFT')
    lib.require(env.get('AIOA_WORKFLOW_REVISION')==REVIEWED_WORKFLOW_SHA256,'BLOCKED_CI_WORKFLOW_REVISION')
    lib.require(all(re.fullmatch(r'[0-9]{1,20}',env.get(k,''))
        for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')),'BLOCKED_CI_RUN_ID')
    requested=env.get('AIOA_CODEQL_REQUESTED','false')
    lib.require(requested in ('true','false'),'BLOCKED_CI_CODEQL_REQUEST')
    if purpose=='codeql' or requested=='true':
        lib.require(requested=='true' and env.get('AIOA_CODEQL_ACK')=='true'
            and env.get('AIOA_CODEQL_PROFILE')=='advanced-v1','BLOCKED_CI_CODEQL_OWNER_GATE')


def workflow_check(env):
    path=lib.safe_path(lib.REPO/WORKFLOW_PATH);info=path.lstat()
    lib.require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=65536,
        'BLOCKED_CI_WORKFLOW_FILE')
    lib.require(lib.sha(path)==env.get('AIOA_WORKFLOW_REVISION')==REVIEWED_WORKFLOW_SHA256,
        'BLOCKED_CI_WORKFLOW_REVISION')


def branch_head_check(source_sha, *, channel=None):
    # Anonymous fixed Git READ. No ambient credential helper, config or token.
    environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','GIT_TERMINAL_PROMPT':'0',
        'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1'}
    source_ref=verify_apk.cosmic4.SOURCE_REF if verify_apk.cosmic4.validate(channel) else SOURCE_REF
    response=subprocess.run(['git','-c','credential.helper=','ls-remote','--exit-code','--refs',
        'https://github.com/luciferprosun/AIOA-spArkHAT.git',source_ref],
        capture_output=True,text=True,timeout=20,env=environment,stdin=subprocess.DEVNULL)
    lib.require(response.returncode==0 and response.stdout.splitlines()==[source_sha+'\t'+source_ref],
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


def command(cache,init, *, channel=None):
    result=[part for part in build_apk.command(cache,init,channel=channel) if part!='--offline']
    return result[:1]+['-Pandroid.builder.sdkDownload=false',
        '-Dorg.gradle.java.installations.auto-download=false']+result[1:]


def codeql_tool_check(env):
    lib.require(env.get('CODEQL_DIST')==str(CODEQL_HOME),'BLOCKED_CI_CODEQL_TOOL_PATH')
    tool=lib.safe_path(CODEQL_HOME/'codeql');database=lib.safe_path(CODEQL_DATABASE)
    lib.require(tool.is_file() and os.access(tool,os.X_OK)
        and (database/'codeql-database.yml').is_file(),'BLOCKED_CI_CODEQL_NOT_INITIALIZED')
    return tool,database


def codeql_command(env,cache,init):
    tool,database=codeql_tool_check(env)
    argv=command(cache,init)
    lib.require(argv[-3:]==['testDebugUnitTest','lintDebug','assembleDebug'],'BLOCKED_CI_BUILD_COMMAND')
    argv=argv[:-3]+['--no-build-cache','--rerun-tasks',':app:compileDebugKotlin']
    return [str(tool),'database','trace-command','--threads=1','--ram=2048',
        '--working-dir='+str(lib.REPO/'clients/android'),str(database),'--',*argv]


def check_sdkmanager_version(text,options):
    notice='NOTE: Picked up JDK_JAVA_OPTIONS: '+options
    lines=[line.strip() for line in text.splitlines() if line.strip() and line.strip()!=notice]
    # Exact informational output from the SHA-bound cmdline-tools22 archive.
    # Unknown, partial or changed warnings still fail; no CLI/version migration.
    vendor_notice=[
        'WARNING: The SDK Manager CLI tool (sdkmanager) is deprecated. Use Android CLI instead.',
        "The 'android' binary can also be found in the cmdline-tools directory, and 'android sdk' is the replacement for 'sdkmanager'.",
        'To learn more about the Android CLI and how to use it, see the documentation (https://d.android.com/tools/agents/android-cli)']
    deprecated=lines[:len(vendor_notice)]==vendor_notice
    if deprecated:lines=lines[len(vendor_notice):]
    lib.require(lines==['22.0'],'BLOCKED_CI_SDKMANAGER_VERSION')
    return {'version':'22.0','vendor_notice':'SDKMANAGER_DEPRECATED' if deprecated else 'NONE'}


def prepare(env,source_sha,image,*,purpose='apk',stages=None):
    stages=stages if stages is not None else new_stages()
    channel=env.get('AIOA_APK_CHANNEL') or None
    with phase(stages,'IMAGE_CHECK','PROJECT_SOURCE'):
        lib.source_check(source_sha)
        lib.require(Path(env.get('GITHUB_WORKSPACE',''))==lib.REPO
            and lib.REPO.is_relative_to(Path('/home/runner/work')),'BLOCKED_CI_WORKSPACE')
    with phase(stages,'SDK_CHECK','SDK_ROOT'):
        sdk=lib.safe_path(env.get('ANDROID_SDK_ROOT',''))
        lib.require(sdk==Path('/usr/local/lib/android/sdk'),'BLOCKED_CI_VENDOR_PATH')
        before=sdk_inventory(sdk)
        lib.require(env.get('AIOA_BUILD_PROFILE','STRICT') not in (DEBUG_PROFILE,ALTERNATE_DEBUG_PROFILE)
            or before['inventory_sha256']==DEBUG_SDK_INVENTORY_SHA256,'BLOCKED_CI_DEBUG_SDK_INVENTORY')
    wrapper=lib.REPO/'clients/android/gradle/wrapper'
    with phase(stages,'JDK_PREPARE','JDK_ARCHIVE'):lock=installer.catalog()
    with phase(stages,'GRADLE_BOOTSTRAP','GRADLE_WRAPPER'):
        lib.require(lib.sha(wrapper/'gradle-wrapper.jar')==lock['wrapper_sha256']
            and lock['artifacts'][1]['sha256'] in (wrapper/'gradle-wrapper.properties').read_text(),
            'BLOCKED_CI_WRAPPER')
    with phase(stages,'JDK_PREPARE','JOB_ROOT'):
        root=lib.safe_path(Path(env['RUNNER_TEMP'])/('aioa-android-'+env['GITHUB_RUN_ID']+'-'+env['GITHUB_RUN_ATTEMPT']))
        root.mkdir(mode=0o700)  # Exclusive: never overwrite an earlier run.
        for name in ('tmp','android-user','java-user','downloads'):(root/name).mkdir(mode=0o700)
    # Hosted setup-java may return an image tool-cache symlink. Keep the
    # no-symlink boundary: use the existing locked downloader/extractor instead
    # of following the cached JAVA_HOME into a mutable system installation.
    with phase(stages,'JDK_PREPARE','JDK_ARCHIVE'):
        jdk_artifact=next(a for a in lock['artifacts'] if a['id']=='jdk')
        jdk=lib.safe_path(acquire(jdk_artifact,root))
        lib.require(jdk==root/'jdk-17','BLOCKED_CI_JDK_SOURCE')
    scoped=environment(root,jdk,sdk)
    scoped['AIOA_BUILD_SOURCE_SHA']=source_sha
    check_jdk(root,jdk,scoped,stages)
    gradle=next(a for a in lock['artifacts'] if a['id']=='gradle')
    manager=next(a for a in lock['artifacts'] if a['id']=='cmdline-tools')
    with phase(stages,'GRADLE_BOOTSTRAP','GRADLE_WRAPPER'):
        acquire(gradle,root);installer.seed_wrapper_cache(gradle,root)
    with phase(stages,'SDK_CHECK','SDKMANAGER'):
        tools=acquire(manager,root)
        status=build_apk.run_logged([str(tools/'bin/sdkmanager'),'--version'],cwd=root,
            environment=scoped,log=root/'sdkmanager-version.log',timeout=30)
        command_check(status,True,'BLOCKED_CI_SDKMANAGER_VERSION')
        manager_probe=check_sdkmanager_version((root/'sdkmanager-version.log').read_text(),scoped['JDK_JAVA_OPTIONS'])
        if manager_probe['vendor_notice']=='SDKMANAGER_DEPRECATED':
            print('SDKMANAGER_DEPRECATED: pinned22.0 verified; vendor informational notice retained.',file=sys.stderr,flush=True)
    init=root/'redirect.gradle';init.write_text(build_apk.init_script(root,channel=channel));init.chmod(0o600)
    argv=(command(root/'gradle-cache',init,channel=channel) if purpose=='apk'
        else codeql_command(env,root/'gradle-cache',init))
    installer.private_write(root/'BUILD_INVOCATION.json',{'schema':'aioa.android.controlled-build.v1',
        'source_sha':source_sha,'command':argv,'init_sha256':lib.sha(init),'started_at':lib.utc(),
        'profile':'GITHUB_HOSTED_MANUAL_V2','purpose':purpose,
        **profile_evidence(env,purpose=purpose),
        'jdk_source':'LOCKED_VENDOR_ARCHIVE_SHA256','jdk_archive_sha256':jdk_artifact['sha256'],
        'sdkmanager_probe':manager_probe,
        'workflow_revision':REVIEWED_WORKFLOW_SHA256})
    lib.gradle_configuration_check(root/'gradle-cache')
    with phase(stages,'GRADLE_BOOTSTRAP','GRADLE_WRAPPER'):
        status=build_apk.run_logged(['./gradlew','--no-daemon','--offline','--version'],
            cwd=lib.REPO/'clients/android',environment=scoped,log=root/'gradle-version.log',timeout=60)
        command_check(status,'Gradle 8.13' in (root/'gradle-version.log').read_text(),'BLOCKED_CI_GRADLE_VERSION')
    lib.gradle_configuration_check(root/'gradle-cache')
    return root,jdk,sdk,before,scoped,init,argv


def execute(env,source_sha,image,*,purpose='apk',stages=None):
    stages=stages if stages is not None else new_stages()
    root,jdk,sdk,before,scoped,init,argv=prepare(env,source_sha,image,purpose=purpose,stages=stages)
    channel=env.get('AIOA_APK_CHANNEL') or None
    variant='cosmic4' if verify_apk.cosmic4.validate(channel) else 'debug'
    if purpose=='apk':
        with phase(stages,'JDK_PREPARE','DEBUG_SIGNER'):
            if channel:verify_apk.cosmic4.prepare_signer(root,jdk,scoped,env)
            else:build_apk.prepare_debug_signer(root,jdk,scoped)
    if purpose=='codeql':
        tool,_=codeql_tool_check(env)
        # The CLI installs its own tracer into its child. Do not inherit ambient
        # JAVA_TOOL_OPTIONS/LD_PRELOAD/CODEQL credentials into the build.
        scoped['JDK_JAVA_OPTIONS']='-Duser.home='+str(root/'java-user')+' -Djava.io.tmpdir='+str(root/'tmp')
        status=build_apk.run_logged([str(tool),'version','--format=json'],cwd=root,
            environment=scoped,log=root/'codeql-version.log',timeout=30)
        lib.require(status==0,'BLOCKED_CI_CODEQL_VERSION')
        lines=[line for line in (root/'codeql-version.log').read_text().splitlines()
            if line.strip()!='NOTE: Picked up JDK_JAVA_OPTIONS: '+scoped['JDK_JAVA_OPTIONS']]
        version=lib.strict_json('\n'.join(lines).encode())
        lib.require(version.get('version')==CODEQL_VERSION,'BLOCKED_CI_CODEQL_VERSION')
    with phase(stages,'CODEQL' if purpose=='codeql' else 'GRADLE_BOOTSTRAP','ANDROID_PROJECT'):
        status=build_apk.run_logged(argv,cwd=lib.REPO/'clients/android',
            environment=scoped,log=root/'build.log',timeout=1800)
        failed=gradle_stages((root/'build.log').read_text(),stages) if purpose=='apk' and (root/'build.log').exists() else None
        if status!=0:
            error=lib.Blocked('BLOCKED_CI_BUILD_FAILED');error.build_exit_code=status
            if failed:error.ci_stage=failed
            raise error
    if purpose=='codeql':stages['CODEQL']='RUNNING'  # Trace completed; analyze has not run yet.
    with phase(stages,'IMAGE_CHECK','PROJECT_SOURCE'):lib.source_check(source_sha)
    with phase(stages,'GRADLE_BOOTSTRAP','GRADLE_WRAPPER'):lib.gradle_configuration_check(root/'gradle-cache')
    with phase(stages,'SDK_CHECK','SDK_ROOT'):lib.require(before==sdk_inventory(sdk),'BLOCKED_CI_SDK_CHANGED')
    with phase(stages,'JDK_PREPARE','JDK_ROOT'):
        jdk_artifact=next(a for a in installer.catalog()['artifacts'] if a['id']=='jdk')
        installer.component_check(jdk_artifact,root)
    if purpose=='codeql':
        evidence={'schema':'aioa.android.codeql-build.v1','status':'CODEQL_TRACED_BUILD_RETURNED_ZERO',
            'source_sha':source_sha,'runner_image':image,'workflow_revision':REVIEWED_WORKFLOW_SHA256,
            'command':argv,'build_log_sha256':lib.sha(root/'build.log'),
            'build_invocation_sha256':lib.sha(root/'BUILD_INVOCATION.json'),
            'codeql_version':CODEQL_VERSION,'codeql_analyze_verified':False,
            'server_upload_verified':False,'model_calls':0,'apk_built':False}
        installer.private_write(root/'CODEQL_BUILD_EVIDENCE.json',evidence)
        return evidence
    apk=root/('builds/_app/outputs/apk/'+variant+'/app-'+variant+'.apk')
    with phase(stages,'SIGNATURE_VERIFY','APK'):
        options={'channel':channel} if channel else {}
        evidence=verify_apk.verify(apk,root,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=scoped,**options)
        evidence=build_apk._bind_controlled_build(evidence,source_sha,root,argv,**options)
    for name in ('JVM_TESTS','LINT','ASSEMBLE'):stages[name]='PASS'
    evidence.update(ci_profile='GITHUB_HOSTED_MANUAL_V2',runner_image=image,
        **profile_evidence(env,purpose=purpose),
        workflow_revision=REVIEWED_WORKFLOW_SHA256,
        codeql_status='PENDING_SEPARATE_JOB' if env.get('AIOA_CODEQL_REQUESTED')=='true' else 'NOT_REQUESTED',
        sdk=before,versions=installer.catalog()['versions'],dependency_resolution='ONLINE_VENDOR_REPOSITORIES_NOT_FULLY_HASH_LOCKED',
        jdk_source='LOCKED_VENDOR_ARCHIVE_SHA256',jdk_archive_sha256=jdk_artifact['sha256'],
        model_calls=0,workflow_run_id=env['GITHUB_RUN_ID'],workflow_run_attempt=env['GITHUB_RUN_ATTEMPT'],
        stage_statuses=dict(stages))
    with phase(stages,'SIGNATURE_VERIFY','COPIED_APK'):
        artifact=verified_artifact(apk,root,evidence,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=scoped,**options)
    installer.private_write(artifact/'APK_EVIDENCE.json',evidence)
    return evidence


def verified_artifact(apk,root,evidence,*,sdk,jdk,source_sha,environment,channel=None):
    """Bounded copy, then independent aapt/apksigner/report readback of the copy."""
    verify_apk.assert_source_identity(evidence,channel=channel)
    artifact=lib.safe_path(root/'artifact');artifact.mkdir(mode=0o700)
    source=lib.safe_path(apk);target=artifact/'aioa-companion-debug.apk'
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        before=os.fstat(fd)
        lib.require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid()
            and before.st_nlink==1 and 0<before.st_size<=128*1024*1024,'BLOCKED_CI_ARTIFACT_SOURCE')
        out_fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'rb',closefd=False) as stream,os.fdopen(out_fd,'wb',closefd=False) as out:
                remaining=before.st_size
                while remaining:
                    data=stream.read(min(1024*1024,remaining))
                    lib.require(bool(data),'BLOCKED_CI_ARTIFACT_TRUNCATED')
                    out.write(data);remaining-=len(data)
                lib.require(not stream.read(1),'BLOCKED_CI_ARTIFACT_SIZE_DRIFT')
                out.flush();os.fsync(out.fileno())
        finally:os.close(out_fd)
        after=os.fstat(fd)
        lib.require((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
            'BLOCKED_CI_ARTIFACT_RACE')
    finally:os.close(fd)
    lib.require(lib.sha(target)==evidence['apk_sha256'],'BLOCKED_CI_ARTIFACT_READBACK')
    checksum=subprocess.run(['/usr/bin/sha256sum',str(target)],env=environment,
        stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
    lib.require(checksum.returncode==0 and not checksum.stderr
        and checksum.stdout==evidence['apk_sha256']+'  '+str(target)+'\n',
        'BLOCKED_CI_ARTIFACT_INDEPENDENT_HASH')
    options={'channel':channel} if channel else {}
    observed=verify_apk.verify(target,root,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=environment,**options)
    fields=('apk_sha256','bytes','certificate_sha256','package','version_code','version_name',
        'min_sdk','target_sdk','permissions','signature_permissions','debuggable','kind','inspected_checkout_sha',
        'junit_pass','junit_fail','junit_skip','lint_errors','report_digests')
    lib.require(all(name in observed and observed[name]==evidence[name] for name in fields),
        'BLOCKED_CI_ARTIFACT_METADATA')
    build_apk.assert_debug_signer(observed,root)
    return artifact


def preflight(env,source_sha,image,*,purpose='apk'):
    context_check(env,source_sha,image,purpose=purpose)
    lib.source_check(source_sha)
    workflow_check(env)
    options={'channel':env['AIOA_APK_CHANNEL']} if env.get('AIOA_APK_CHANNEL') else {}
    branch_head_check(source_sha,**options)
    sdk=lib.safe_path(env.get('ANDROID_SDK_ROOT',''))
    lib.require(sdk==Path('/usr/local/lib/android/sdk'),'BLOCKED_CI_VENDOR_PATH')
    observation=sdk_inventory(sdk)
    profile=profile_evidence(env,purpose=purpose)
    lib.require(profile['build_profile'] not in (DEBUG_PROFILE,ALTERNATE_DEBUG_PROFILE)
        or observation['inventory_sha256']==DEBUG_SDK_INVENTORY_SHA256,'BLOCKED_CI_DEBUG_SDK_INVENTORY')
    return {'status':'CI_PREFLIGHT_VERIFIED','source_sha':source_sha,'runner_image':image,
        **profile,
        'workflow_revision':REVIEWED_WORKFLOW_SHA256,'sdk_inventory_sha256':observation['inventory_sha256'],
        'no_tools_acquired':True,'purpose':purpose}


def build(env,source_sha,image,*,purpose='apk'):
    preflight(env,source_sha,image,purpose=purpose)
    stages=new_stages();stages.update(IMAGE_CHECK='PASS',SDK_CHECK='PASS')
    try:
        if purpose=='codeql':codeql_tool_check(env)
        result=execute(env,source_sha,image,purpose=purpose,stages=stages)
        options={'channel':env['AIOA_APK_CHANNEL']} if env.get('AIOA_APK_CHANNEL') else {}
        branch_head_check(source_sha,**options)
        return result
    except (lib.Blocked,OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as error:
        # Preserve the original nonzero outcome even if diagnostics cannot be
        # recorded. Failed preflight never reaches this writer or the tools.
        if not hasattr(error,'ci_stage_statuses'):error.ci_stage_statuses=dict(stages)
        try:record_failure(env,source_sha,image,error,purpose=purpose)
        except (lib.Blocked,OSError,ValueError,TypeError,KeyError):pass
        raise


def record_failure(env,source_sha,image,error,*,purpose='apk'):
    """Publishable structured diagnostics, never raw tool output or an APK.

    Only called after successful preflight. Private logs remain ephemeral;
    their hashes and bounded known public-source locations survive the job.
    """
    lib.require(purpose in ('apk','codeql') and all(re.fullmatch(r'[0-9]{1,20}',env.get(k,''))
        for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')),'BLOCKED_CI_DIAGNOSTIC_CONTEXT')
    suffix=env['GITHUB_RUN_ID']+'-'+env['GITHUB_RUN_ATTEMPT']
    parent=lib.safe_path(Path(env['RUNNER_TEMP']))
    root=parent/('aioa-android-'+suffix)
    logs=[];raw=b''
    for name in (() if root.is_symlink() else ('build.log','java-version.log','javac-version.log','gradle-version.log','sdkmanager-version.log',
                 'codeql-version.log','keytool-generate.log','keytool-certificate.log')):
        path=root/name
        if not path.exists() and not path.is_symlink():continue
        data=lib.private_bytes(path,max_bytes=8*1024*1024)
        logs.append({'name':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        if name=='build.log':raw=data
    manifest=lib.strict_json((lib.REPO/'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json').read_bytes())
    allowed={row['path'] for row in manifest['files'] if row['path'].startswith('clients/android/app/src/')
        and row['path'].endswith(('.kt','.java'))}
    tasks=set();locations=[]
    for line in raw.decode('utf-8','replace').splitlines():
        task=re.fullmatch(r'> Task :app:((?:compile(?:Debug|Cosmic4)Kotlin)|test(?:Debug|Cosmic4)UnitTest|lint(?:Debug|Cosmic4)|assemble(?:Debug|Cosmic4)) FAILED',line)
        if task:tasks.add(':app:'+task[1])
        match=re.match(r'^e: (?:file://)?(.+\.(?:kt|java)):(\d{1,6}):(\d{1,4})\s+(.+)$',line)
        if not match or len(locations)>=16:continue
        path=Path(match[1])
        if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(lib.REPO):continue
        relative=path.relative_to(lib.REPO).as_posix()
        if relative not in allowed or int(match[2])<1 or int(match[3])<1:continue
        category=next((value for text,value in [('Unresolved reference','UNRESOLVED_REFERENCE'),
            ('Type mismatch','TYPE_MISMATCH'),('Syntax error','SYNTAX_ERROR'),
            ('Cannot infer type','TYPE_INFERENCE')] if text in match[4]),'KOTLIN_COMPILER_ERROR')
        item={'path':relative,'line':int(match[2]),'column':int(match[3]),'category':category}
        if item not in locations:locations.append(item)
    code=getattr(error,'code',None)
    # Machine codes from the native exception type, never arbitrary messages or
    # tool/provider output. This preserves new installer errors without leaking text.
    native_code=(type(error) is lib.Blocked and type(code) is str
        and re.fullmatch(r'BLOCKED_[A-Z0-9_]{1,80}',code) is not None)
    exit_code=getattr(error,'build_exit_code',None)
    stages=new_stages()
    recorded=getattr(error,'ci_stage_statuses',{})
    if type(recorded) is dict:
        stages.update({k:v for k,v in recorded.items() if k in STAGES and v in ('NOT_RUN','PASS','FAIL','SKIPPED','RUNNING','UNKNOWN')})
    failed=gradle_stages(raw.decode('utf-8','replace'),stages) if purpose=='apk' else None
    stage=getattr(error,'ci_stage',None)
    if stage not in STAGES:stage=failed or ('CODEQL' if purpose=='codeql' else 'GRADLE_BOOTSTRAP')
    stages[stage]='FAIL'
    role=getattr(error,'ci_path_role','UNKNOWN')
    value={'schema':'aioa.android.failure-evidence.v1','status':'FAILED_NO_APK_PUBLICATION',
        **profile_evidence(env,purpose=purpose),
        'source_sha':source_sha,'source_binding':'REQUESTED_SHA_NOT_BUILD_ATTESTATION',
        'runner_image':image,'workflow_revision':REVIEWED_WORKFLOW_SHA256,
        'workflow_run_id':env['GITHUB_RUN_ID'],'workflow_run_attempt':env['GITHUB_RUN_ATTEMPT'],
        'purpose':purpose,'stage':stage,'stage_statuses':stages,
        'path_role':role if role in PATH_ROLES else 'UNKNOWN',
        'error_code':code if native_code else 'DIAGNOSTIC_UNAVAILABLE',
        'exit_code':exit_code if type(exit_code) is int and -128<=exit_code<=255 else None,
        'logs':logs,'failed_tasks':sorted(tasks),'compiler_locations':locations,
        'diagnostic_status':'STRUCTURED_DIAGNOSTIC_AVAILABLE' if tasks or locations or native_code else 'DIAGNOSTIC_UNAVAILABLE',
        'raw_log_retention':'EPHEMERAL_RUNNER_ONLY','apk_verified':False,'automatic_retry':False}
    destination=lib.safe_path(parent/('aioa-failure-'+suffix+'-'+purpose));destination.mkdir(mode=0o700)
    installer.private_write(destination/'BUILD_FAILURE_EVIDENCE.json',value)
    return value


def codeql_readback(env,source_sha,image):
    context_check(env,source_sha,image,purpose='codeql')
    lib.source_check(source_sha);workflow_check(env);branch_head_check(source_sha)
    lib.require(re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        env.get('AIOA_SARIF_ID','')) is not None,'BLOCKED_CI_SARIF_UPLOAD_ID')
    root=lib.safe_path(Path(env['RUNNER_TEMP'])/('aioa-android-'+env['GITHUB_RUN_ID']+'-'+env['GITHUB_RUN_ATTEMPT']))
    evidence=lib.private_json(root/'CODEQL_BUILD_EVIDENCE.json')
    invocation=lib.private_json(root/'BUILD_INVOCATION.json')
    lib.require(evidence.get('schema')=='aioa.android.codeql-build.v1'
        and evidence.get('status')=='CODEQL_TRACED_BUILD_RETURNED_ZERO'
        and evidence.get('codeql_version')==CODEQL_VERSION
        and evidence.get('model_calls')==0 and evidence.get('apk_built') is False
        and evidence.get('codeql_analyze_verified') is False and evidence.get('server_upload_verified') is False
        and evidence.get('source_sha')==invocation.get('source_sha')==source_sha
        and invocation.get('schema')=='aioa.android.controlled-build.v1'
        and invocation.get('purpose')=='codeql'
        and invocation.get('workflow_revision')==REVIEWED_WORKFLOW_SHA256
        and invocation.get('init_sha256')==lib.sha(root/'redirect.gradle')
        and evidence.get('runner_image')==image
        and evidence.get('command')==invocation.get('command')==codeql_command(env,root/'gradle-cache',root/'redirect.gradle')
        and evidence.get('workflow_revision')==REVIEWED_WORKFLOW_SHA256
        and evidence.get('build_log_sha256')==lib.sha(root/'build.log')
        and evidence.get('build_invocation_sha256')==lib.sha(root/'BUILD_INVOCATION.json'),
        'BLOCKED_CI_CODEQL_BUILD_READBACK')
    path=lib.safe_path(Path(env['RUNNER_TEMP'])/'aioa-codeql-sarif/java.sarif')
    lib.require(path.is_file() and path.stat().st_size<=32*1024*1024,'BLOCKED_CI_SARIF_MISSING')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        before=os.fstat(fd)
        lib.require(stat.S_ISREG(before.st_mode) and before.st_nlink==1
            and before.st_uid==os.getuid() and before.st_size<=32*1024*1024,'BLOCKED_CI_SARIF_FILE')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(32*1024*1024+1)
        after=os.fstat(fd)
        lib.require(len(raw)<=32*1024*1024
            and (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'BLOCKED_CI_SARIF_RACE')
    finally:os.close(fd)
    sarif=lib.strict_json(raw);runs=sarif.get('runs')
    lib.require(sarif.get('version')=='2.1.0' and type(runs) is list and bool(runs)
        and all(type(run) is dict and run.get('tool',{}).get('driver',{}).get('name')=='CodeQL'
            and run.get('automationDetails',{}).get('id','').rstrip('/')=='/language:java-kotlin'
            and type(run.get('results')) is list
            and type(run.get('versionControlProvenance',[])) is list
            and all(type(p) is dict and p.get('revisionId')==source_sha for p in run.get('versionControlProvenance',[]))
            for run in runs),
        'BLOCKED_CI_SARIF_FORMAT')
    artifact=root/'codeql-artifact';artifact.mkdir(mode=0o700)
    filtered={k:evidence[k] for k in ('source_sha','runner_image','workflow_revision','codeql_version',
        'build_log_sha256','build_invocation_sha256','model_calls','apk_built')}
    filtered.update(schema='aioa.android.codeql-evidence.v1',status='SARIF_READBACK_VERIFIED_UPLOAD_STATUS_PENDING',
        sarif_sha256=hashlib.sha256(raw).hexdigest(),workflow_run_id=env['GITHUB_RUN_ID'],
        workflow_run_attempt=env['GITHUB_RUN_ATTEMPT'],server_upload_verified=False,
        source_binding='CONTROLLED_CHECKOUT_AND_BUILD_NOT_SERVER_ATTESTATION',
        source_verification_status='PENDING_SERVER_COMMIT_SHA_READBACK',
        server_sarif_id=env['AIOA_SARIF_ID'],
        sarif_embedded_revision='MATCHED' if all(run.get('versionControlProvenance') for run in runs) else 'ABSENT')
    installer.private_write(artifact/'CODEQL_EVIDENCE.json',filtered)
    return filtered


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha',required=True);parser.add_argument('--runner-image',required=True)
    parser.add_argument('--purpose',choices=('apk','codeql'),default='apk')
    parser.add_argument('--verify-codeql',action='store_true')
    parser.add_argument('--preflight-only',action='store_true')
    args=parser.parse_args();os.umask(0o077)
    try:
        lib.require(not (args.verify_codeql and args.preflight_only),'BLOCKED_CI_PURPOSE')
        if args.verify_codeql:
            lib.require(args.purpose=='codeql','BLOCKED_CI_PURPOSE')
            value=codeql_readback(os.environ,args.source_sha,args.runner_image)
        elif args.preflight_only:value=preflight(os.environ,args.source_sha,args.runner_image,purpose=args.purpose)
        else:value=build(os.environ,args.source_sha,args.runner_image,purpose=args.purpose)
    except lib.Blocked as e:value={'status':e.code,'automatic_retry':False}
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):
        value={'status':'BLOCKED_CI_UNKNOWN','automatic_retry':False}
    print(json.dumps(value,sort_keys=True,indent=2))
    return 0 if value['status'] in ('DEBUG_APK_VERIFIED_HOST_ONLY','CODEQL_TRACED_BUILD_RETURNED_ZERO',
        'SARIF_READBACK_VERIFIED_UPLOAD_STATUS_PENDING','CI_PREFLIGHT_VERIFIED') else 2


if __name__=='__main__':raise SystemExit(main())
