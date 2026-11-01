"""Fail-closed storage and verified archive primitives. All probes are read-only.

The qualification publisher is external to these tools. Nothing here creates a
PASS report, a trust pin, a license acceptance or an AIOA owner credential.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import zipfile

REPO = Path(__file__).resolve().parents[2]
MOUNT = Path('/media/l/LSC_DATA3')
ROOT = MOUNT/'AIOA_ANDROID_TOOLCHAIN'
UUID = '1c748500-8e12-4e23-80be-115ce7f3937a'
DEVICE = '/dev/sda1'
GIB = 1024**3
PIN = Path('/home/l/.local/state/aioa-storage/LSC_DATA3-toolchain-qualification-pin.json')
QUALIFICATION_ROOT = Path('/home/l/AIOA_RECOVERY_EVIDENCE/storage')
SHA = re.compile(r'[0-9a-f]{64}\Z')
SDK_LICENSES = frozenset({'8933bad161af4178b1185d1a37fbf41ea5269c55',
    'd56f5187479451eabf01fb78af6dfcb131a6481e','24333f8a63b6825ea9c5514f83c2829b004d1fee'})


class Blocked(RuntimeError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)


def require(ok, code):
    if not ok:raise Blocked(code)


def sha(path):
    result=hashlib.sha256()
    with open(path,'rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):result.update(data)
    return result.hexdigest()


def safe_path(path):
    path=Path(path).absolute()
    require('..' not in path.parts,'BLOCKED_PATH')
    for p in [path,*path.parents]:require(not p.is_symlink(),'BLOCKED_SYMLINK')
    return path


def private_bytes(path,*,max_bytes=65536):
    require(type(max_bytes) is int and 0<max_bytes<=16*1024*1024,'BLOCKED_EVIDENCE_LIMIT')
    path=safe_path(path);info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
            and not info.st_mode & 0o077 and info.st_size<=max_bytes,'BLOCKED_PRIVATE_EVIDENCE')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        actual=os.fstat(fd)
        require((actual.st_dev,actual.st_ino,actual.st_size)==(info.st_dev,info.st_ino,info.st_size),'BLOCKED_EVIDENCE_RACE')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(max_bytes+1)
        after=os.fstat(fd)
        require(len(raw)<=max_bytes and (after.st_size,after.st_mtime_ns)==(actual.st_size,actual.st_mtime_ns),'BLOCKED_EVIDENCE_RACE')
        return raw
    finally:os.close(fd)


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'BLOCKED_DUPLICATE_JSON')
            result[key]=value
        return result
    def invalid(_):raise Blocked('BLOCKED_NONFINITE_JSON')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    except (ValueError,UnicodeError):raise Blocked('BLOCKED_JSON') from None


def private_json(path,*,max_bytes=65536):return strict_json(private_bytes(path,max_bytes=max_bytes))


def git(*args):
    r=subprocess.run(['git','--no-optional-locks','-C',str(REPO),*args],capture_output=True,text=True,timeout=8)
    require(r.returncode==0,'BLOCKED_SOURCE_GIT')
    return r.stdout.strip()


def source_check(expected):
    require(type(expected) is str and re.fullmatch(r'[0-9a-f]{40}',expected),'BLOCKED_SOURCE_SHA')
    require(git('rev-parse','HEAD')==expected,'BLOCKED_SOURCE_SHA')
    require(not git('status','--porcelain','-uall'),'BLOCKED_DIRTY_SOURCE')
    require(not git('ls-files','--others','--ignored','--exclude-standard','--','clients/android'),
            'BLOCKED_IGNORED_ANDROID_INPUT')
    path=REPO/'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json'
    value=json.loads(path.read_text())
    for row in value['files']:
        name=row['path']
        require(name.startswith('clients/android/') and '..' not in Path(name).parts,'BLOCKED_INPUT_PATH')
        p=safe_path(REPO/name)
        require(sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
                and bool(p.stat().st_mode & 0o111)==row['executable'],'BLOCKED_INPUT_DRIFT')
    return value


def gradle_configuration_check(home):
    home=safe_path(home)
    for name in ('gradle.properties','init.gradle','init.gradle.kts'):
        require(not safe_path(home/name).exists(),'BLOCKED_GRADLE_OVERRIDE')
    init=safe_path(home/'init.d')
    require(not init.exists() or (init.is_dir() and not any(init.iterdir())),'BLOCKED_GRADLE_OVERRIDE')


def storage_decision(facts, qualification, *, now=None):
    now=time.time() if now is None else now
    errors=[]
    expected={'target':str(MOUNT),'device':DEVICE,'uuid':UUID,'fstype':'ext4'}
    if any(facts.get(k)!=v for k,v in expected.items()):errors.append('MOUNT_IDENTITY_MISMATCH')
    options=facts.get('options',[])
    if 'rw' not in options or any(x in options for x in ('ro','noexec')):errors.append('MOUNT_OPTIONS')
    if facts.get('path_safe') is not True or facts.get('destination_writable') is not True:errors.append('PATH_OR_OWNERSHIP')
    if facts.get('external_free',0) < (25+12)*GIB:errors.append('EXTERNAL_RESERVE')
    if facts.get('root_free',0) < 10*GIB:errors.append('ROOT_RESERVE')
    if facts.get('kernel_readable') is not True or facts.get('io_errors')!=0 or facts.get('ext4_errors')!=0:errors.append('IO_HEALTH_UNKNOWN_OR_FAILED')
    q=qualification or {}
    exact=(q.get('schema')=='aioa.storage.independent-qualification.v1'
        and q.get('publisher')=='AIOA_WD_WATCH' and q.get('status')=='PASS'
        and q.get('report_pin_verified') is True
        and q.get('prior_faults')=='RESOLVED' and q.get('smart')=='PASS' and q.get('usb')=='PASS'
        and all(q.get(k)==facts.get(k) for k in ('target','device','uuid','mount_id'))
        and type(q.get('observed_at')) is int and type(q.get('expires_at')) is int
        and q['observed_at']<=now<q['expires_at'] and 0<q['expires_at']-q['observed_at']<=3600)
    if not exact:errors.append('INDEPENDENT_CURRENT_QUALIFICATION_MISSING_OR_INVALID')
    return {'status':'BLOCKED_STORAGE_TOOLCHAIN' if errors else 'PRECHECK_PASS_PROBE_REQUIRED',
            'reasons':errors,'may_stage':not errors,'storage_certified':False,'external_write_bytes':0}


def load_qualification():
    """Read only an independently provisioned report and native operator pin.

