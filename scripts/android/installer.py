"""Pinned, idempotent user-space installer. No license acceptance or repairs."""
import argparse
import fcntl
import json
import hashlib
import os
from pathlib import Path
import stat
import shutil
import subprocess
import sys
import tempfile
import uuid

if __package__:
    from . import toolchain_lib as lib
else:
    import toolchain_lib as lib

LOCKFILE=Path(__file__).with_name('toolchain.lock.json')
COMPONENT='.aioa-component.json'
COMPONENT_LIMIT=16*1024*1024


def wrapper_relative_home():
    # Upstream Gradle8.13 PathAssembler layout, not a security checksum. Actual
    # integrity is the separately pinned SHA256 of the distribution and each file.
    url='https://services.gradle.org/distributions/gradle-8.13-bin.zip'
    number=int.from_bytes(hashlib.md5(url.encode(),usedforsecurity=False).digest(),'big')
    alphabet='0123456789abcdefghijklmnopqrstuvwxyz';result=''
    while number:
        number,digit=divmod(number,36);result=alphabet[digit]+result
    return Path('gradle-cache/wrapper/dists/gradle-8.13-bin')/(result or '0')/'gradle-8.13'


def seed_wrapper_cache(artifact,root):
    destination=component_check(artifact,root)
    lib.require(destination==root/wrapper_relative_home(),'BLOCKED_WRAPPER_CACHE_PATH')
    archive=lib.download(artifact,root/'downloads')
    cached=lib.safe_path(destination.parent/artifact['filename'])
    if cached.exists():lib.require(lib.sha(cached)==artifact['sha256'],'BLOCKED_WRAPPER_CACHE_DRIFT')
    else:
        temp=cached.with_name(cached.name+'.seed-'+uuid.uuid4().hex)
        with open(archive,'rb') as source,open(temp,'xb') as target:
            shutil.copyfileobj(source,target,1024*1024);target.flush();os.fsync(target.fileno())
        lib.promote(temp,cached)
    marker=lib.safe_path(cached.with_name(cached.name+'.ok'))
    if not marker.exists():
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    wrapper_cache_check(root)


def wrapper_cache_check(root=lib.ROOT):
    artifact=next(a for a in catalog()['artifacts'] if a['id']=='gradle')
    destination=component_check(artifact,root)
    cached=lib.safe_path(destination.parent/artifact['filename'])
    marker=lib.safe_path(cached.with_name(cached.name+'.ok'))
    lib.require(destination==root/wrapper_relative_home() and cached.is_file() and marker.is_file()
        and lib.sha(cached)==artifact['sha256'] and (destination/'lib/gradle-launcher-8.13.jar').is_file(),
        'BLOCKED_WRAPPER_CACHE')
    return destination


def catalog():
    value=json.loads(LOCKFILE.read_text())
    lib.require(value['schema']=='aioa.android.toolchain-lock.v1','BLOCKED_LOCK_SCHEMA')
    return value


def plan():
    value=catalog()
    return {'schema':'aioa.android.install-plan.v1','versions':value['versions'],
        'artifacts':[{'id':a['id'],'version':a['version'],'published_sha256':a['sha256'] is not None} for a in value['artifacts']],
        'possible_blockers':['BLOCKED_STORAGE_TOOLCHAIN','BLOCKED_LICENSE','BLOCKED_PUBLISHED_SHA256','BLOCKED_DIRTY_SOURCE'],
        'sdk_licenses_accepted_by_tool':False,'downloads':0}


def tree_manifest(directory):
    directory=lib.safe_path(directory);rows=[]
    for path in sorted(directory.rglob('*')):
        lib.safe_path(path)
        if path.is_dir():continue
        lib.require(stat.S_ISREG(path.lstat().st_mode),'BLOCKED_COMPONENT_TYPE')
        if path==directory/COMPONENT:continue
        rows.append({'path':path.relative_to(directory).as_posix(),'sha256':lib.sha(path),
                     'bytes':path.stat().st_size,'executable':bool(path.stat().st_mode & 0o111)})
    lib.require(bool(rows),'BLOCKED_EMPTY_COMPONENT')
    return sorted(rows,key=lambda row:row['path'])


