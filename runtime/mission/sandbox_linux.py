"""Explicit trusted Linux sandbox broker. Imports and default routes never execute tools.

Only Core's live START branch supplies the release callback. Typed requests and
on-disk receipts are bindings/evidence, never replayable execution authority.
"""
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime,timezone
import array,errno,hashlib,json,os,select,socket,stat,struct,subprocess,sys,tempfile,uuid
from runtime.memory_patch.contracts.serialization import canonical_sha256,canonical_json_bytes
from runtime.mission.sandbox_contracts import SandboxDispatchRequest,SandboxOperation,RESOURCE_CEILINGS,SandboxRecipe,SandboxRegistry
from runtime.mission.warrant import require

def now():return datetime.now(timezone.utc).isoformat()
def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:os.fsync(fd)
    finally:os.close(fd)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def exact_cgroup(unit):
    return '0::/user.slice/user-%d.slice/user@%d.service/app.slice/%s/work'%(os.getuid(),os.getuid(),unit)
def mountid(fd):
    for line in Path('/proc/self/fdinfo/'+str(fd)).read_text().splitlines():
        if line.startswith('mnt_id:'):return int(line.split(':')[1])
    raise ValueError('MISSING_MOUNT_ID')
def populated(fd):
    os.lseek(fd,0,os.SEEK_SET)
    values=dict(line.split() for line in os.read(fd,4096).decode().splitlines())
    require(values.get('populated') in ('0','1'),'INVALID_CGROUP_EVENTS')
    return values['populated']
def command_result(argv):
    try:
        r=subprocess.run(argv,capture_output=True,text=True,timeout=4)
        return {'argv':argv,'exit_code':r.returncode,'stdout':r.stdout[:2048],'stderr':r.stderr[:1024]}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {'argv':argv,'error':type(exc).__name__,'errno':getattr(exc,'errno',None)}
def bounded_line(stream,seconds=8):
    data=bytearray()
    import time
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline and len(data)<65536:
        ready,_,_=select.select([stream.fileno()],[],[],max(0,deadline-time.monotonic()))
        if not ready:break
        byte=os.read(stream.fileno(),1)
        if not byte:break
        data.extend(byte)
        if byte==b'\n':
            value=json.loads(data)
            require(value.get('stage')!='CHILD_FAILED','TRUSTED_SUPERVISOR_FAILED:'+str(value)[:1024])
            return value
    raise ValueError('BOUNDED_PROTOCOL_LINE_MISSING')

def build_filter(*,final):
    # Linux x86_64 only. Each filter rejects other ABIs and x32 first.
    rows=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(0x06,0,0,0x80000000),
          (0x20,0,0,0),(0x35,0,1,0x40000000),(0x06,0,0,0x80000000)]
    deny={101,133,259,320,428,429,430,431,432,433,165,166,167,168,169,170,171,172,173,174,175,176,178,179,180,181,182,183,184,185,
          246,248,249,250,272,298,300,303,304,308,310,311,313,317,321,323,425,426,427,438,442}
    if final:deny.update({41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,288,299,307})
    for number in sorted(deny):rows.extend([(0x15,0,1,number),(0x06,0,0,0x00050001)])
    rows.extend([(0x15,0,1,435),(0x06,0,0,0x00050026)]) # clone3 ENOSYS
    # Legacy clone: forbid high bits and all CLONE_NEW flags, including NEWTIME.
    rows.extend([(0x15,0,8,56),(0x20,0,0,20),(0x15,1,0,0),(0x06,0,0,0x00050001),
                 (0x20,0,0,16),(0x54,0,0,0x7e020080),(0x15,1,0,0),
                 (0x06,0,0,0x00050001),(0x06,0,0,0x7fff0000),(0x06,0,0,0x7fff0000)])
    return b''.join(struct.pack('<HBBI',*row) for row in rows)

@dataclass(frozen=True,slots=True)
class TrustedSandboxConfig:
    root:Path
    profile_bytes:bytes
    profile_digest:str
    registry:SandboxRegistry
    inputs_bytes:bytes
    runtime_bytes:bytes

    def profile(self):return json.loads(self.profile_bytes)
    def inputs(self):return json.loads(self.inputs_bytes)
    def runtime(self):return json.loads(self.runtime_bytes)

