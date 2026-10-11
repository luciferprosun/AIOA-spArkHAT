"""Explicit offline acceptance driver; never part of ordinary unittest discovery.

Real untrusted fixture programs run only through the shared Core Linux variant.
"""
from pathlib import Path
import sys,json,hashlib,os,dataclasses,subprocess,ast
E=Path(sys.argv[1]).absolute()
W=Path(sys.argv[2]).absolute() if len(sys.argv)>2 else Path(__file__).resolve().parents[1]
sys.path[:0]=[str(W),str(W/'tests')]
from sandbox_product_support import core_case
from runtime.mission.sandbox_linux import prepare_linux_sandbox
from runtime.core_admission import Capability

OK="\nfrom pathlib import Path\nPath('/artifacts/result.txt').write_bytes(b'OK\\n')\n"
CASES={
'isolated-paths':("""import os,errno
from pathlib import Path
for name in ('/home/l/.ssh/id_rsa','/home/l/.config','/run/user/1000','/var/run/docker.sock','/nonexistent','OUTSIDE'):
    try:os.open(name,os.O_RDONLY)
    except OSError as e:assert e.errno in (errno.ENOENT,errno.EACCES,errno.EPERM)
    else:raise AssertionError('host path visible')
for name in ('/outside.txt','/home/l/escape','OUTSIDE'):
    try:Path(name).write_text('escape')
    except OSError as e:assert e.errno in (errno.ENOENT,errno.EROFS,errno.EACCES,errno.EPERM)
    else:raise AssertionError('outside write')
os.symlink('OUTSIDE','/work/link')
try:Path('/work/link').write_text('escape')
except OSError:pass
else:raise AssertionError('symlink escape')
try:os.link('OUTSIDE','/work/hardlink')
except OSError:pass
else:raise AssertionError('hardlink escape')
"""+OK,True),
'readonly-runtime':("""import os
for name in ('/usr/bin/python3.12','/inputs/recipe.py','/finalfilter','/bootstrap','/proc/sys/kernel/hostname'):
    try:os.open(name,os.O_WRONLY)
    except OSError:pass
    else:raise AssertionError('readonly policy/runtime writable')
"""+OK,True),
'network-off':("""import socket,errno
for family in (socket.AF_INET,socket.AF_INET6,socket.AF_UNIX):
    for kind in (socket.SOCK_STREAM,socket.SOCK_DGRAM):
        try:socket.socket(family,kind)
        except OSError as e:assert e.errno==errno.EPERM
        else:raise AssertionError('socket allowed')
try:socket.getaddrinfo('offline-sandbox.invalid',80)
except socket.gaierror:pass
else:raise AssertionError('DNS unexpectedly resolved')
try:socket.create_connection(('127.0.0.1',9),timeout=.1)
except OSError as e:assert e.errno==errno.EPERM
else:raise AssertionError('host loopback allowed')
"""+OK,True),
'no-authority-fds':("""import os,fcntl,errno
assert os.environ=={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent','TMPDIR':'/tmp'}
for fd in range(3,1024):
    try:fcntl.fcntl(fd,fcntl.F_GETFD)
    except OSError as e:assert e.errno==errno.EBADF
    else:raise AssertionError('inherited fd')
assert not os.path.exists('/sys/fs/cgroup')
"""+OK,True),
'bounded-memory':("""import resource
assert resource.getrlimit(resource.RLIMIT_AS)==(536870912,536870912)
try:bytearray(600*1024*1024)
except MemoryError:pass
else:raise AssertionError('memory limit not enforced')
"""+OK,True),
'bounded-pids':("""import os,time,signal,errno
children=[]
try:
    for _ in range(32):
        try:pid=os.fork()
        except OSError as e:
            assert e.errno==errno.EAGAIN;break
        if pid==0:time.sleep(30);os._exit(0)
        children.append(pid)
    else:raise AssertionError('PID limit not enforced')
    assert 1<=len(children)<16
finally:
    for pid in children:
        os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
"""+OK,True),
'bounded-disk':("""import os,errno
seen=False
for i in range(8):
    fd=os.open('/work/fill'+str(i),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        for _ in range(7):os.write(fd,b'x'*1048576)
    except OSError as e:
        assert e.errno==errno.ENOSPC;seen=True;break
    finally:os.close(fd)
assert seen
"""+OK,True),
'child-tree-timeout':("""import os,time
for _ in range(3):
    if os.fork()==0:time.sleep(30);os._exit(0)
while True:pass
""",False),
'stdout-stderr-flood':("""import os
while True:
    os.write(1,b'o'*2048);os.write(2,b'e'*2048)
""",False),
'artifact-flood':("""import os,errno
for i in range(4):
    fd=os.open('/artifacts/fill'+str(i),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        for _ in range(7):os.write(fd,b'x'*1048576)
    except OSError as e:
        assert e.errno==errno.ENOSPC;break
    finally:os.close(fd)
""",False),
'symlink-artifact':("""import os
from pathlib import Path
Path('/work/result.txt').write_bytes(b'OK\\n')
os.symlink('/work/result.txt','/artifacts/result.txt')
""",False),
'hardlink-artifact':("""import os
from pathlib import Path
Path('/artifacts/twin.txt').write_bytes(b'OK\\n')
os.link('/artifacts/twin.txt','/artifacts/result.txt')
""",False),
'wrong-artifact':("""from pathlib import Path
Path('/artifacts/result.txt').write_bytes(b'NO\\n')
print('DONE: tests all passed')
""",False),
'bad-test':("""from pathlib import Path
Path('/artifacts/result.txt').write_bytes(b'OK\\n')
assert 2+2==5
""",False),
'gate-revocation':(OK,False),
}

