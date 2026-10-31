"""One bounded build in external owned output, no phone/retry/publishing."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
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
    process=subprocess.Popen(argv,cwd=cwd,env=environment,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    poll=selectors.DefaultSelector();poll.register(process.stdout,selectors.EVENT_READ)
    deadline=time.monotonic()+timeout;count=0
    try:
        with open(log,'xb') as out:
            while True:
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
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(process.pid,sig)
            except ProcessLookupError:pass
            if sig==signal.SIGTERM:time.sleep(.05)
        process.wait(timeout=5);poll.close();process.stdout.close()
    return process.returncode


def resources():
    info={s.split(':')[0]:int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith(('MemTotal:','MemAvailable:'))}
    lib.require(info.get('MemAvailable',0)>=1536*1024**2,'BLOCKED_AVAILABLE_RAM')
    return info


def execute_build(source_sha):
    inputs=lib.source_check(source_sha);lib.assert_admitted();installer.verify_versions();resources()
    installer.wrapper_cache_check()
    installer.bounded_probe(lib.ROOT)
    parent=lib.safe_path(lib.ROOT/'build-output'/source_sha);parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix='run-',dir=parent));init=output/'redirect.gradle'
    init.write_text(init_script(output));init.chmod(0o600)
    environment=installer.scoped_environment();environment['JAVA_OPTS']='-Xmx128m'
    cache=lib.ROOT/'gradle-cache'/source_sha;cache.mkdir(mode=0o700,exist_ok=True)
    # The wrapper must use the already verified distribution, even offline.
    version=run_logged(['./gradlew','--no-daemon','--offline','--version'],cwd=lib.REPO/'clients/android',
        environment=environment,log=output/'gradle-version.log',timeout=60)
    lib.require(version==0 and 'Gradle 8.13' in (output/'gradle-version.log').read_text(),'BLOCKED_GRADLE_VERSION')
    status=run_logged(command(cache,init),cwd=lib.REPO/'clients/android',environment=environment,log=output/'build.log')
    lib.require(status==0,'BLOCKED_BUILD_FAILED_LOG_PRESERVED')
    lib.source_check(source_sha);lib.assert_admitted()
    apk=output/'builds/_app/outputs/apk/debug/app-debug.apk'
    result=verify_apk.verify(apk,output,sdk=lib.ROOT/'sdk',jdk=lib.ROOT/'jdk-17',source_sha=source_sha,environment=environment)
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
