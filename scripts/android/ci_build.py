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
REVIEWED_WORKFLOW_SHA256='4dd97937fe9923c20fc3786a5b338c28f0f621e9cd8ce2e8878f15aa74e64f68'
CODEQL_VERSION='2.27.3'
CODEQL_HOME=Path('/opt/hostedtoolcache/CodeQL/2.27.3/x64/codeql')
CODEQL_DATABASE=Path('/home/runner/work/_temp/aioa-codeql-databases/java')


def context_check(env,source_sha,image,*,purpose='apk'):
    lib.require(purpose in ('apk','codeql'),'BLOCKED_CI_PURPOSE')
    expected={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
        'GITHUB_REPOSITORY':'luciferprosun/AIOA-spArkHAT',
        'GITHUB_REPOSITORY_OWNER':'luciferprosun','GITHUB_ACTOR':'luciferprosun',
        'GITHUB_TRIGGERING_ACTOR':'luciferprosun','GITHUB_REF':SOURCE_REF,
        'GITHUB_WORKFLOW_REF':'luciferprosun/AIOA-spArkHAT/'+WORKFLOW_PATH+'@'+SOURCE_REF,
        'GITHUB_JOB':'debug-apk' if purpose=='apk' else 'codeql-kotlin','GITHUB_RUN_ATTEMPT':'1',
        'RUNNER_ENVIRONMENT':'github-hosted','RUNNER_ARCH':'X64','ImageOS':'ubuntu24',
        'RUNNER_TEMP':'/home/runner/work/_temp','AIOA_APPROVE_RUN':'true',
        'AIOA_SDK_LICENSE_ACK':'true','AIOA_ARTIFACT_ACK':'true'}
    lib.require(all(env.get(k)==v for k,v in expected.items()),'BLOCKED_CI_OWNER_OR_RUNNER_CONTEXT')
    lib.require(type(source_sha) is str and re.fullmatch(r'[0-9a-f]{40}',source_sha)
        and env.get('GITHUB_SHA')==env.get('GITHUB_WORKFLOW_SHA')==source_sha,'BLOCKED_CI_SOURCE')
    lib.require(image==env.get('ImageVersion')==REVIEWED_IMAGE_VERSION,'BLOCKED_CI_IMAGE_DRIFT')
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
    return [str(tool),'database','trace-command','--threads=1','--ram=2048',str(database),'--',*argv]


def check_sdkmanager_version(text,options):
    notice='NOTE: Picked up JDK_JAVA_OPTIONS: '+options
    lines=[line.strip() for line in text.splitlines() if line.strip() and line.strip()!=notice]
    lib.require(lines==['22.0'],'BLOCKED_CI_SDKMANAGER_VERSION')


def prepare(env,source_sha,image,*,purpose='apk'):
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
    argv=(command(root/'gradle-cache',init) if purpose=='apk'
        else codeql_command(env,root/'gradle-cache',init))
    installer.private_write(root/'BUILD_INVOCATION.json',{'schema':'aioa.android.controlled-build.v1',
        'source_sha':source_sha,'command':argv,'init_sha256':lib.sha(init),'started_at':lib.utc(),
        'profile':'GITHUB_HOSTED_MANUAL_V2','purpose':purpose,
        'workflow_revision':REVIEWED_WORKFLOW_SHA256})
    lib.gradle_configuration_check(root/'gradle-cache')
    status=build_apk.run_logged(['./gradlew','--no-daemon','--offline','--version'],
        cwd=lib.REPO/'clients/android',environment=scoped,log=root/'gradle-version.log',timeout=60)
    lib.require(status==0 and 'Gradle 8.13' in (root/'gradle-version.log').read_text(),'BLOCKED_CI_GRADLE_VERSION')
    lib.gradle_configuration_check(root/'gradle-cache')
    return root,jdk,sdk,before,scoped,init,argv