No flag/env can mint this evidence. A syntactically valid report is insufficient:
the pin must have been independently provisioned from the authentic publisher.
The current host has no such source. See the G1 handoff before provisioning.
"""
    try:
        pin=private_json(PIN)
        require(set(pin)=={'schema','publisher','report_path','report_sha256'}
            and pin['schema']=='aioa.storage.report-pin.v1' and pin['publisher']=='AIOA_WD_WATCH'
            and SHA.fullmatch(pin['report_sha256']),'BLOCKED_QUALIFICATION_PIN')
        report=safe_path(pin['report_path'])
        require(report.is_relative_to(QUALIFICATION_ROOT),'BLOCKED_QUALIFICATION_SOURCE')
        raw=private_bytes(report);value=strict_json(raw)
        require(hashlib.sha256(raw).hexdigest()==pin['report_sha256'],'BLOCKED_QUALIFICATION_DRIFT')
        require('report_pin_verified' not in value,'BLOCKED_SELF_APPROVED_REPORT')
        value['report_pin_verified']=True
        return value
    except (Blocked,OSError,ValueError,TypeError,KeyError):return None


def probe_storage():
    facts={'root_free':shutil.disk_usage('/').free,'external_free':0,'path_safe':False,
           'destination_writable':False,'kernel_readable':False,'io_errors':None,'ext4_errors':None}
    try:
        mount=json.loads(subprocess.run(['findmnt','--json','--target',str(MOUNT),
            '--output','TARGET,SOURCE,FSTYPE,OPTIONS,UUID,ID'],capture_output=True,text=True,timeout=5,check=True).stdout)['filesystems'][0]
        facts.update(target=mount['target'],device=mount['source'],fstype=mount['fstype'],
            options=mount['options'].split(','),uuid=mount.get('uuid'),mount_id=str(mount.get('id')))
        safe_path(MOUNT);safe_path(ROOT)
        info=(ROOT if ROOT.exists() else MOUNT).lstat()
        facts['path_safe']=True
        facts['destination_writable']=info.st_uid==os.getuid() and stat.S_ISDIR(info.st_mode) and os.access(ROOT if ROOT.exists() else MOUNT,os.W_OK)
        facts['external_free']=shutil.disk_usage(MOUNT).free
        count=Path('/sys/fs/ext4/sda1/errors_count')
        if count.is_file():facts['ext4_errors']=int(count.read_text().strip())
        r=subprocess.run(['journalctl','-k','--since','48 hours ago','--no-pager','-o','cat'],capture_output=True,text=True,timeout=8)
        require(len(r.stdout)<=1024*1024,'BLOCKED_KERNEL_OUTPUT')
        facts['kernel_readable']=r.returncode==0 and bool(r.stdout.strip()) and 'No entries' not in r.stdout
        lines=[s.lower() for s in r.stdout.splitlines() if any(t in s.lower() for t in ('sda','usb','ext4'))]
        facts['io_errors']=sum(any(w in s for w in ('i/o error','usb disconnect','reset high-speed','reset superspeed','ext4-fs error','remounting filesystem read-only','uas_eh')) for s in lines)
    except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError,Blocked):pass
    return facts


def admission():
    return storage_decision(probe_storage(),load_qualification())


def assert_admitted():
    result=admission()
    require(result['may_stage'],'BLOCKED_STORAGE_TOOLCHAIN')
    return result


def license_observed(sdk):
    """Observation of SDK manager's existing record, NOT automatic acceptance."""
    try:
        p=safe_path(Path(sdk)/'licenses/android-sdk-license')
        require(p.is_file() and p.stat().st_size<=16384,'BLOCKED_LICENSE')
        return bool(set(p.read_text().splitlines()) & SDK_LICENSES)
    except (OSError,ValueError,Blocked):return False