def main():
    with (E/'PRODUCT_MATRIX_STARTED.json').open('x') as f:json.dump({'driver':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},f)
    outside=E/'MATRIX_OUTSIDE_CANARY';outside.write_bytes(b'OUTSIDE UNCHANGED\n')
    recipes={identity:{'files':{'recipe.py':source.replace('OUTSIDE',str(outside)).encode()},'expected':{'result.txt':b'OK\n'}} for identity,(source,_) in CASES.items()}
    runtime=json.loads((E/'PYTHON_RUNTIME_PREPARATION.json').read_bytes())['manifest']
    for spec in recipes.values():ast.parse(spec['files']['recipe.py'])
    config=prepare_linux_sandbox(E/'PRODUCT_MATRIX_CONFIG',runtime,workspace='workspace-1',recipes=recipes)
    result={'profile_digest':config.profile_digest,'provider_calls':0,'cases':[]};failed=0
    for identity,(_,expected_pass) in CASES.items():
        fixture,route,warrant,args=core_case(config,identity)
        before=set(config.root.glob('run-*'));probes=[]
        if identity=='gate-revocation':
            def probe():
                probes.append(1)
                if len(probes)==4:fixture.now+=121
                return fixture.current
            route.probe=probe
        try:
            result0=route.dispatch(fixture.fx.p(),**args)
            assert result0['outcome']['contract_type']=='Unknown'
            new=set(config.root.glob('run-*'))-before;assert len(new)==1
            path=next(iter(new))/'receipt.json';receipt=json.loads(path.read_bytes())
            assert receipt['cgroup_absent_after_cleanup'] and receipt['unit_terminal_observed']
            assert outside.read_bytes()==b'OUTSIDE UNCHANGED\n'
            if expected_pass:
                assert receipt['status']=='READBACK_VERIFIED',receipt.get('error')
                assert route.reconcile(fixture.fx.p(),warrant,1)['outcome']['contract_type']=='Applied'
            else:
                assert receipt['status']=='UNKNOWN',receipt
                try:route.reconcile(fixture.fx.p(),warrant,1)
                except ValueError:pass
                else:raise AssertionError('negative became Applied')
            cause=receipt.get('error',{})
            terminal=receipt['observations'].get('worker_terminal',{})
            if identity=='symlink-artifact':assert cause.get('errno')==40,cause
            if identity=='hardlink-artifact':assert 'INVALID_ARTIFACT_METADATA' in cause.get('message',''),cause
            if identity=='wrong-artifact':assert 'ARTIFACT_DIGEST_MISMATCH' in cause.get('message',''),cause
            if identity=='bad-test':
                assert 'AssertionError' in terminal.get('stderr','') and terminal.get('child_exit_code')!=0,terminal
                assert receipt['observations']['pinned_readback']['result.txt']['sha256']==hashlib.sha256(b'OK\n').hexdigest()
            if identity=='artifact-flood':assert cause.get('errno')==2 and terminal.get('child_exit_code')==0,(cause,terminal)
            retained=route.dispatch(fixture.fx.p(),**args)
            assert set(config.root.glob('run-*'))-before==new
            if identity=='child-tree-timeout':assert receipt['observations']['worker_terminal']['termination_reason']=='TIMEOUT'
            if identity=='stdout-stderr-flood':assert receipt['observations']['worker_terminal']['termination_reason']=='OUTPUT_LIMIT'
            if identity=='gate-revocation':assert not receipt['project_code_started'] and len(probes)==4
            item={'case':identity,'status':'PASS','receipt':str(path),'effect_status':receipt['status'],'retained':retained['outcome']['contract_type']}
        except Exception as exc:
            failed+=1;item={'case':identity,'status':'FAIL','error':str(exc)[:2048],'type':type(exc).__name__}
        finally:fixture.doCleanups()
        result['cases'].append(item);print(json.dumps(item),flush=True)
    result['status']='PASS' if not failed else 'FAIL';result['failed']=failed
    with (E/'PRODUCT_MATRIX_RESULT.json').open('x') as f:json.dump(result,f,indent=2)
    return bool(failed)
if __name__=='__main__':raise SystemExit(main())