def execute(env,source_sha,image,*,purpose='apk'):
    root,jdk,sdk,before,scoped,init,argv=prepare(env,source_sha,image,purpose=purpose)
    if purpose=='apk':build_apk.prepare_debug_signer(root,jdk,scoped)
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
    status=build_apk.run_logged(argv,cwd=lib.REPO/'clients/android',
        environment=scoped,log=root/'build.log',timeout=1800)
    lib.require(status==0,'BLOCKED_CI_BUILD_FAILED_LOG_PRESERVED')
    lib.source_check(source_sha)
    lib.gradle_configuration_check(root/'gradle-cache')
    lib.require(before==sdk_inventory(sdk),'BLOCKED_CI_SDK_CHANGED')
    if purpose=='codeql':
        evidence={'schema':'aioa.android.codeql-build.v1','status':'CODEQL_TRACED_BUILD_RETURNED_ZERO',
            'source_sha':source_sha,'runner_image':image,'workflow_revision':REVIEWED_WORKFLOW_SHA256,
            'command':argv,'build_log_sha256':lib.sha(root/'build.log'),
            'build_invocation_sha256':lib.sha(root/'BUILD_INVOCATION.json'),
            'codeql_version':CODEQL_VERSION,'codeql_analyze_verified':False,
            'server_upload_verified':False,'model_calls':0,'apk_built':False}
        installer.private_write(root/'CODEQL_BUILD_EVIDENCE.json',evidence)
        return evidence
    apk=root/'builds/_app/outputs/apk/debug/app-debug.apk'
    evidence=verify_apk.verify(apk,root,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=scoped)
    evidence=build_apk._bind_controlled_build(evidence,source_sha,root,argv)
    evidence.update(ci_profile='GITHUB_HOSTED_MANUAL_V2',runner_image=image,
        workflow_revision=REVIEWED_WORKFLOW_SHA256,
        codeql_status='PENDING_SEPARATE_JOB' if env.get('AIOA_CODEQL_REQUESTED')=='true' else 'NOT_REQUESTED',
        sdk=before,versions=installer.catalog()['versions'],dependency_resolution='ONLINE_VENDOR_REPOSITORIES_NOT_FULLY_HASH_LOCKED',
        model_calls=0,workflow_run_id=env['GITHUB_RUN_ID'],workflow_run_attempt=env['GITHUB_RUN_ATTEMPT'])
    artifact=verified_artifact(apk,root,evidence,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=scoped)
    installer.private_write(artifact/'APK_EVIDENCE.json',evidence)
    return evidence


def verified_artifact(apk,root,evidence,*,sdk,jdk,source_sha,environment):
    """Bounded copy, then independent aapt/apksigner/report readback of the copy."""
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
    observed=verify_apk.verify(target,root,sdk=sdk,jdk=jdk,source_sha=source_sha,environment=environment)
    fields=('apk_sha256','bytes','certificate_sha256','package','version_code','version_name',
        'min_sdk','target_sdk','permissions','debuggable','kind','inspected_checkout_sha',
        'junit_pass','junit_fail','junit_skip','lint_errors','report_digests')
    lib.require(all(name in observed and observed[name]==evidence[name] for name in fields),
        'BLOCKED_CI_ARTIFACT_METADATA')
    build_apk.assert_debug_signer(observed,root)
    return artifact


def preflight(env,source_sha,image,*,purpose='apk'):
    context_check(env,source_sha,image,purpose=purpose)
    lib.source_check(source_sha)
    workflow_check(env)
    branch_head_check(source_sha)
    sdk=lib.safe_path(env.get('ANDROID_SDK_ROOT',''))
    lib.require(sdk==Path('/usr/local/lib/android/sdk'),'BLOCKED_CI_VENDOR_PATH')
    observation=sdk_inventory(sdk)
    return {'status':'CI_PREFLIGHT_VERIFIED','source_sha':source_sha,'runner_image':image,
        'workflow_revision':REVIEWED_WORKFLOW_SHA256,'sdk_inventory_sha256':observation['inventory_sha256'],
        'no_tools_acquired':True,'purpose':purpose}


def build(env,source_sha,image,*,purpose='apk'):
    preflight(env,source_sha,image,purpose=purpose)
    if purpose=='codeql':codeql_tool_check(env)
    result=execute(env,source_sha,image,purpose=purpose)
    branch_head_check(source_sha)
    return result


def codeql_readback(env,source_sha,image):
    context_check(env,source_sha,image,purpose='codeql')
    lib.source_check(source_sha);workflow_check(env);branch_head_check(source_sha)
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
            and type(run.get('versionControlProvenance')) is list
            and bool(run['versionControlProvenance'])
            and all(type(p) is dict and p.get('revisionId')==source_sha for p in run['versionControlProvenance'])
            for run in runs),
        'BLOCKED_CI_SARIF_FORMAT')
    artifact=root/'codeql-artifact';artifact.mkdir(mode=0o700)
    filtered={k:evidence[k] for k in ('source_sha','runner_image','workflow_revision','codeql_version',
        'build_log_sha256','build_invocation_sha256','model_calls','apk_built')}
    filtered.update(schema='aioa.android.codeql-evidence.v1',status='SARIF_READBACK_VERIFIED_UPLOAD_STATUS_PENDING',
        sarif_sha256=hashlib.sha256(raw).hexdigest(),workflow_run_id=env['GITHUB_RUN_ID'],
        workflow_run_attempt=env['GITHUB_RUN_ATTEMPT'],server_upload_verified=False)
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