def validate_url(url):
    parsed=urlsplit(url)
    require(parsed.scheme=='https' and parsed.username is None and parsed.password is None
        and parsed.port in (None,443) and not parsed.fragment,'BLOCKED_ORIGIN')
    allowed={'dl.google.com','services.gradle.org','downloads.gradle.org','github.com','release-assets.githubusercontent.com'}
    require(parsed.hostname in allowed,'BLOCKED_ORIGIN')
    if parsed.hostname=='github.com':
        require(parsed.path.startswith(('/adoptium/temurin17-binaries/releases/','/gradle/gradle-distributions/releases/')),'BLOCKED_ORIGIN')


def validate_artifact(value):
    require(type(value.get('sha256')) is str and SHA.fullmatch(value['sha256']),'BLOCKED_PUBLISHED_SHA256')
    require(type(value.get('size')) is int and 0<value['size']<=512*1024*1024,'BLOCKED_DOWNLOAD_SIZE')
    validate_url(value['url'])
    if 'filename' in value:require(re.fullmatch(r'[A-Za-z0-9_.+-]{1,160}',value['filename']),'BLOCKED_FILENAME')


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _request(url,offset):
    headers={'User-Agent':'AIOA-verified-toolchain/1'}
    if offset:headers['Range']='bytes='+str(offset)+'-'
    return urllib.request.build_opener(_Redirect()).open(urllib.request.Request(url,headers=headers),timeout=20)