def component_check(artifact,root=lib.ROOT,*,directory=None):
    lib.validate_artifact(artifact)
    destination=lib.safe_path(directory if directory is not None else root/artifact['destination'])
    lib.require(destination.is_relative_to(root),'BLOCKED_COMPONENT_PATH')
    lib.require(destination.is_dir(),'BLOCKED_MISSING_COMPONENT')
    value=lib.private_json(destination/COMPONENT,max_bytes=COMPONENT_LIMIT)
    witness=lib.archive_inventory(root/'downloads'/artifact['filename'],
        expected_sha256=artifact['sha256'],expected_size=artifact['size'])
    lib.require(value['id']==artifact['id'] and value['version']==artifact['version']
        and value['archive_sha256']==artifact['sha256'] and value['files']==witness
        and witness==tree_manifest(destination),'BLOCKED_COMPONENT_DRIFT')
    return destination


def private_write(path,value):
    path=lib.safe_path(path)
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    lib.require(len(raw)<=COMPONENT_LIMIT,'BLOCKED_COMPONENT_MANIFEST_SIZE')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb',closefd=False) as out:out.write(raw);out.flush();os.fsync(fd)
    finally:os.close(fd)


def bounded_probe(root):
    """16KiB, unique owned staging, targeted fsync; never global sync/fsck."""
    lib.assert_admitted()
    directory=Path(tempfile.mkdtemp(prefix='.probe-',dir=root/'downloads'))
    payload=os.urandom(16384);path=directory/'probe.bin'
    try:
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            before=os.fstat(fd);view=memoryview(payload)
            while view:view=view[os.write(fd,view):]
            os.fsync(fd);os.lseek(fd,0,os.SEEK_SET)
            actual=b''
            while len(actual)<len(payload):
                chunk=os.read(fd,len(payload)-len(actual))
                if not chunk:break
                actual+=chunk
            after=os.fstat(fd)
            lib.require((before.st_dev,before.st_ino)==(after.st_dev,after.st_ino)
                and actual==payload,'BLOCKED_PROBE_READBACK')
        finally:os.close(fd)
        dfd=os.open(directory,os.O_DIRECTORY|os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
        lib.assert_admitted()
        result={'schema':'aioa.android.bounded-storage-probe.v1','status':'PASS_BOUNDED_PROBE_ONLY',
            'bytes':16384,'sha256':lib.hashlib.sha256(payload).hexdigest(),'at':lib.utc(),'global_storage_certification':False}
        private_write(root/'reports'/('probe-'+uuid.uuid4().hex+'.json'),result)
        # Only this process's newly created file/directory, after identity check.
        info=path.lstat();lib.require((info.st_dev,info.st_ino)==(before.st_dev,before.st_ino),'BLOCKED_PROBE_RACE')
        path.unlink();directory.rmdir()
        return result
    except OSError:raise lib.Blocked('BLOCKED_PROBE_IO_STOP') from None


def install_component(artifact,root):
    lib.assert_admitted();lib.validate_artifact(artifact)
    destination=lib.safe_path(root/artifact['destination'])
    if destination.exists():return component_check(artifact,root)
    archive=lib.download(artifact,root/'downloads')
    lib.assert_admitted()
    stage=Path(tempfile.mkdtemp(prefix='.stage-',dir=root/'downloads'))
    extracted=lib.extract(archive,stage/'unpacked')
    private_write(extracted/COMPONENT,{'schema':'aioa.android.component.v1','id':artifact['id'],
        'version':artifact['version'],'archive_sha256':artifact['sha256'],'source_url':artifact['url'],
        'license':artifact['license'],'acquired_at':lib.utc(),'files':tree_manifest(extracted),
        'archive_transform':'internal TAR file aliases materialized; no symlinks'})
    component_check(artifact,root,directory=extracted)
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    lib.assert_admitted();lib.promote(extracted,destination)
    # Staging is deliberately retained on failure; never remove unknown trees.
    return component_check(artifact,root)


def scoped_environment(root=lib.ROOT):
    return {'PATH':str(root/'jdk-17/bin')+':/usr/bin:/bin','LANG':'C.UTF-8',
        'JAVA_HOME':str(root/'jdk-17'),'ANDROID_HOME':str(root/'sdk'),'ANDROID_SDK_ROOT':str(root/'sdk'),
        'ANDROID_USER_HOME':str(root/'sdk/.user'),'GRADLE_USER_HOME':str(root/'gradle-cache'),
        'TMPDIR':str(root/'downloads/.tmp'),
        'JDK_JAVA_OPTIONS':'-Xmx128m -Duser.home='+str(root/'reports/java-user')
            +' -Djava.io.tmpdir='+str(root/'downloads/.tmp')}


def verify_versions(root=lib.ROOT):
    value=catalog()
    for artifact in value['artifacts']:component_check(artifact,root)
    lib.require(lib.license_observed(root/'sdk'),'BLOCKED_LICENSE')
    java=subprocess.run([str(root/'jdk-17/bin/java'),'-version'],capture_output=True,text=True,
        timeout=10,env=scoped_environment(root))
    lib.require(java.returncode==0 and '17.' in java.stdout+java.stderr,'BLOCKED_JDK_VERSION')
    manager=root/'sdk/cmdline-tools'/value['versions']['cmdline_tools']/'bin/sdkmanager'
    version=subprocess.run([str(manager),'--version'],stdin=subprocess.DEVNULL,capture_output=True,text=True,
        timeout=10,env=scoped_environment(root))
    lib.require(version.returncode==0 and version.stdout.strip().startswith(value['versions']['cmdline_tools']),'BLOCKED_SDKMANAGER_VERSION')
    for name,revision in [('platforms/android-36','2'),('build-tools/35.0.0','35.0.0')]:
        props=(root/'sdk'/name/'source.properties').read_text()
        lib.require('Pkg.Revision='+revision in props.replace(' ',''),'BLOCKED_SDK_PACKAGE_VERSION')
    return {'status':'TOOLCHAIN_INSTALLED_VERIFIED','versions':value['versions'],'scope':'CURRENT_LOCAL_PROFILE_ONLY'}


def perform_install(expected_source):
    lib.source_check(expected_source);lib.assert_admitted()
    root=lib.safe_path(lib.ROOT)
    marker=root/'.aioa-toolchain-root.json'
    if root.exists():
        lib.require(lib.private_json(marker).get('schema')=='aioa.android.toolchain-root.v1','BLOCKED_UNKNOWN_TOOLCHAIN_ROOT')
    else:
        root.mkdir(mode=0o700)
        private_write(marker,{'schema':'aioa.android.toolchain-root.v1','uuid':lib.UUID,'created_at':lib.utc()})
    lock=os.open(root/'toolchain.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise lib.Blocked('BLOCKED_OTHER_TOOLCHAIN_WRITER') from None
        for name in ('downloads','downloads/.tmp','reports','sdk','gradle-cache','build-output'):
            lib.safe_path(root/name).mkdir(mode=0o700,parents=True,exist_ok=True)
        bounded_probe(root)
        artifacts=catalog()['artifacts']
        for artifact in artifacts[:2]:
            install_component(artifact,root)
            if artifact['id']=='gradle':seed_wrapper_cache(artifact,root)
        lib.require(lib.license_observed(root/'sdk'),'BLOCKED_LICENSE')
        # Validate all SDK publication pins before any SDK archive acquisition.
        for artifact in artifacts[2:]:lib.validate_artifact(artifact)
        for artifact in artifacts[2:]:install_component(artifact,root)
        lib.source_check(expected_source)
        return verify_versions(root)
    finally:os.close(lock)


def install(*,dry_run,expected_source):
    gate=lib.admission()
    if not gate['may_stage']:return {'status':'BLOCKED_STORAGE_TOOLCHAIN','storage':gate,'downloads':0}
    lib.source_check(expected_source)
    if dry_run:return {'status':'DRY_RUN_NO_EFFECTS','storage':gate,**plan()}
    return perform_install(expected_source)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--source-sha',required=True)
    args=parser.parse_args()
    try:result=install(dry_run=args.dry_run,expected_source=args.source_sha)
    except lib.Blocked as e:result={'status':e.code,'automatic_retry':False}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):result={'status':'BLOCKED_IO_OR_INPUT','automatic_retry':False}
    print(json.dumps(result,sort_keys=True,indent=2))
    return 0 if result['status'] in ('DRY_RUN_NO_EFFECTS','TOOLCHAIN_INSTALLED_VERIFIED') else 2


if __name__=='__main__':raise SystemExit(main())
