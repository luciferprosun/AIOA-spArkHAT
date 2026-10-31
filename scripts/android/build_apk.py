"""One bounded build in external owned output, no phone/retry/publishing."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import threading
import time

if __package__:
    from . import installer,toolchain_lib as lib,verify_apk
else:
    import installer
    import toolchain_lib as lib
    import verify_apk


def command(cache,init):
    return ['./gradlew','--no-daemon','--max-workers=1','--offline',
        '--project-cache-dir',str(cache/'project'),'--init-script',str(init),
        '-Dorg.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=384m -Dfile.encoding=UTF-8',
        '-Pkotlin.compiler.execution.strategy=in-process','-Pkotlin.project.persistent.dir='+str(cache/'kotlin'),
        'testDebugUnitTest','lintDebug','assembleDebug']


def init_script(output):
    # Only a native-owned, constrained output path is interpolated; never a model
    # instruction or workflow input. JSON quotes the fixed path for Groovy.
    build=json.dumps(str(output/'builds'));key=json.dumps(str(output/'debug.keystore'))
    return '''allprojects { p ->
  p.layout.buildDirectory.set(new File(%s, p.path == ':' ? 'root' : p.path.replace(':','_')))
  p.plugins.withId('com.android.application') {
    p.android.signingConfigs.getByName('debug').storeFile = new File(%s)
  }
}
''' % (build,key)


def run_logged(argv,*,cwd,environment,log,timeout=1800):
    """Bound output/time and clean only our own process group, leader PID pinned."""
    lib.require(not Path(log).exists(),'BLOCKED_LOG_EXISTS')
    lib.require(threading.current_thread() is threading.main_thread(),'BLOCKED_SIGNAL_CONTEXT')
    cancelled=[False]
    def request_stop(_signum,_frame):cancelled[0]=True
    handlers={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    for sig in handlers:signal.signal(sig,request_stop)
    process=None;poll=selectors.DefaultSelector()
    try:
        process=subprocess.Popen(argv,cwd=cwd,env=environment,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        poll.register(process.stdout,selectors.EVENT_READ)
        deadline=time.monotonic()+timeout;count=0
        with open(log,'xb') as out:
            while True:
                lib.require(not cancelled[0],'BLOCKED_BUILD_CANCELLED')
                lib.require(time.monotonic()<deadline,'BLOCKED_BUILD_TIMEOUT')
                exited=os.waitid(os.P_PID,process.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                if not poll.get_map() and exited is not None:break
                for item,_ in poll.select(.1):
                    data=os.read(item.fileobj.fileno(),16384)
                    if not data:poll.unregister(item.fileobj);continue
                    count+=len(data);lib.require(count<=8*1024*1024,'BLOCKED_BUILD_LOG_SIZE')
                    out.write(data)
            out.flush();os.fsync(out.fileno())
    finally:
        try:
            if process is not None:
                for sig in (signal.SIGTERM,signal.SIGKILL):
                    try:os.killpg(process.pid,sig)
                    except ProcessLookupError:pass
                    if sig==signal.SIGTERM:time.sleep(.05)
                process.wait(timeout=5);process.stdout.close()
        finally:
            poll.close()
            for sig,handler in handlers.items():signal.signal(sig,handler)
    lib.require(not cancelled[0],'BLOCKED_BUILD_CANCELLED')
    return process.returncode


def _bind_controlled_build(evidence,source_sha,output,argv):
    """Called only after this trusted process's successful controlled build.

