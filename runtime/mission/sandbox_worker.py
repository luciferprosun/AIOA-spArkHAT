"""Trusted supervisor for one delegated worker; no authority is derived here."""
from pathlib import Path
import errno,json,os,select,selectors,subprocess,sys,time
P=None

def exact_cgroup(unit):
    return '0::/user.slice/user-%d.slice/user@%d.service/app.slice/%s/work'%(os.getuid(),os.getuid(),unit)

def sandbox_argv(p,fd,control,nonce):
    limits=p['limits']
    a=['/usr/bin/bwrap','--die-with-parent','--new-session','--unshare-user','--unshare-ipc',
       '--unshare-pid','--unshare-net','--unshare-uts','--unshare-cgroup','--disable-userns',
       '--assert-userns-disabled','--uid',str(os.getuid()),'--gid',str(os.getgid()),'--cap-drop','ALL',
       '--hostname','aioa-sandbox','--clearenv','--proc','/proc','--remount-ro','/proc']
    # The manifest contains regular, private, content-pinned snapshot files.
    for destination,entry in sorted(p['runtime'].items()):a+=['--ro-bind',entry['snapshot'],destination]
    for name,source in sorted(p['inputs'].items()):a+=['--ro-bind',source,'/inputs/'+name]
    for name,source in [('bootstrap',p['bootstrap']),('finalfilter',p['final_filter']),('control',control)]:
        a+=['--ro-bind',source,'/'+name]
    for name in ('null','zero','urandom'):a+=['--dev-bind','/dev/'+name,'/dev/'+name]
    for name,key in [('work','work_bytes'),('tmp','tmp_bytes'),('artifacts','artifacts_bytes')]:
        a+=['--size',str(limits[key]),'--tmpfs','/'+name]
    return a+['--remount-ro','/','--chdir','/work','--seccomp',str(fd),'--','/bootstrap',nonce]

def bounded_output(worker,work,p):
    maximum=p['limits']['max_output_bytes'];deadline=time.monotonic()+p['limits']['timeout_ms']/1000
    streams=selectors.DefaultSelector();out=bytearray();err=bytearray();reason='EXITED'
    for stream,target in [(worker.stdout,out),(worker.stderr,err)]:
        os.set_blocking(stream.fileno(),False);streams.register(stream,selectors.EVENT_READ,target)
    try:
        while streams.get_map():
            if time.monotonic()>=deadline:reason='TIMEOUT';break
            for key,_ in streams.select(min(.05,max(0,deadline-time.monotonic()))):
                chunk=os.read(key.fd,4096)
                if not chunk:streams.unregister(key.fileobj);continue
                room=maximum-len(out)-len(err)
                key.data.extend(chunk[:max(0,room)])
                if len(chunk)>room:reason='OUTPUT_LIMIT';break
            if reason!='EXITED':break
        if reason!='EXITED':(work/'cgroup.kill').write_text('1')
        try:worker.wait(timeout=2)
        except subprocess.TimeoutExpired:
            (work/'cgroup.kill').write_text('1');worker.wait(timeout=2);reason='TIMEOUT'
        return bytes(out),bytes(err),reason
    finally:
        streams.close();worker.stdout.close();worker.stderr.close()

class ChildFailure(RuntimeError):
    def __init__(self,report):self.report=report;super().__init__('TRUSTED_CHILD_FAILURE')

def bounded_line(stream,seconds=8):
    data=bytearray();deadline=time.monotonic()+seconds
    while time.monotonic()<deadline and len(data)<8192:
        ready,_,_=select.select([stream.fileno()],[],[],max(0,deadline-time.monotonic()))
        if not ready:break
        byte=os.read(stream.fileno(),1)
        if not byte:break
        data.extend(byte)
        if byte==b'\n':
            value=json.loads(data)
            if value.get('stage')=='CHILD_FAILED':raise ChildFailure(value)
            return value
    raise RuntimeError('BOUNDED_PROTOCOL_LINE_MISSING')

def populated(fd):
    os.lseek(fd,0,os.SEEK_SET)
    values=dict(line.split() for line in os.read(fd,4096).decode().splitlines())
    assert values.get('populated') in {'0','1'}
    return values['populated']