def download(artifact,cache,*,request=_request):
    validate_artifact(artifact)
    cache=safe_path(cache);cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    final=safe_path(cache/artifact['filename']);part=safe_path(cache/(artifact['filename']+'.part'))
    if final.exists():
        require(stat.S_ISREG(final.lstat().st_mode) and final.stat().st_nlink==1 and sha(final)==artifact['sha256'],'BLOCKED_CACHE_DRIFT')
        return final
    offset=0
    if part.exists():
        require(stat.S_ISREG(part.lstat().st_mode) and part.stat().st_nlink==1,'BLOCKED_PARTIAL_TYPE')
        offset=part.stat().st_size
        require(offset<=artifact['size'],'BLOCKED_PARTIAL_SIZE')
    if offset<artifact['size']:
        try:
            with request(artifact['url'],offset) as response:
                validate_url(response.geturl())
                require(response.status==(206 if offset else 200),'BLOCKED_DOWNLOAD_STATUS')
                if offset:require(response.headers.get('Content-Range')==f"bytes {offset}-{artifact['size']-1}/{artifact['size']}",'BLOCKED_RESUME_RANGE')
                flags=os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC
                fd=os.open(part,flags,0o600)
                try:
                    require(os.fstat(fd).st_size==offset,'BLOCKED_PARTIAL_RACE')
                    os.lseek(fd,offset,os.SEEK_SET);count=offset;deadline=time.monotonic()+600
                    while True:
                        require(time.monotonic()<deadline,'BLOCKED_DOWNLOAD_TIMEOUT')
                        data=response.read(1024*1024)
                        if not data:break
                        count+=len(data);require(count<=artifact['size'],'BLOCKED_DOWNLOAD_SIZE')
                        view=memoryview(data)
                        while view:view=view[os.write(fd,view):]
                    os.fsync(fd)
                finally:os.close(fd)
        except (OSError,urllib.error.URLError,TimeoutError):raise Blocked('BLOCKED_NETWORK') from None
    require(part.stat().st_size==artifact['size'] and sha(part)==artifact['sha256'],'BLOCKED_CHECKSUM')
    promote(part,final)
    return final


def _member(name):
    require(type(name) is str and name and '\\' not in name and '\x00' not in name,'BLOCKED_ARCHIVE_PATH')
    p=PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and p.parts[0] not in ('.',''),'BLOCKED_ARCHIVE_PATH')
    return p


@contextmanager
def _archive(archive,max_bytes):
    """One shared validation/materialization plan for extraction and inventory."""
    zipped=zipfile.is_zipfile(archive)
    if hasattr(archive,'seek'):archive.seek(0)
    stream=zipfile.ZipFile(archive) if zipped else tarfile.open(
        fileobj=archive if hasattr(archive,'read') else None,
        name=None if hasattr(archive,'read') else archive,mode='r:*')
    with stream:
        members=stream.infolist() if zipped else stream.getmembers()
        paths=[_member(m.filename if zipped else m.name) for m in members]
        require(len(members)<=50000,'BLOCKED_ARCHIVE_SIZE')
        require(len({p.parts[0] for p in paths})==1,'BLOCKED_ARCHIVE_ROOT')
        require(len(set(str(p) for p in paths))==len(paths),'BLOCKED_ARCHIVE_DUPLICATE')
        by_name={str(p):m for p,m in zip(paths,members)};files=[];directories=[]
        for member,path in zip(members,paths):
            source=member
            if zipped:
                require(stat.S_IFMT(member.external_attr>>16) in (0,stat.S_IFREG,stat.S_IFDIR),'BLOCKED_ARCHIVE_LINK')
                directory=member.is_dir();size=member.file_size;mode=member.external_attr>>16
            else:
                require(member.isfile() or member.isdir() or member.issym() or member.islnk(),'BLOCKED_ARCHIVE_TYPE')
                directory=member.isdir()
                if member.issym() or member.islnk():
                    target=_member(posixpath.normpath(posixpath.join(posixpath.dirname(str(path)),member.linkname)
                        if member.issym() else member.linkname))
                    require(target.parts[0]==path.parts[0] and str(target) in by_name
                        and by_name[str(target)].isfile(),'BLOCKED_ARCHIVE_LINK')
                    require(not any(str(q).startswith(str(path)+'/') for q in paths),'BLOCKED_ARCHIVE_LINK_PARENT')
                    source=by_name[str(target)]
                size=source.size;mode=source.mode
            if directory:directories.append(path)
            else:
                require(len(path.parts)>1 and size>=0,'BLOCKED_ARCHIVE_ROOT')
                files.append((path,source,size,bool(mode&0o111)))
        require(sum(row[2] for row in files)<=max_bytes,'BLOCKED_ARCHIVE_SIZE')
        yield stream,zipped,files,directories