def prepare_linux_sandbox(root,runtime_manifest,*,workspace,recipes):
    """Explicit operator preparation: compile packaged trusted C, pin runtime/inputs.

    recipes is a trusted mapping id -> {files:{name:bytes},expected:{artifact:bytes}}.
    Nothing in a proposal can supply this configuration or add a recipe.
    """
    require(isinstance(root,Path) and type(runtime_manifest) is dict and type(recipes) is dict
            and 0<len(recipes)<=32 and sys.platform=='linux' and os.uname().machine=='x86_64'
            and not sys.flags.optimize,'TRUSTED_SANDBOX_CONFIGURATION_REQUIRED')
    root=root.absolute();root.mkdir(mode=0o700,parents=True,exist_ok=False)
    native=Path(__file__).parent/'native';pins={};runtime={}
    for name in ('worker_gate','bootstrap'):
        source=native/(name+'.c');destination=root/name
        result=subprocess.run(['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror','-fstack-protector-strong',
            '-D_FORTIFY_SOURCE=2','-Wl,-z,relro,-z,now',str(source),'-o',str(destination)],
            capture_output=True,timeout=30)
        require(result.returncode==0,'TRUSTED_SANDBOX_COMPILATION_FAILED')
        destination.chmod(0o500);pins[name]={'source_sha256':sha(source),'binary_sha256':sha(destination)}
    for name,final in [('setup_filter',False),('final_filter',True)]:
        path=root/(name+'.bpf');path.write_bytes(build_filter(final=final));path.chmod(0o400);pins[name]=sha(path)
    for target,entry in runtime_manifest.items():
        require(type(target) is str and target.startswith(('/usr/lib/python3.12/','/usr/bin/python3.12','/lib/','/lib64/'))
                and '..' not in target.split('/'),'UNAPPROVED_RUNTIME_PATH')
        path=Path(entry['snapshot']);metadata=path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_size==entry['bytes'] and sha(path)==entry['sha256'],
                'PINNED_RUNTIME_CHANGED')
        runtime[target]={**entry,'mode':stat.S_IMODE(metadata.st_mode)}
    require('/usr/bin/python3.12' in runtime,'PINNED_RUNTIME_REQUIRED')
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent','TMPDIR':'/tmp'}
    profile={'schema':'aioa.linux-sandbox-profile.v1','platform':'linux-x86_64','runtime':{key:{'sha256':entry['sha256'],'bytes':entry['bytes'],'mode':entry['mode']} for key,entry in runtime.items()},
        'native':pins,'bwrap_sha256':sha('/usr/bin/bwrap'),'worker_sha256':sha(Path(__file__).with_name('sandbox_worker.py')),
        'backend_sha256':sha(__file__),'resources':dict(RESOURCE_CEILINGS),'env':env,'network':'OFF','namespaces':7,
        'retained_python_extensions':'manifest exact; includes host test and Tk extension closure'}
    digest=canonical_sha256(profile);env_digest=canonical_sha256(env);inputs={};approved=[]
    for identity,spec in recipes.items():
        require(type(spec) is dict and set(spec)=={'files','expected'} and type(spec['files']) is dict
                and 'recipe.py' in spec['files'] and 0<len(spec['files'])<=16 and type(spec['expected']) is dict
                and 0<len(spec['expected'])<=8,'INVALID_TRUSTED_RECIPE')
        directory=root/('input-'+str(len(inputs)));directory.mkdir(mode=0o700);files={};manifest={}
        for name,data in spec['files'].items():
            require(type(name) is str and name.isascii() and '/' not in name and name not in ('.','..')
                    and type(data) is bytes and len(data)<=1048576,'INVALID_TRUSTED_INPUT')
            destination=directory/name;destination.write_bytes(data);destination.chmod(0o400)
            files[name]=str(destination);manifest[name]=hashlib.sha256(data).hexdigest()
        expected={}
        for name,data in spec['expected'].items():
            require(type(name) is str and name.isascii() and '/' not in name and name not in ('.','..')
                    and type(data) is bytes and len(data)<=1048576,'INVALID_EXPECTED_ARTIFACT')
            expected[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        input_digest=canonical_sha256({'files':manifest,'expected':expected})
        inputs[identity]={'files':files,'manifest':manifest,'expected':expected,'digest':input_digest}
        approved.append(SandboxRecipe(identity,'trusted-input-'+input_digest[:24],digest,input_digest,env_digest))
    return TrustedSandboxConfig(root,canonical_json_bytes(profile),digest,SandboxRegistry(workspace,tuple(approved)),json.dumps(inputs,sort_keys=True,separators=(',',':')).encode(),json.dumps(runtime,sort_keys=True,separators=(',',':')).encode())

class LinuxSandboxBroker:
    def __init__(self,config=None):
        require(type(config) is TrustedSandboxConfig and not sys.flags.optimize,'TRUSTED_SANDBOX_CONFIGURATION_REQUIRED')
        require(config.profile_digest==canonical_sha256(config.profile()),'PINNED_PROFILE_CHANGED')
        self.config=config

    def __call__(self,request):
        raise ValueError('LIVE_CORE_GATE_REQUIRED')

    def dispatch(self,request,release_check):
        require(type(request) is SandboxDispatchRequest and callable(release_check),'LIVE_CORE_GATE_REQUIRED')
        self.config.registry.validate(SandboxOperation(request.operation_bytes).to_dict())
        p=self.config.profile();inputs=self.config.inputs()[json.loads(request.operation_bytes)['payload']['recipe_id']]
        require(canonical_sha256(p)==self.config.profile_digest,'PINNED_PROFILE_CHANGED')
        for name,pin in p['native'].items():
            path=self.config.root/(name+('.bpf' if name.endswith('filter') else ''))
            expected=pin['binary_sha256'] if type(pin) is dict else pin
            require(sha(path)==expected,'PINNED_NATIVE_CHANGED')
        require(sha(__file__)==p['backend_sha256'] and sha('/usr/bin/bwrap')==p['bwrap_sha256']
                and sha(Path(__file__).with_name('sandbox_worker.py'))==p['worker_sha256'],'PINNED_BACKEND_CHANGED')
        require({key:{'sha256':entry['sha256'],'bytes':entry['bytes'],'mode':entry['mode']} for key,entry in self.config.runtime().items()}==p['runtime'],'PINNED_RUNTIME_CHANGED')
        for entry in self.config.runtime().values():require(sha(entry['snapshot'])==entry['sha256'] and stat.S_IMODE(Path(entry['snapshot']).lstat().st_mode)==entry['mode'],'PINNED_RUNTIME_CHANGED')
        for name,path in inputs['files'].items():require(sha(path)==inputs['manifest'][name],'PINNED_INPUT_CHANGED')
        release_check() # early check; independent second check immediately before project ACK
        run=self.config.root/('run-'+request.digest);run.mkdir(mode=0o700,exist_ok=False);sync_directory(self.config.root)
        worker_config={'runtime':self.config.runtime(),'inputs':inputs['files'],'limits':json.loads(request.operation_bytes)['payload'],
            'gate':str(self.config.root/'worker_gate'),'bootstrap':str(self.config.root/'bootstrap'),
            'setup_filter':str(self.config.root/'setup_filter.bpf'),'final_filter':str(self.config.root/'final_filter.bpf')}
        config_path=run/'worker.json';config_path.write_bytes(json.dumps(worker_config,sort_keys=True,separators=(',',':')).encode());config_path.chmod(0o400)
        return self._run(request,release_check,config_path,run,inputs)

    def _run(self,request,release_check,config_path,run,inputs):
        unit='aioa-sandbox-'+uuid.uuid4().hex+'.service';nonce=uuid.uuid4().hex
        receipt={'started_at':now(),'unit':unit,'status':'UNKNOWN','project_code_started':False,'operation_digest':request.operation_digest,'dispatch_digest':request.digest,'request':request.to_dict(),'warrant_digest':request.warrant_digest,'profile_digest':self.config.profile_digest,'stage':'PREPARED','observations':{},'cleanup':[]}
        proc=None;peer=None;listener=None;directory=None;peerpidfd=None;procdir=None;proof=None;work_events=None
        fds=[];private=Path(tempfile.mkdtemp(prefix='aioa-handoff-'));os.chmod(private,0o700);control=private/'control'
        try:
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.settimeout(5);listener.bind(str(control));os.chmod(control,0o600);listener.listen(1)
            argv=['/usr/bin/systemd-run','--user','--quiet','--wait','--pipe','--service-type=exec','--expand-environment=no','--unit='+unit]
            for prop in ['Delegate=yes','DelegateSubgroup=supervisor','Slice=app.slice','MemoryMax=536870912','MemorySwapMax=0','TasksMax=16','CPUQuota=100%','CPUQuotaPeriodSec=100ms','NoNewPrivileges=yes','LimitAS=536870912','LimitCPU=15','LimitFSIZE=8388608','LimitCORE=0','LimitNOFILE=64','RuntimeMaxSec=32s','TimeoutStopSec=2s','KillMode=control-group','UMask=0077']:argv+=['--property='+prop]
            argv+=['/usr/bin/env','-i','PATH=/usr/bin:/bin','LANG=C.UTF-8','/usr/bin/python3.12','-I','-S','-B',str(Path(__file__).with_name('sandbox_worker.py')),unit,str(control),nonce,str(config_path)]
            receipt['argv']=argv
            proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.PIPE)
            receipt['stage']='WAITING_FOR_TRUSTED_KEEPER'
            ready=bounded_line(proc.stdout)
            assert ready['stage']=='WORK_READY' and ready['before_exec_placement'] is True
            expected_path='/sys/fs/cgroup/'+exact_cgroup(unit).split('::',1)[1].lstrip('/')
            assert ready['work_cgroup']==expected_path
            work_events=os.open(expected_path+'/cgroup.events',os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
            assert populated(work_events)=='1'
            kernel_limits={name:Path(expected_path).parent.joinpath(name).read_text().strip()
                for name in ('memory.max','memory.swap.max','pids.max','cpu.max')}
            require(kernel_limits==ready['limits'],'KERNEL_LIMITS_MISMATCH')
            receipt['observations']['aggregate_kernel_limits']=kernel_limits
            receipt['observations']['worker_gate']=ready
            receipt['observations']['worker_events_fd_pinned_before_exec']=True
            proc.stdin.write(b'G');proc.stdin.flush()
            peer,_=listener.accept();peer.settimeout(3);listener.close();listener=None;control.unlink()
            receipt['stage']='PEER_KERNEL_IDENTITY'
            pid,uid,gid=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            assert pid>0 and uid==os.getuid() and gid==os.getgid()
            peerpidfd=struct.unpack('i',peer.getsockopt(socket.SOL_SOCKET,77,4))[0]
            os.set_inheritable(peerpidfd,False)
            assert not select.select([peerpidfd],[],[],0)[0]
            procdir=os.open('/proc/'+str(pid),os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC)
            cgfd=os.open('cgroup',os.O_RDONLY|os.O_CLOEXEC,dir_fd=procdir)
            try:cg=os.read(cgfd,4096).decode().strip()
            finally:os.close(cgfd)
            assert cg==exact_cgroup(unit)
            receipt['observations']['peer']={'pid':pid,'uid':uid,'gid':gid,'pidfd_pinned':True,'cgroup':cg}
            receipt['stage']='RECEIVE_EXACT_DIRECTORY_FD'
            payload,ancillary,flags,_=peer.recvmsg(33,socket.CMSG_SPACE(4),socket.MSG_CMSG_CLOEXEC)
            for level,kind,data in ancillary:
                if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
                    integers=array.array('i');integers.frombytes(data[:len(data)-len(data)%integers.itemsize]);fds.extend(integers)
            assert not flags&(socket.MSG_CTRUNC|socket.MSG_TRUNC) and payload==nonce.encode() and len(fds)==1 and len(ancillary)==1
            directory=fds[0];metadata=os.fstat(directory);vfs=os.fstatvfs(directory)
            assert stat.S_ISDIR(metadata.st_mode) and metadata.st_uid==os.getuid() and not os.get_inheritable(directory)
            assert vfs.f_blocks*vfs.f_frsize==8388608 and not vfs.f_flag&os.ST_RDONLY
            mid=mountid(directory)
            receipt['stage']='INDEPENDENT_PEER_MOUNTINFO'
            mfd=os.open('mountinfo',os.O_RDONLY|os.O_CLOEXEC,dir_fd=procdir)
            try:
                with os.fdopen(mfd) as stream:mountinfo=stream.read(1048576)
                require(len(mountinfo)<1048576,'MOUNTINFO_LIMIT_EXCEEDED')
            except BaseException:raise
            candidates=[]
            for line in mountinfo.splitlines():
                left,right=line.split(' - ',1);fields=left.split();kind=right.split()
                if fields[4]=='/artifacts':candidates.append((fields,kind))
            assert len(candidates)==1
            fields,kind=candidates[0]
            assert int(fields[0])==mid and fields[3]=='/' and kind[0]=='tmpfs' and 'rw' in fields[5].split(',')
            assert fields[2]==f'{os.major(metadata.st_dev)}:{os.minor(metadata.st_dev)}'
            receipt['observations']['artifact_mount']={'mount_id':mid,'mountinfo_fields':fields,'filesystem':kind,'tmpfs_bytes':vfs.f_blocks*vfs.f_frsize}
            receipt['stage']='INDEPENDENT_PROC_ROOT_ARTIFACT_OPEN'
            independent=os.open('root/artifacts',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC,dir_fd=procdir)
            try:
                other=os.fstat(independent)
                assert (metadata.st_dev,metadata.st_ino,mid)==(other.st_dev,other.st_ino,mountid(independent))
            finally:os.close(independent)
            receipt['stage']='INDEPENDENT_BOOTSTRAP_IDENTITY'
            exe=os.open('exe',os.O_RDONLY|os.O_CLOEXEC,dir_fd=procdir)
            with os.fdopen(exe,'rb') as stream:assert hashlib.sha256(stream.read(1048576)).hexdigest()==self.config.profile()['native']['bootstrap']['binary_sha256']
            assert not select.select([peerpidfd],[],[],0)[0]
            status=Path('/proc/'+str(pid)+'/status').read_text()
            values=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
            require(values['NoNewPrivs'].strip()=='1' and values['Seccomp'].strip()=='2'
                    and all(int(values[key].strip(),16)==0 for key in ('CapEff','CapPrm','CapBnd')),
                    'KERNEL_PRIVILEGES_MISMATCH')
            namespaces={name:{'host':os.readlink('/proc/self/ns/'+name),
                'worker':os.readlink('/proc/'+str(pid)+'/ns/'+name)}
                for name in ('user','mnt','pid','net','ipc','uts','cgroup')}
            require(all(entry['host']!=entry['worker'] for entry in namespaces.values()),'KERNEL_NAMESPACE_MISMATCH')
            receipt['observations']['namespaces']=namespaces
            receipt['observations']['privileges']={key:values[key].strip() for key in ('NoNewPrivs','Seccomp','CapEff','CapPrm','CapBnd')}
            mounts={}
            for line in mountinfo.splitlines():
                left,right=line.split(' - ',1);fields=left.split();mounts[fields[4]]={'options':fields[5].split(','),'kind':right.split()[0]}
            require('ro' in mounts['/']['options'] and 'ro' in mounts['/proc']['options'], 'KERNEL_ROOT_READONLY_REQUIRED')
            for target in self.config.profile()['runtime']:
                require('ro' in mounts[target]['options'],'KERNEL_RUNTIME_READONLY_REQUIRED')
            for name in inputs['files']:
                require('ro' in mounts['/inputs/'+name]['options'],'KERNEL_INPUT_READONLY_REQUIRED')
            scratch={}
            for target,key in [('work','work_bytes'),('tmp','tmp_bytes')]:
                scratch_fd=os.open('root/'+target,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC,dir_fd=procdir)
                try:
                    vfs=os.fstatvfs(scratch_fd);size=vfs.f_blocks*vfs.f_frsize
                    require(size==json.loads(request.operation_bytes)['payload'][key]
                            and not vfs.f_flag&os.ST_RDONLY and mounts['/'+target]['kind']=='tmpfs','KERNEL_SCRATCH_LIMIT_MISMATCH')
                    scratch[target]=size
                finally:os.close(scratch_fd)
            receipt['observations']['readonly_mounts_verified']=len(self.config.profile()['runtime'])+len(inputs['files'])+2
            receipt['observations']['scratch_tmpfs_bytes']=scratch
            release_check()
            peer.sendall(b'Y');receipt['project_code_started']=True;peer.close();peer=None
            receipt['stage']='FINAL_FILTER_AND_TEARDOWN'
            empty=bounded_line(proc.stdout,24)
            assert empty['stage']=='WORK_EMPTY' and empty['spawn_and_migration_sealed'] is True
            assert populated(work_events)=='0'
            receipt['observations']['worker_populated_zero_before_readback']=True
            receipt['observations']['worker_terminal']=empty
            receipt['stage']='PINNED_READBACK_AFTER_CHILD_EXIT'
            readback={}
            for name,expected in inputs['expected'].items():
                proof=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=directory)
                try:
                    metadata=os.fstat(proof)
                    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink==1 and metadata.st_size==expected['bytes'],
                            'INVALID_ARTIFACT_METADATA')
                    value=os.read(proof,expected['bytes']+1)
                    require(len(value)==expected['bytes'] and hashlib.sha256(value).hexdigest()==expected['sha256'],
                            'ARTIFACT_DIGEST_MISMATCH')
                    readback[name]={'sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value),'nofollow':True,'single_link':True}
                    destination=run/('artifact-'+name)
                    with destination.open('xb') as copied:
                        copied.write(value);copied.flush();os.fchmod(copied.fileno(),0o400);os.fsync(copied.fileno())
                    sync_directory(run)
                finally:os.close(proof);proof=None
            receipt['observations']['pinned_readback']=readback
            assert populated(work_events)=='0'
            receipt['observations']['worker_populated_zero_after_readback']=True
            proc.stdin.write(b'R');proc.stdin.flush()
            out,err=proc.communicate(timeout=4)
            receipt.update(exit_code=proc.returncode,stdout=out[:8192].decode(errors='replace'),stderr=err[:4096].decode(errors='replace'))
            assert proc.returncode==0
            require(empty['child_exit_code']==0 and empty['termination_reason']=='EXITED','SANDBOX_UNSUCCESSFUL')
            receipt['status']='READBACK_VERIFIED'
        except Exception as exc:
            receipt['error']={'type':type(exc).__name__,'errno':getattr(exc,'errno',None),'name':errno.errorcode.get(getattr(exc,'errno',None)),'message':str(exc)[:512]}
        finally:
            def guarded_cleanup(stage,callback):
                try:callback()
                except Exception as exc:receipt['cleanup'].append({'stage':stage,'error':type(exc).__name__,'errno':getattr(exc,'errno',None)})
            if peer is not None:
                try:peer.sendall(b'N')
                except OSError:pass
                guarded_cleanup('PEER_CLOSE',peer.close)
            if listener is not None:guarded_cleanup('LISTENER_CLOSE',listener.close)
            receipt['cleanup'].append(command_result(['/usr/bin/systemctl','--user','stop',unit]))
            if proc is not None:
                def reap_owned():
                    try:out,err=proc.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill();out,err=proc.communicate(timeout=3);receipt['owned_client_killed']=True
                    receipt.setdefault('stdout',out[:8192].decode(errors='replace'));receipt.setdefault('stderr',err[:4096].decode(errors='replace'));receipt['exit_code']=proc.returncode
                guarded_cleanup('OWNED_CLIENT_REAP',reap_owned)
            receipt['cleanup'].append(command_result(['/usr/bin/systemctl','--user','reset-failed',unit]))
            shown=command_result(['/usr/bin/systemctl','--user','show',unit,'--property=LoadState,ActiveState,SubState,MainPID'])
            receipt['cleanup'].append(shown)
            cgpath=Path('/sys/fs/cgroup')/exact_cgroup(unit).split('::',1)[1].lstrip('/').removesuffix('/work')
            receipt['cgroup_absent_after_cleanup']=not cgpath.exists()
            receipt['cgroup_populated_zero_directly_observed']=receipt['observations'].get('worker_populated_zero_before_readback',False) and receipt['observations'].get('worker_populated_zero_after_readback',False)
            if control.exists():guarded_cleanup('SOCKET_UNLINK',control.unlink)
            guarded_cleanup('PRIVATE_DIRECTORY_REMOVE',private.rmdir)
            for fd in set(fds+[v for v in [peerpidfd,procdir,proof,work_events] if v is not None]):guarded_cleanup('DESCRIPTOR_CLOSE',lambda fd=fd:os.close(fd))
            terminal=shown.get('exit_code')==0 and all(s in shown.get('stdout','') for s in ['ActiveState=inactive','SubState=dead','MainPID=0'])
            clean=terminal and receipt['cgroup_absent_after_cleanup'] and not any('error' in c for c in receipt['cleanup'])
            receipt['unit_terminal_observed']=terminal
            if not clean:
                receipt['status']='UNKNOWN'
                receipt['cleanup_incomplete']=True
            receipt['finished_at']=now()
            with (run/'receipt.json').open('x') as stream:
                json.dump(receipt,stream,indent=2);stream.flush();os.fsync(stream.fileno())
            sync_directory(run);sync_directory(self.config.root)
        return receipt

    def verify(self,operation,warrant):
        from lab.archaioa.outcome import Applied
        from lab.archaioa.evidence import EvidenceRef
        from runtime.mission.liability import Reconciliation
        # Never bless exit code/model text. Require the independent pinned readback receipt.
        digest=SandboxOperation.parse(operation).digest
        require(digest==warrant.operation_hash,'READBACK_BINDING')
        candidates=[]
        for run in self.config.root.glob('run-*'):
            path=run/'receipt.json'
            if not path.is_file():continue
            receipt=json.loads(path.read_bytes())
            if receipt.get('operation_digest')==digest and receipt.get('warrant_digest')==warrant.digest():
                candidates.append((run,receipt,path))
        require(len(candidates)==1,'READBACK_REQUIRED')
        run,receipt,path=candidates[0]
        stored=dict(receipt['request']);require(stored.pop('schema')=='aioa.sandbox-dispatch.v1','READBACK_BINDING')
        stored['operation_bytes']=canonical_json_bytes(stored.pop('operation'))
        request=SandboxDispatchRequest(**stored)
        require(request.digest==receipt['dispatch_digest'] and run.name=='run-'+request.digest
                and request.operation_digest==digest and request.warrant_digest==warrant.digest()
                and request.operation_bytes==canonical_json_bytes(operation),'READBACK_BINDING')
        require(receipt['status']=='READBACK_VERIFIED' and receipt['cgroup_populated_zero_directly_observed']
                and receipt['cgroup_absent_after_cleanup'] and receipt['unit_terminal_observed']
                and receipt['profile_digest']==self.config.profile_digest,'UNRESOLVED_READBACK')
        expected=self.config.inputs()[operation['payload']['recipe_id']]['expected']
        for name,pin in expected.items():
            fd=os.open(run/('artifact-'+name),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
            try:
                meta=os.fstat(fd);data=os.read(fd,pin['bytes']+1)
                require(stat.S_ISREG(meta.st_mode) and meta.st_nlink==1 and len(data)==pin['bytes']
                        and hashlib.sha256(data).hexdigest()==pin['sha256'],'ARTIFACT_DIGEST_MISMATCH')
            finally:os.close(fd)
        receipt_id='sandbox-'+receipt['dispatch_digest'][:32]
        return Reconciliation(digest,Applied(receipt_id),
            EvidenceRef(receipt_id,'receipt','sha256:'+sha(path),'v1'),
            EvidenceRef('sandbox-readback-'+receipt['dispatch_digest'][:24],'independent-readback',
                        'sha256:'+canonical_sha256(receipt['observations']['pinned_readback']),'v1'))