def child(unit,control,nonce,config):
    global P
    P=json.loads(Path(config).read_text())
    worker=None;work=None;event=fd=gate_read=gate_write=None
    result=88;failure=None;cleanup=[];stage='DELEGATED_SERVICE_IDENTITY'
    try:
        p=P;raw=Path('/proc/self/cgroup').read_text().strip()
        expected=exact_cgroup(unit).removesuffix('/work')
        assert raw==expected+'/supervisor',raw
        cg=Path('/sys/fs/cgroup')/expected.split('::',1)[1].lstrip('/')
        limits={n:(cg/n).read_text().strip() for n in ['memory.max','memory.swap.max','pids.max','cpu.max']}
        assert limits=={'memory.max':str(p['limits']['memory_bytes']),'memory.swap.max':'0','pids.max':str(p['limits']['pids_max']),'cpu.max':str(p['limits']['cpu_quota_us'])+' '+str(p['limits']['cpu_period_us'])}
        assert 'NoNewPrivs:\t1' in Path('/proc/self/status').read_text()
        stage='CREATE_OWN_WORK_CGROUP';work=cg/'work';work.mkdir()
        stage='PIN_WORK_CGROUP_EVENTS';event=os.open(work/'cgroup.events',os.O_RDONLY|os.O_CLOEXEC)
        fd=os.open(Path(p['setup_filter']),os.O_RDONLY|os.O_CLOEXEC)
        gate_read,gate_write=os.pipe2(os.O_CLOEXEC)
        assert populated(event)=='0'
        stage='SPAWN_BLOCKED_TRUSTED_GATE'
        argv=[p['gate'],str(gate_read),exact_cgroup(unit)+'\n',*sandbox_argv(p,fd,control,nonce)]
        worker=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            pass_fds=(gate_read,fd),env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        os.close(gate_read);gate_read=None
        stage='PLACE_OWN_UNREAPED_WORKER_BEFORE_EXEC'
        (work/'cgroup.procs').write_text(str(worker.pid))
        assert Path('/proc/'+str(worker.pid)+'/cgroup').read_text().strip()==exact_cgroup(unit)
        assert populated(event)=='1'
        print(json.dumps({'stage':'WORK_READY','worker_pid':worker.pid,'work_cgroup':str(work),'limits':limits,'before_exec_placement':True}),flush=True)
        stage='WAIT_FOR_EXTERNAL_EVENTS_PIN'
        assert os.read(0,1)==b'G'
        os.write(gate_write,b'G');os.close(gate_write);gate_write=None
        stage='WAIT_FOR_TRUSTED_SANDBOX_EXIT';out,err,reason=bounded_output(worker,work,p)
        stage='SEAL_SPAWN_MIGRATION_AND_KILL_WORK'
        (work/'cgroup.kill').write_text('1')
        deadline=time.monotonic()+2
        while populated(event)!='0' and time.monotonic()<deadline:time.sleep(.01)
        assert populated(event)=='0'
        print(json.dumps({'stage':'WORK_EMPTY','child_exit_code':worker.returncode,'termination_reason':reason,'stdout':out[:p['limits']['max_output_bytes']].decode(errors='replace'),'stderr':err[:p['limits']['max_output_bytes']].decode(errors='replace'),'worker_populated':'0','spawn_and_migration_sealed':True}),flush=True)
        stage='WAIT_FOR_READBACK_DONE';assert os.read(0,1)==b'R'
        assert populated(event)=='0'
        result=worker.returncode if 0<=worker.returncode<=255 else 87
    except Exception as exc:
        failure={'stage':stage,'type':type(exc).__name__,'errno':getattr(exc,'errno',None),
                 'name':errno.errorcode.get(getattr(exc,'errno',None)),'message':str(exc)[:512]}
    finally:
        def clean(name,callback):
            try:callback()
            except Exception as exc:cleanup.append({'stage':name,'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
        if work is not None:clean('OWN_WORK_KILL',lambda:(work/'cgroup.kill').write_text('1'))
        if worker is not None and worker.poll() is None:clean('OWN_WORKER_REAP',lambda:worker.wait(timeout=2))
        for value in [event,fd,gate_read,gate_write]:
            if value is not None:clean('FD_CLOSE',lambda value=value:os.close(value))
        if work is not None:clean('OWN_WORK_REMOVE',work.rmdir)
        if failure is not None or cleanup:
            print(json.dumps({'stage':'CHILD_FAILED','original_failure':failure,'cleanup_errors':cleanup}),flush=True)
            result=88
    return result

if __name__=='__main__':
    if len(sys.argv)!=5:raise SystemExit(89)
    raise SystemExit(child(*sys.argv[1:]))