def extract(archive,stage,*,max_bytes=4*GIB):
    """No links/devices/traversal; internal TAR file aliases become plain files."""
    archive=safe_path(archive);stage=safe_path(stage)
    require(not stage.exists(),'BLOCKED_STAGE_EXISTS')
    with _archive(archive,max_bytes) as (stream,zipped,files,directories):
        stage.mkdir(mode=0o700)
        for path in directories:(stage/str(path)).mkdir(parents=True,exist_ok=True)
        for path,member,size,executable in files:
            target=stage/str(path);target.parent.mkdir(parents=True,exist_ok=True)
            with (stream.open(member) if zipped else stream.extractfile(member)) as source,open(target,'xb') as dest:
                shutil.copyfileobj(source,dest,1024*1024)
            require(target.stat().st_size==size,'BLOCKED_ARCHIVE_TRUNCATED')
            target.chmod(0o755 if executable else 0o644)
    children=list(stage.iterdir());require(len(children)==1 and children[0].is_dir(),'BLOCKED_ARCHIVE_ROOT')
    return children[0]


def archive_inventory(archive,*,expected_sha256=None,expected_size=None):
    archive=safe_path(archive)
    require(archive.is_file(),'BLOCKED_ARCHIVE_WITNESS_MISSING')
    fd=os.open(archive,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd,'rb') as raw:
        before=os.fstat(raw.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1,'BLOCKED_ARCHIVE_WITNESS')
        if expected_size is not None:require(before.st_size==expected_size,'BLOCKED_ARCHIVE_WITNESS')
        def verify_digest():
            raw.seek(0);digest=hashlib.sha256()
            for data in iter(lambda:raw.read(1024*1024),b''):digest.update(data)
            if expected_sha256 is not None:require(digest.hexdigest()==expected_sha256,'BLOCKED_ARCHIVE_WITNESS')
            raw.seek(0)
        verify_digest();rows=[]
        with _archive(raw,4*GIB) as (stream,zipped,files,_):
            for path,member,size,executable in files:
                digest=hashlib.sha256();count=0
                with (stream.open(member) if zipped else stream.extractfile(member)) as source:
                    for data in iter(lambda:source.read(1024*1024),b''):digest.update(data);count+=len(data)
                require(count==size,'BLOCKED_ARCHIVE_TRUNCATED')
                rows.append({'path':PurePosixPath(*path.parts[1:]).as_posix(),'sha256':digest.hexdigest(),
                    'bytes':count,'executable':executable})
        verify_digest();after=os.fstat(raw.fileno())
        require((before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
            (after.st_size,after.st_mtime_ns,after.st_ctime_ns),'BLOCKED_ARCHIVE_WITNESS_CHANGED')
        return sorted(rows,key=lambda row:row['path'])


def promote(stage,destination):
    stage=safe_path(stage);destination=safe_path(destination)
    # Linux atomic no-replace, including directories. No check/rename overwrite race.
    libc=ctypes.CDLL(None,use_errno=True)
    rename=getattr(libc,'renameat2',None)
    require(rename is not None,'BLOCKED_ATOMIC_PROMOTION_UNAVAILABLE')
    result=rename(-100,os.fsencode(stage),-100,os.fsencode(destination),1)
    if result:
        err=ctypes.get_errno()
        raise Blocked('BLOCKED_INSTALL_EXISTS' if err==errno.EEXIST else 'BLOCKED_PROMOTION_IO')
    fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:os.fsync(fd)
    finally:os.close(fd)


def utc():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