No CLI option/imported receipt can upgrade standalone artifact verification.
This is a local process-origin record, not a third-party build attestation.
"""
    invocation=lib.private_json(output/'BUILD_INVOCATION.json')
    lib.require(evidence['status']=='DEBUG_APK_VALID_SOURCE_UNBOUND'
        and invocation['source_sha']==source_sha and invocation['command']==argv
        and invocation['init_sha256']==lib.sha(output/'redirect.gradle')
        and evidence['inspected_checkout_sha']==source_sha,'BLOCKED_BUILD_BINDING')
    return {**evidence,'status':'DEBUG_APK_VERIFIED_HOST_ONLY','source_sha':source_sha,
        'source_binding':'CONTROLLED_BUILD_PROCESS',
        'build_invocation_sha256':lib.sha(output/'BUILD_INVOCATION.json'),
        'build_log_sha256':lib.sha(output/'build.log'),
        'gradle_version_log_sha256':lib.sha(output/'gradle-version.log'),
        'third_party_build_attestation':False}


def resources():
    info={s.split(':')[0]:int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith(('MemTotal:','MemAvailable:'))}
    lib.require(info.get('MemAvailable',0)>=1536*1024**2,'BLOCKED_AVAILABLE_RAM')
    return info


def execute_build(source_sha):
    inputs=lib.source_check(source_sha);lib.assert_admitted()
    lib.gradle_configuration_check(lib.ROOT/'gradle-cache')
    installer.verify_versions();resources()
    installer.wrapper_cache_check()
    installer.bounded_probe(lib.ROOT)
    parent=lib.safe_path(lib.ROOT/'build-output'/source_sha);parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix='run-',dir=parent));init=output/'redirect.gradle'
    init.write_text(init_script(output));init.chmod(0o600)
    environment=installer.scoped_environment()
    for name in ('java-user','tmp'):(output/name).mkdir(mode=0o700)
    environment['JDK_JAVA_OPTIONS']='-Xmx128m -Duser.home='+str(output/'java-user')+' -Djava.io.tmpdir='+str(output/'tmp')
    cache=lib.ROOT/'gradle-cache'/source_sha;cache.mkdir(mode=0o700,exist_ok=True)
    argv=command(cache,init)
    installer.private_write(output/'BUILD_INVOCATION.json',{'schema':'aioa.android.controlled-build.v1',
        'source_sha':source_sha,'command':argv,'init_sha256':lib.sha(init),'started_at':lib.utc(),
        'profile':'LOCAL_G1_QUALIFIED_V1'})
    # The wrapper must use the already verified distribution, even offline.
    version=run_logged(['./gradlew','--no-daemon','--offline','--version'],cwd=lib.REPO/'clients/android',
        environment=environment,log=output/'gradle-version.log',timeout=60)
    lib.require(version==0 and 'Gradle 8.13' in (output/'gradle-version.log').read_text(),'BLOCKED_GRADLE_VERSION')
    lib.gradle_configuration_check(lib.ROOT/'gradle-cache')
    status=run_logged(argv,cwd=lib.REPO/'clients/android',environment=environment,log=output/'build.log')
    lib.require(status==0,'BLOCKED_BUILD_FAILED_LOG_PRESERVED')
    lib.source_check(source_sha);lib.assert_admitted();lib.gradle_configuration_check(lib.ROOT/'gradle-cache')
    apk=output/'builds/_app/outputs/apk/debug/app-debug.apk'
    result=verify_apk.verify(apk,output,sdk=lib.ROOT/'sdk',jdk=lib.ROOT/'jdk-17',source_sha=source_sha,environment=environment)
    result=_bind_controlled_build(result,source_sha,output,argv)
    installer.private_write(output/'APK_EVIDENCE.json',result)
    return result


def build(source_sha):
    gate=lib.admission()
    if not gate['may_stage']:return {'status':'BLOCKED_STORAGE_TOOLCHAIN','storage':gate,'build_attempts':0}
    return execute_build(source_sha)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source-sha',required=True)
    args=parser.parse_args()
    try:value=build(args.source_sha)
    except lib.Blocked as e:value={'status':e.code,'automatic_retry':False}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):value={'status':'BLOCKED_BUILD_UNKNOWN','automatic_retry':False}
    print(json.dumps(value,sort_keys=True,indent=2))
    return 0 if value['status']=='DEBUG_APK_VERIFIED_HOST_ONLY' else 2


if __name__=='__main__':raise SystemExit(main())
